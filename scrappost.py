import os
import sys
import time
import hashlib
import csv
import argparse
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

# Default profile to avoid entering URL repeatedly
DEFAULT_PROFILE = 'https://www.facebook.com/PizzaPizzaCanada'


def setup_argument_parser():
    """Set up command-line argument parser."""
    parser = argparse.ArgumentParser(
        description='Scrape Facebook post content - URLs, captions, images',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --profile https://www.facebook.com/BeingSalmanKhan --posts 15
  %(prog)s --profile https://www.facebook.com/PizzaPizzaCanada --posts 100 --output my_posts.csv
  %(prog)s  # Uses default profile and interactive prompts
        """
    )
    
    parser.add_argument(
        '--profile', '-p',
        type=str,
        help=f'Facebook profile URL to scrape (default: {DEFAULT_PROFILE})'
    )
    
    parser.add_argument(
        '--posts', '-n',
        type=int,
        help='Number of posts to scrape (default: 100)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='scrap.post.csv',
        help='Output CSV filename (default: scrap.post.csv)'
    )
    
    return parser


def validate_facebook_url(url):
    """Validate and normalize Facebook profile URL."""
    if not url or not url.strip():
        return None
        
    url = url.strip()
    
    # Add https:// if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Parse and validate URL
    try:
        parsed = urlparse(url)
        if 'facebook.com' not in parsed.netloc.lower():
            raise ValueError("URL must be a Facebook profile")
        
        # Normalize URL
        normalized = urlunparse((
            'https',
            'www.facebook.com',
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
        
        return normalized
    except Exception as e:
        raise ValueError(f"Invalid Facebook URL: {e}")


def confirm_scraping_parameters(profile_url, num_posts, output_file):
    """Display scraping parameters and get user confirmation."""
    print("\n" + "="*60)
    print("FACEBOOK POST SCRAPER - CONFIGURATION")
    print("="*60)
    print(f"Profile URL: {profile_url}")
    print(f"Posts to scrape: {num_posts}")
    print(f"Output file: {output_file}")
    print("="*60)
    
    while True:
        choice = input("\nProceed with scraping? (y/n): ").strip().lower()
        if choice in ['y', 'yes']:
            return True
        elif choice in ['n', 'no']:
            print("Scraping cancelled.")
            return False
        else:
            print("Please enter 'y' for yes or 'n' for no.")


def get_scraping_parameters():
    """Get scraping parameters from command line or interactive input."""
    parser = setup_argument_parser()
    args = parser.parse_args()
    
    # Determine profile URL
    if args.profile:
        try:
            profile_url = validate_facebook_url(args.profile)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
    else:
        # Interactive mode for profile
        profile = input(f'Enter the profile URL (or press Enter for default {DEFAULT_PROFILE}): ').strip()
        if not profile:
            profile_url = DEFAULT_PROFILE
        else:
            try:
                profile_url = validate_facebook_url(profile)
            except ValueError as e:
                print(f"Error: {e}")
                sys.exit(1)
    
    # Determine number of posts
    if args.posts:
        num_posts = args.posts
        if num_posts <= 0:
            print("Error: Number of posts must be positive")
            sys.exit(1)
    else:
        # Interactive mode for posts
        try:
            user_input = input('How many posts to scrape? [default 100]: ').strip()
            num_posts = int(user_input) if user_input else 100
            if num_posts <= 0:
                print("Error: Number of posts must be positive")
                sys.exit(1)
        except ValueError:
            print("Error: Invalid number of posts")
            sys.exit(1)
    
    # Output file
    output_file = args.output
    
    return profile_url, num_posts, output_file


def manual_login_fallback():
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.facebook.com/login")
    input("Please log into Facebook in the opened browser window, then press Enter here to continue...")
    return driver


def collect_posts_on_profile(driver, profile_url, max_posts=10, max_scrolls=200, pause=1.5):
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

                # defer uid creation until after we extract caption/images so
                # we can build a more robust identifier (avoid skipping posts
                # that have no visible caption or no permalink).
                # uid will be computed below.

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

                # build unique id and dedupe (robust)
                unique_raw = ''
                if post_url:
                    unique_raw = post_url
                elif caption_text:
                    unique_raw = caption_text[:400]
                else:
                    # try data-ft or element attributes, else fall back to outerHTML
                    unique_raw = (p.get_attribute('data-ft') or '')
                    if not unique_raw:
                        unique_raw = (p.get_attribute('id') or '')
                    if not unique_raw:
                        unique_raw = (p.get_attribute('data-testid') or '')
                    if not unique_raw:
                        outer = p.get_attribute('outerHTML') or ''
                        unique_raw = outer[:2000]

                if not unique_raw:
                    # last resort: skip this post if we truly cannot identify it
                    continue

                uid = hashlib.sha1(unique_raw.encode('utf-8')).hexdigest()
                # signature: short, human-readable snippet from unique_raw used to re-find the card
                sig = (unique_raw[:400]).strip()
                if uid in seen:
                    continue
                seen.add(uid)

                collected.append({'post_url': post_url or '', 'caption': caption_text, 'images': images, 'uid': uid, 'signature': sig})
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
    """Main function to run the Facebook post scraper."""
    driver = None
    try:
        # Get scraping parameters
        profile_url, num_posts, output_file = get_scraping_parameters()
        
        # Confirm parameters with user
        if not confirm_scraping_parameters(profile_url, num_posts, output_file):
            sys.exit(0)
        
        # Initialize WebDriver
        if FB_LOGIN_AVAILABLE:
            try:
                driver = fb_login_main()
                print("\n✓ Facebook login successful")
            except Exception as e:
                print(f'\n⚠ fb_login failed: {e}')
                driver = None

        if driver is None:
            print("\n→ Using manual login fallback...")
            driver = manual_login_fallback()

        print(f"\n→ Starting to scrape {num_posts} posts from profile...")
        posts = collect_posts_on_profile(driver, profile_url, max_posts=num_posts)
        
        print(f"→ Saving {len(posts)} posts to CSV...")
        out_path = save_posts_csv(posts, output_file)
        
        print(f"\n✓ Scraping completed successfully!")
        print(f"✓ Posts saved to: {out_path}")
        print(f"✓ Total posts scraped: {len(posts)}")

    except KeyboardInterrupt:
        print("\n\n⚠ Scraping interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during scraping: {e}")
        sys.exit(1)
    finally:
        try:
            if driver:
                driver.quit()
                print("→ Browser closed")
        except Exception:
            pass


if __name__ == '__main__':
    main()