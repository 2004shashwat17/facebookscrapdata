import os
import time
import csv
from bs4 import BeautifulSoup

try:
    from fb_login import main as fb_login_main
    FB_LOGIN_AVAILABLE = True
except Exception:
    fb_login_main = None
    FB_LOGIN_AVAILABLE = False

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


def manual_login_fallback():
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.facebook.com/login")
    input("Please log into Facebook in the opened browser window, then press Enter here to continue...")
    return driver


def expand_comments(driver, max_clicks=30):
    # Try clicking common 'view more' buttons until none left or limit reached
    clicked = 0
    for _ in range(max_clicks):
        try:
            # common phrases for loading more comments
            btn = None
            xpaths = [
                "//div[@role='button' and (contains(., 'View more comments') or contains(., 'See more comments') or contains(., 'View previous comments') or contains(., 'Load more comments') or contains(., 'Show more comments'))]",
                "//a[contains(., 'View more comments') or contains(., 'See more comments') or contains(., 'View previous comments') or contains(., 'Load more comments') or contains(., 'Show more comments')]",
                "//span[contains(., 'View more comments') or contains(., 'See more comments')]",
            ]
            for xp in xpaths:
                try:
                    # If a modal/dialog is present, search inside it first
                    modal = None
                    try:
                        modal = driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"]')
                    except Exception:
                        modal = None

                    if modal:
                        elems = modal.find_elements(By.XPATH, xp)
                    else:
                        elems = driver.find_elements(By.XPATH, xp)
                    if elems:
                        for e in elems:
                            if e.is_displayed():
                                btn = e
                                break
                    if btn:
                        break
                except Exception:
                    continue

            if not btn:
                break

            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.5)
            try:
                btn.click()
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", btn)
                except Exception:
                    break
            clicked += 1
            time.sleep(1.2)
        except Exception:
            break
    return clicked


def scrape_post_comments(driver, post_url, max_comments=500):
    driver.get(post_url)
    time.sleep(5)
    # ensure feed/post loaded
    driver.execute_script("window.scrollTo(0, 400);")
    time.sleep(1)

    # If the post opened in a modal dialog, we need to scroll the modal's right-side scrollable container
    modal = None
    try:
        modal = driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"]')
    except Exception:
        modal = None

    # Try to scroll the modal container (if any) so comments load in that container
    if modal:
        try:
            scroll_modal_until_end(driver, modal, max_idle_cycles=6, pause=0.6)
        except Exception:
            pass

    expand_comments(driver, max_clicks=40)

    # After expansion, take page source and parse
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')

    results = []
    # Look for article/ post blocks which often contain comments as nested articles
    comment_blocks = []
    # Strategy 1: find elements with role='article' and that contain 'comment' text
    for div in soup.find_all('div', attrs={'role': 'article'}):
        # Heuristic: if block contains 'a' link (likely author)
        if div.find('a', href=True):
            comment_blocks.append(div)

    # Fallback: find elements with data-testid containing 'UFI2Comment'
    if not comment_blocks:
        comment_blocks = soup.find_all(lambda t: t.name == 'div' and t.get('data-testid') and 'UFI2Comment' in t.get('data-testid'))

    # Extract author and text heuristically
    for block in comment_blocks:
        try:
            author = ''
            profile = ''
            # author link
            a = block.find('a', href=True)
            if a:
                author = a.get_text(strip=True)
                profile = a['href']

            # comment text: look for a span with visible text but not the author
            comment_text = ''
            # try message containers
            msg = block.find('div', attrs={'data-ad-preview': 'message'})
            if msg:
                comment_text = msg.get_text(separator=' ', strip=True)
            else:
                # fallback: gather span texts
                spans = block.find_all('span')
                texts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
                # remove author occurrences
                texts = [t for t in texts if author not in t]
                comment_text = ' '.join(texts[:6])

            if not comment_text and not author:
                continue

            results.append({'author': author, 'profile': profile, 'text': comment_text})
            if len(results) >= max_comments:
                break
        except Exception:
            continue

    # Attempt to close modal/dialog after scraping so caller can proceed to next post
    try:
        close_modal(driver)
    except Exception:
        pass
    return results


