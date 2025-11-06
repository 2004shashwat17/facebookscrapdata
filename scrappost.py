import os
import time
import csv
from urllib.parse import urlparse, urlunparse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, InvalidSessionIdException

try:
    from fb_login import main as fb_login_main
    FB_LOGIN_AVAILABLE = True
except Exception:
    fb_login_main = None
    FB_LOGIN_AVAILABLE = False


def manual_login_fallback():
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.facebook.com/login")
    input("Please log into Facebook in the opened browser window, then press Enter here to continue...")
    return driver


def collect_posts_on_profile(driver, profile_url, max_posts=10, max_scrolls=40, pause=1.5):
    """Two-phase collection:

    1) Slowly scroll the profile and gather post permalinks (canonicalized).
    2) Visit each permalink in the same tab (with retries and slow incremental
       scrolling), click 'See more' when present, and extract caption + images.

    Returns a list of dicts: {'post_url','caption','images'}.
    """
    # navigate to profile once and then extract each post in-place (no navigation)
    try:
        driver.get(profile_url)
    except (WebDriverException, InvalidSessionIdException):
        raise
    time.sleep(2.6)

    collected = []
    seen = set()
    scrolls = 0

    def normalize_post_url(url: str) -> str:
        if not url:
            return ''
        try:
            p = urlparse(url)
            path = p.path.rstrip('/')
            return urlunparse((p.scheme, p.netloc, path, '', '', ''))
        except Exception:
            return url.split('?')[0].rstrip('/')

    # ensure a reasonable minimum pause
    if pause < 0.8:
        pause = 0.8

    # loop: scan visible post cards, extract from each in-place, then scroll more
    while len(collected) < max_posts and scrolls < max_scrolls:
        posts = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
        for p in posts:
            if len(collected) >= max_posts:
                break
            try:
                # try to get a permalink for dedupe if available (more robust)
                post_url = ''
                try:
                    anchors = p.find_elements(By.TAG_NAME, 'a')
                    candidates = []
                    for a in anchors:
                        try:
                            href = (a.get_attribute('href') or '').strip()
                        except Exception:
                            href = ''
                        if not href:
                            continue
                        # common permalink/link patterns
                        if any(x in href for x in ['/posts/', 'permalink.php', '/photos/', '/videos/', 'story.php', 'ft_ent_identifier', 'story_fbid', '/photo.php', '/media/set']):
                            candidates.append(href)
                        # also accept direct facebook.com or m.facebook.com links as fallback
                        elif 'facebook.com' in href or 'm.facebook.com' in href:
                            candidates.append(href)

                    # prefer candidates with explicit post identifiers
                    chosen = None
                    for pref in ['/posts/', 'story.php', 'permalink.php', '/photo.php', '/photos/', '/videos/']:
                        for c in candidates:
                            if pref in c:
                                chosen = c
                                break
                        if chosen:
                            break
                    if not chosen and candidates:
                        chosen = candidates[0]

                    if chosen:
                        post_url = normalize_post_url(chosen)
                except Exception:
                    post_url = ''

                # If still no permalink, try to parse data-ft (top_level_post_id)
                if not post_url:
                    try:
                        data_ft = p.get_attribute('data-ft') or ''
                        if data_ft:
                            import re
                            m = re.search(r'top_level_post_id\"?\s*[:=]\s*\"?(\d+(?:_\d+)?)\"?', data_ft)
                            if m:
                                tid = m.group(1)
                                # if format owner_post, split and craft a posts URL
                                if '_' in tid:
                                    owner, post = tid.split('_', 1)
                                    post_url = normalize_post_url(f"https://www.facebook.com/{owner}/posts/{post}")
                                else:
                                    post_url = normalize_post_url(f"https://www.facebook.com/{tid}")
                    except Exception:
                        pass

                uid = post_url

                # NOTE: per user request, do NOT click anything (no 'See more').
                # Only extract the visible caption text and image srcs as-is.

                # extract caption from this post card
                caption_text = ''
                try:
                    msg = p.find_element(By.CSS_SELECTOR, "div[data-ad-preview='message']")
                    caption_text = (msg.text or '').strip()
                except Exception:
                    caption_text = ''

                if not caption_text:
                    try:
                        spans = p.find_elements(By.CSS_SELECTOR, "span[dir='auto']")
                        for s in spans:
                            try:
                                t = (s.text or '').strip()
                                if not t:
                                    continue
                                low = t.lower()
                                skip_words = ['like', 'comment', 'comments', 'share', 'see more', 'reply', 'edited', 'follow']
                                if any(sw in low for sw in skip_words):
                                    continue
                                if low.isdigit():
                                    continue
                                caption_text = t
                                break
                            except Exception:
                                continue
                    except Exception:
                        caption_text = ''

                # images inside the post card
                images = []
                try:
                    imgs = p.find_elements(By.TAG_NAME, 'img')
                    for im in imgs:
                        try:
                            src = im.get_attribute('src') or im.get_attribute('data-src') or ''
                            if src and 'profile' not in src and src not in images:
                                images.append(src)
                        except Exception:
                            continue
                except Exception:
                    images = []

                # build unique id and dedupe
                if not uid:
                    uid = (caption_text[:200] if caption_text else None)
                if not uid:
                    continue
                if uid in seen:
                    continue
                seen.add(uid)

                collected.append({'post_url': post_url or '', 'caption': caption_text, 'images': images})
                time.sleep(0.25)

            except InvalidSessionIdException:
                raise
            except Exception:
                continue

        # incremental scroll further down the profile feed
        try:
            driver.execute_script('window.scrollBy(0, 700);')
        except Exception:
            try:
                driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            except Exception:
                pass
        time.sleep(pause)
        scrolls += 1

    return collected


def save_posts_csv(posts, filename='scrap.post.csv'):
    out_dir = os.path.join(os.path.dirname(__file__), 'facebook_data')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    # use 'caption' (preserve emojis) instead of generic 'text'
    keys = ['post_url', 'caption', 'images']

    def _write(path):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for p in posts:
                row = {
                    'post_url': p.get('post_url', ''),
                    'caption': p.get('caption', '').replace('\n', ' ').strip(),
                    'images': ';'.join(p.get('images', []))
                }
                writer.writerow(row)

    try:
        _write(out_path)
        return out_path
    except PermissionError:
        # fallback: write to an alternate filename with a timestamp (file may be locked by another process)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        if filename.lower().endswith('.csv'):
            alt_name = filename[:-4] + f'_{ts}.csv'
        else:
            alt_name = filename + f'_{ts}'
        alt_path = os.path.join(out_dir, alt_name)
        try:
            _write(alt_path)
            print(f"[!] Permission denied writing {out_path}. Saved to alternate file: {alt_path}")
            return alt_path
        except Exception as e:
            # re-raise original problem with context
            raise


def main():
    print('ScrapPost: extract posts (text + image srcs) from a profile')
    driver = None
    try:
        if FB_LOGIN_AVAILABLE:
            try:
                driver = fb_login_main()
            except Exception as e:
                print('fb_login failed:', e)
                driver = None

        if driver is None:
            driver = manual_login_fallback()

        profile = input('Enter the profile URL (or press Enter for default): ').strip()
        if not profile:
            profile = 'https://www.facebook.com/deepakmalik.monro'

        try:
            n = int(input('How many posts to scrape? [default 5]: ').strip() or '5')
        except Exception:
            n = 5

        posts = collect_posts_on_profile(driver, profile, max_posts=n)
        print(f'Collected {len(posts)} posts')
        out = save_posts_csv(posts, 'scrap.post.csv')
        print('Saved posts to', out)

    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()