def close_modal(driver):
    try:
        # try find close button inside dialog
        try:
            close_btn = driver.find_element(By.XPATH, "//div[@role='dialog']//div[@aria-label='Close']")
        except Exception:
            try:
                close_btn = driver.find_element(By.XPATH, "//div[@aria-label='Close']")
            except Exception:
                close_btn = None

        if close_btn:
            try:
                driver.execute_script('arguments[0].click();', close_btn)
                time.sleep(0.4)
                return True
            except Exception:
                pass

        # fallback: send ESCAPE
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
        time.sleep(0.4)
        return True
    except Exception:
        return False


def scroll_modal_until_end(driver, modal_element, max_idle_cycles=6, pause=0.8, max_scrolls=200):
    """Scroll the modal's inner container until no new content appears.

    Strategy:
    - Find a likely scrollable container inside the modal (several candidate selectors).
    - Repeatedly set scrollTop to scrollHeight and wait.
    - Consider progress when either scrollHeight increases or the number of comment blocks increases.
    - Stop when neither metric changes for `max_idle_cycles` iterations or after `max_scrolls` attempts.
    - While scrolling, attempt to click "view more/see more" buttons inside the modal so replies load.
    """
    candidates = [
        "div.x14nfmen",
        "div.x1uvtmcs",
        "div[style*='overflow']",
        "div[role='dialog'] div[role='presentation']",
        "div[role='dialog'] div[aria-label]",
    ]

    container = None
    for sel in candidates:
        try:
            elems = modal_element.find_elements(By.CSS_SELECTOR, sel)
            if elems:
                container = elems[-1]
                break
        except Exception:
            continue

    if container is None:
        # fallback: pick element with largest scrollHeight
        try:
            elems = modal_element.find_elements(By.CSS_SELECTOR, 'div')
            best = None
            best_scroll = 0
            for e in elems:
                try:
                    scroll_h = driver.execute_script('return arguments[0].scrollHeight || 0', e)
                    client_h = driver.execute_script('return arguments[0].clientHeight || 0', e)
                    if scroll_h and scroll_h > client_h and scroll_h > best_scroll:
                        best = e
                        best_scroll = scroll_h
                except Exception:
                    continue
            container = best
        except Exception:
            container = None

    if container is None:
        return False

    prev_scroll = -1
    prev_count = -1
    idle = 0
    attempts = 0

    while idle < max_idle_cycles and attempts < max_scrolls:
        attempts += 1
        try:
            # click any "view more" buttons that appear inside the modal
            try:
                view_xp = "//div[@role='dialog']//div[@role='button' and (contains(., 'View more') or contains(., 'See more') or contains(., 'Load more'))]"
                btns = modal_element.find_elements(By.XPATH, view_xp)
                for b in btns:
                    try:
                        if b.is_displayed():
                            driver.execute_script('arguments[0].scrollIntoView(true);', b)
                            time.sleep(0.2)
                            try:
                                b.click()
                            except Exception:
                                driver.execute_script('arguments[0].click();', b)
                            time.sleep(0.3)
                    except Exception:
                        continue
            except Exception:
                pass

            # read current metrics
            scroll_h = driver.execute_script('return arguments[0].scrollHeight || 0', container)
            # count comment-like blocks inside modal
            c_count = 0
            try:
                c_count = len(modal_element.find_elements(By.XPATH, 
                    "//div[@role='dialog']//div[@data-testid and contains(@data-testid, 'UFI2Comment')]"))
            except Exception:
                try:
                    c_count = len(modal_element.find_elements(By.XPATH, "//div[@role='dialog']//div[@role='article']"))
                except Exception:
                    c_count = 0

            # scroll to bottom
            try:
                driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', container)
            except Exception:
                try:
                    driver.execute_script('arguments[0].scrollTop += 800', container)
                except Exception:
                    pass

            time.sleep(pause)

            # re-evaluate
            new_scroll_h = driver.execute_script('return arguments[0].scrollHeight || 0', container)
            new_count = 0
            try:
                new_count = len(modal_element.find_elements(By.XPATH, 
                    "//div[@role='dialog']//div[@data-testid and contains(@data-testid, 'UFI2Comment')]"))
            except Exception:
                try:
                    new_count = len(modal_element.find_elements(By.XPATH, "//div[@role='dialog']//div[@role='article']"))
                except Exception:
                    new_count = 0

            progressed = False
            if new_scroll_h > prev_scroll:
                progressed = True
            if new_count > prev_count:
                progressed = True

            prev_scroll = new_scroll_h
            prev_count = new_count

            if progressed:
                idle = 0
            else:
                idle += 1

        except Exception:
            idle += 1

    return True


def collect_post_links(driver, profile_url, max_posts=10, max_scrolls=15):
    """Scroll a profile/page and collect candidate post links (permaliinks)."""
    driver.get(profile_url)
    time.sleep(4)
    collected = []
    seen = set()
    scrolls = 0
    while len(collected) < max_posts and scrolls < max_scrolls:
        # gather anchors
        anchors = driver.find_elements(By.TAG_NAME, 'a')
        for a in anchors:
            try:
                href = a.get_attribute('href')
                if not href:
                    continue
                # candidate patterns for post links
                if any(x in href for x in ['/posts/', '/permalink.php', '/photos/']) and href not in seen:
                    seen.add(href)
                    collected.append(href)
                    if len(collected) >= max_posts:
                        break
            except Exception:
                continue

        # scroll down to load more posts
        driver.execute_script('window.scrollBy(0, 1000);')
        time.sleep(1.2)
        scrolls += 1

    return collected


def main():
    print('Starting minimal comment scraper')
    driver = None
    if FB_LOGIN_AVAILABLE:
        try:
            driver = fb_login_main()
        except Exception as e:
            print('fb_login failed:', e)
            driver = None

    if driver is None:
        driver = manual_login_fallback()

    user_input = input('Enter the Facebook post or profile URL to scrape comments from: ').strip()
    if not user_input:
        print('No URL provided, exiting')
        driver.quit()
        return

    # Ask how many posts the user wants to scrape (default 1)
    try:
        posts_to_scrape = int(input('How many posts would you like to scrape? [default 1]: ').strip() or '1')
        if posts_to_scrape < 1:
            posts_to_scrape = 1
    except Exception:
        posts_to_scrape = 1

    # If the user provided a profile URL (not a direct post permalink), collect recent post links and show them
    post_url = user_input
    is_profile = not any(x in user_input for x in ['/posts/', '/permalink.php', '/photo.php', '/photos/'])
    selected_links = None
    if is_profile:
        print('[*] Detected profile/page URL. Collecting recent post links...')
        links = collect_post_links(driver, user_input, max_posts=posts_to_scrape)
        if not links:
            print('No post links found on this profile/page. You can enter a direct post URL instead.')
        else:
            print('\nRecent post links found:')
            for i, l in enumerate(links, start=1):
                print(f"  {i}. {l}")
            print('\nEnter the number of the post to scrape, or \"a\" to scrape all listed posts, or 0 to cancel.')
            choice = input('Selection: ').strip().lower()
            if choice == '0' or choice == 'c':
                print('Cancelled.')
                driver.quit()
                return
            if choice == 'a':
                # honor the requested posts_to_scrape count
                selected_links = links[:posts_to_scrape]
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(links):
                        post_url = links[idx]
                    else:
                        print('Invalid selection, exiting.')
                        driver.quit()
                        return
                except Exception:
                    print('Invalid input, exiting.')
                    driver.quit()
                    return

    out_dir = os.path.join(os.path.dirname(__file__), 'facebook_data')
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, 'comments_output.csv')

    try:
        if selected_links:
            # Scrape all collected links and combine
            combined = []
            for link in selected_links:
                print(f'[*] Scraping post: {link}')
                res = scrape_post_comments(driver, link, max_comments=500)
                for r in res:
                    r['post_url'] = link
                combined.extend(res)
            results = combined
        else:
            results = scrape_post_comments(driver, post_url, max_comments=1000)

        if results:
            # If multiple posts, include post_url column
            keys = ['post_url', 'author', 'profile', 'text'] if any('post_url' in r for r in results) else ['author', 'profile', 'text']
            with open(out_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                for r in results:
                    # ensure all keys present
                    row = {k: r.get(k, '') for k in keys}
                    writer.writerow(row)
            print(f'✅ Saved {len(results)} comments to {out_file}')
        else:
            print('⚠️ No comments found or extraction failed (try increasing expansion attempts).')
    except Exception as e:
        print('Error during scraping:', e)
    finally:
        input('Press Enter to close browser...')
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()
