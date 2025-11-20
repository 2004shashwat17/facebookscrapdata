import os
import sys
import time
import hashlib
import csv
import random
import re
import pyautogui
import signal
import atexit
from urllib.parse import urlparse, urlunparse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException, InvalidSessionIdException, TimeoutException, 
    NoSuchElementException, StaleElementReferenceException
)

try:
    from fb_login import main as fb_login_main
    FB_LOGIN_AVAILABLE = True
except Exception:
    fb_login_main = None
    FB_LOGIN_AVAILABLE = False

# Configuration
DEFAULT_PROFILE = 'https://www.facebook.com/bjp4bihar'
OUTPUT_DIR = 'facebook_data'
MAX_POSTS = 20
SCROLL_PAUSE_TIME = 3
SHARE_POPUP_TIMEOUT = 8
COMMENT_POPUP_TIMEOUT = 10
COMMENT_SCROLLS = 6
COMMENT_SCROLL_PAUSE = 3.0

# Global tracking to prevent duplicates across all posts
GLOBAL_SEEN_COMMENTS = set()

# Global variables for emergency saving
CURRENT_POSTS_DATA = []
CURRENT_SHARES_DATA = []
CURRENT_COMMENTS_DATA = []
EMERGENCY_SAVE_ENABLED = False

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)


def emergency_save():
    """Save current data in case of unexpected termination"""
    global CURRENT_POSTS_DATA, CURRENT_SHARES_DATA, CURRENT_COMMENTS_DATA, EMERGENCY_SAVE_ENABLED
    
    if not EMERGENCY_SAVE_ENABLED or not CURRENT_POSTS_DATA:
        return
    
    try:
        print("\n" + "="*60)
        print("🚨 EMERGENCY SAVE TRIGGERED!")
        print("💾 Saving extracted data before exit...")
        print("="*60)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        emergency_file = os.path.join(OUTPUT_DIR, f'emergency_save_{timestamp}.csv')
        
        # Save data using the same format as normal save
        combined_data = []
        
        # Create dictionaries to group shares and comments by post_number
        shares_by_post = {}
        for share in CURRENT_SHARES_DATA:
            post_num = share['post_number']
            if post_num not in shares_by_post:
                shares_by_post[post_num] = []
            shares_by_post[post_num].append(share)
        
        comments_by_post = {}
        for comment in CURRENT_COMMENTS_DATA:
            post_num = comment['post_number']
            if post_num not in comments_by_post:
                comments_by_post[post_num] = []
            comments_by_post[post_num].append(comment)
        
        # Create combined data rows
        for post in CURRENT_POSTS_DATA:
            post_number = post.get('post_number', '')
            post_url = post.get('post_url', '')
            caption = post.get('caption', '').replace('\n', ' ').strip()
            images = ';'.join(post.get('images', []))
            
            post_shares = shares_by_post.get(post_number, [])
            post_comments = comments_by_post.get(post_number, [])
            
            if post_shares and post_comments:
                for share in post_shares:
                    for comment in post_comments:
                        combined_data.append({
                            'post_number': post_number,
                            'post_url': post_url,
                            'caption': caption,
                            'images': images,
                            'person_who_shared': share.get('person_who_shared', ''),
                            'url_of_person_who_shared': share.get('url_of_person_who_shared', ''),
                            'commenter_name': comment.get('commenter_name', ''),
                            'comment_text': comment.get('comment_text', '')
                        })
            elif post_shares:
                for share in post_shares:
                    combined_data.append({
                        'post_number': post_number,
                        'post_url': post_url,
                        'caption': caption,
                        'images': images,
                        'person_who_shared': share.get('person_who_shared', ''),
                        'url_of_person_who_shared': share.get('url_of_person_who_shared', ''),
                        'commenter_name': '',
                        'comment_text': ''
                    })
            elif post_comments:
                for comment in post_comments:
                    combined_data.append({
                        'post_number': post_number,
                        'post_url': post_url,
                        'caption': caption,
                        'images': images,
                        'person_who_shared': '',
                        'url_of_person_who_shared': '',
                        'commenter_name': comment.get('commenter_name', ''),
                        'comment_text': comment.get('comment_text', '')
                    })
            else:
                combined_data.append({
                    'post_number': post_number,
                    'post_url': post_url,
                    'caption': caption,
                    'images': images,
                    'person_who_shared': '',
                    'url_of_person_who_shared': '',
                    'commenter_name': '',
                    'comment_text': ''
                })
        
        # Save to CSV
        fieldnames = ['post_number', 'post_url', 'caption', 'images', 'person_who_shared', 'url_of_person_who_shared', 'commenter_name', 'comment_text']
        
        with open(emergency_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(combined_data)
        
        print(f"💾 Emergency save completed!")
        print(f"📁 File: {emergency_file}")
        print(f"📊 Posts: {len(CURRENT_POSTS_DATA)}")
        print(f"📊 Shares: {len(CURRENT_SHARES_DATA)}")
        print(f"📊 Comments: {len(CURRENT_COMMENTS_DATA)}")
        print(f"📊 Total rows: {len(combined_data)}")
        print("="*60)
        
    except Exception as e:
        print(f"❌ Emergency save failed: {e}")


def signal_handler(signum, frame):
    """Handle Ctrl+C and other termination signals"""
    print(f"\n🛑 Received signal {signum} - triggering emergency save...")
    emergency_save()
    sys.exit(0)


def random_sleep(min_s=1.5, max_s=3.5):
    """Random sleep to mimic human behavior"""
    time.sleep(random.uniform(min_s, max_s))


def normalize_post_url(url: str) -> str:
    """Normalize post URL for consistency"""
    if not url:
        return ''
    try:
        p = urlparse(url)
        path = p.path.rstrip('/')
        return urlunparse((p.scheme, p.netloc, path, '', '', ''))
    except Exception:
        return url.split('?')[0].rstrip('/')


def get_profile_url():
    """Get profile URL from user input or use default"""
    profile = input(f'Enter the Facebook profile URL (or press Enter for default {DEFAULT_PROFILE}): ').strip()
    if not profile:
        return DEFAULT_PROFILE
    
    # Add https:// if missing
    if not profile.startswith(('http://', 'https://')):
        profile = 'https://' + profile
    
    return profile


def manual_login_fallback():
    """Fallback manual login if fb_login fails"""
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.facebook.com/login")
    input("Please log into Facebook in the opened browser window, then press Enter here to continue...")
    return driver


def close_dialog(driver):
    """Close popup dialog if open"""
    try:
        close_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Close' and @role='button']"))
        )
        driver.execute_script("arguments[0].click();", close_btn)
        random_sleep(1, 2)
    except Exception:
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            random_sleep(1, 2)
        except Exception:
            pass


def open_comment_sort_menu(driver):
    """Open comment sorting menu and select 'All comments'"""
    try:
        sort_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@role='button']//span[contains(text(),'Most relevant')]"
            ))
        )
        print("    🔽 Clicking 'Most relevant' sorting button...")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sort_button)
        time.sleep(0.8)
        sort_button.click()
        time.sleep(1.2)
        return True
    except Exception as e:
        print(f"    ⚠️ Could not click 'Most relevant': {e}")
        return False


def select_all_comments_option(driver):
    """Select 'All comments' option from the menu"""
    try:
        all_comments_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@role='menuitem']//span[contains(text(),'All comments')]"
            ))
        )
        print("    ☑️ Selecting 'All comments' option...")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", all_comments_btn)
        time.sleep(0.8)
        all_comments_btn.click()
        time.sleep(1.2)
        return True
    except Exception as e:
        print(f"    ⚠️ Could not select 'All comments': {e}")
        return False


def scroll_comment_popup_and_extract(driver, post_number):
    """Scroll through comment popup and extract all comments with proper duplicate prevention"""
    print(f"    ↕️ Scrolling comment section for post #{post_number}...")
    all_comments = []
    seen_comment_hashes = set()  # Track unique comments for this post
    
    try:
        screen_width, screen_height = pyautogui.size()
        cx = screen_width // 2
        cy = screen_height // 2
        
        pyautogui.moveTo(cx, cy, duration=0.4)
        time.sleep(0.5)
        
        stagnant_scrolls = 0
        MAX_STAGNANT_SCROLLS = 5  # Reduced for faster processing
        MAX_TOTAL_SCROLLS = 30    # Reduced for faster processing
        total_scrolls = 0
        
        while total_scrolls < MAX_TOTAL_SCROLLS:
            print(f"    📜 Scroll #{total_scrolls + 1}/{MAX_TOTAL_SCROLLS}")
            
            # Extract comments from current view
            try:
                comment_blocks = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@aria-label,'Comment') and .//div[@dir='auto']]"
                )
                
                new_comments_found = 0
                
                for block in comment_blocks:
                    try:
                        # Extract commenter name
                        try:
                            name_el = block.find_element(By.XPATH, ".//a[@role='link']//span[@dir='auto']")
                            name = name_el.text.strip()
                        except:
                            name = ""
                        
                        # Extract comment text
                        try:
                            comment_el = block.find_element(By.XPATH, ".//div[@dir='auto' and @data-ad-preview='message']")
                            comment_text = comment_el.text.strip()
                        except:
                            try:
                                comment_el = block.find_element(By.XPATH, ".//div[@dir='auto']")
                                comment_text = comment_el.text.strip()
                            except:
                                comment_text = ""
                        
                        # Skip if no content
                        if not name and not comment_text:
                            continue
                            
                        # Create unique identifier (without post_number to avoid cross-post duplicates)
                        unique_content = f"{name}||{comment_text}"
                        comment_hash = hashlib.md5(unique_content.encode()).hexdigest()
                        
                        # Skip if already seen in this post or globally
                        if comment_hash in seen_comment_hashes or comment_hash in GLOBAL_SEEN_COMMENTS:
                            continue
                        
                        # Add to both local and global seen sets
                        seen_comment_hashes.add(comment_hash)
                        GLOBAL_SEEN_COMMENTS.add(comment_hash)
                        all_comments.append({
                            "post_number": post_number,
                            "commenter_name": name,
                            "comment_text": comment_text
                        })
                        
                        new_comments_found += 1
                        print(f"        👤 {name} → {comment_text[:40]}{'...' if len(comment_text) > 40 else ''}")
                        
                    except Exception as e:
                        continue
                
                print(f"    📊 Found {new_comments_found} new comments in this scroll")
                
                # Check if we should continue scrolling
                if new_comments_found == 0:
                    stagnant_scrolls += 1
                    print(f"    ⏸️ No new comments found ({stagnant_scrolls}/{MAX_STAGNANT_SCROLLS})")
                else:
                    stagnant_scrolls = 0
                
                if stagnant_scrolls >= MAX_STAGNANT_SCROLLS:
                    print("    🚫 No new comments for multiple scrolls — finished loading.")
                    break
                
            except Exception as e:
                print(f"    ⚠️ Error during comment extraction: {e}")
                stagnant_scrolls += 1
            
            # Scroll down to load more comments
            if total_scrolls < MAX_TOTAL_SCROLLS - 1:  # Don't scroll on last iteration
                scroll_amount = random.randint(-800, -600)
                pyautogui.scroll(scroll_amount)
                time.sleep(random.uniform(1.0, 1.5))  # Reduced wait time
            
            total_scrolls += 1
        
        print(f"    ✅ Extracted {len(all_comments)} unique comments total for post #{post_number}")
    
    except Exception as e:
        print(f"    ⚠️ Could not scroll comment popup: {e}")
    
    return all_comments


def close_comment_section(driver):
    """Close comment section popup with enhanced logic"""
    print("    🔄 Attempting to close comment section...")
    
    try:
        # Method 1: Try ESC key multiple times
        for i in range(5):
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                print(f"    🔑 ESC key attempt #{i+1}")
                time.sleep(0.5)
            except:
                pass
        
        # Method 2: Look for close buttons with various selectors
        close_selectors = [
            "//div[@aria-label='Close' and @role='button']",
            "//div[@aria-label='close' and @role='button']",
            "//div[contains(@aria-label,'Close')]",
            "//div[contains(@aria-label,'close')]",
            "//button[@aria-label='Close']",
            "//span[contains(@class,'close') or contains(@class,'Close')]"
        ]
        
        for selector in close_selectors:
            try:
                close_buttons = driver.find_elements(By.XPATH, selector)
                for btn in close_buttons[:3]:  # Try first 3 buttons
                    try:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].click();", btn)
                            print("    ✅ Closed using close button.")
                            time.sleep(1)
                            return True
                    except:
                        continue
            except:
                continue
        
        # Method 3: Click outside the popup area
        try:
            driver.execute_script("""
                // Click outside any popup
                const body = document.body;
                const event = new MouseEvent('click', {
                    view: window,
                    bubbles: true,
                    cancelable: true,
                    clientX: 100,
                    clientY: 100
                });
                body.dispatchEvent(event);
            """)
            time.sleep(0.5)
        except:
            pass
        
        # Method 4: JavaScript close all dialogs
        try:
            driver.execute_script("""
                // Close all dialogs/overlays
                document.querySelectorAll('[role="dialog"]').forEach(dialog => {
                    if (dialog.style) {
                        dialog.style.display = 'none';
                    }
                });
                
                // Remove overlay backgrounds
                document.querySelectorAll('[data-testid="Backdrop"]').forEach(backdrop => {
                    if (backdrop.style) {
                        backdrop.style.display = 'none';
                    }
                });
            """)
            print("    🔧 Used JavaScript to force close dialogs.")
        except:
            pass
    
    except Exception as e:
        print(f"    ⚠️ Error in close_comment_section: {e}")
    
    time.sleep(2)  # Give time for close action to complete
    print("    ✅ Comment section close attempts completed.")
    return True


def wait_for_share_popup(driver):
    """Wait for the share popup to appear"""
    try:
        WebDriverWait(driver, SHARE_POPUP_TIMEOUT).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
            )
        )
        return True
    except TimeoutException:
        return False


def scrape_shares_from_popup(driver, post_number):
    """Scrape sharer names from the popup dialog"""
    sharers = []
    seen = set()
    print(f"[*] Scraping sharers for post #{post_number}")

    try:
        popup = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
            )
        )
        print("✅ Share popup detected.")
    except TimeoutException:
        print("[-] Share popup not detected.")
        return sharers

    # Find scrollable container
    scrollable_container = None
    divs = popup.find_elements(By.XPATH, ".//div")
    for div in divs:
        try:
            scroll_height = driver.execute_script("return arguments[0].scrollHeight;", div)
            client_height = driver.execute_script("return arguments[0].clientHeight;", div)
            if scroll_height and scroll_height > client_height + 100:
                scrollable_container = div
                print("✅ Found scrollable container inside share popup.")
                break
        except Exception:
            continue

    if not scrollable_container:
        print("⚠️ No scrollable div found — using popup as fallback.")
        scrollable_container = popup

    # Scroll and collect sharers
    last_height = 0
    same_height_count = 0
    scroll_round = 0
    max_scroll_rounds = 20

    while scroll_round < max_scroll_rounds:
        scroll_round += 1
        print(f"🔽 Scroll attempt #{scroll_round}")

        # Scroll to trigger lazy loading
        driver.execute_script("arguments[0].scrollBy(0, -200);", scrollable_container)
        time.sleep(1)
        driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable_container)
        time.sleep(3)

        # Collect visible anchor tags
        links = scrollable_container.find_elements(By.XPATH, ".//a[contains(@href,'facebook.com')]")

        for link in links:
            try:
                name_el = link.find_element(By.XPATH, ".//span")
                name = name_el.text.strip()
                if not name or len(name) < 2 or len(name) > 100:
                    continue

                # Filter out junk
                if not any(c.isalpha() for c in name):
                    continue

                href = link.get_attribute("href")
                if href and "facebook.com" in href:
                    href = href.split("?")[0]
                    if name not in seen:
                        seen.add(name)
                        sharers.append({
                            "post_number": post_number,
                            "person_who_shared": name,
                            "url_of_person_who_shared": href
                        })
            except Exception:
                continue

        # Check scroll progress
        new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_container)
        if new_height == last_height:
            same_height_count += 1
            print(f"⏸️ No scroll height change ({same_height_count}/3)")
            if same_height_count >= 3:
                print("✅ Reached end of popup list.")
                break
        else:
            same_height_count = 0
        last_height = new_height

    close_dialog(driver)
    print(f"[+] Collected {len(sharers)} sharers for post {post_number}")
    return sharers


def extract_post_data(driver, post_element, post_number):
    """Extract post URL, caption, and images from a post element"""
    post_data = {
        'post_number': post_number,
        'post_url': '',
        'caption': '',
        'images': [],
        'shares': []
    }

    try:
        # Extract post URL
        post_url = ''
        try:
            anchors = post_element.find_elements(By.TAG_NAME, 'a')
            candidates = []
            for a in anchors:
                try:
                    href = (a.get_attribute('href') or '').strip()
                except Exception:
                    href = ''
                if not href:
                    continue
                
                # Look for permalink patterns
                if any(x in href for x in ['/posts/', 'permalink.php', '/photos/', '/videos/', 'story.php', 'ft_ent_identifier', 'story_fbid', '/photo.php', '/media/set']):
                    candidates.append(href)
                elif 'facebook.com' in href or 'm.facebook.com' in href:
                    candidates.append(href)

            # Prefer candidates with explicit post identifiers
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
            pass

        # If still no permalink, try to parse data-ft
        if not post_url:
            try:
                data_ft = post_element.get_attribute('data-ft') or ''
                if data_ft:
                    import re
                    m = re.search(r'top_level_post_id\"?\s*[:=]\s*\"?(\d+(?:_\d+)?)\"?', data_ft)
                    if m:
                        tid = m.group(1)
                        if '_' in tid:
                            owner, post = tid.split('_', 1)
                            post_url = normalize_post_url(f"https://www.facebook.com/{owner}/posts/{post}")
                        else:
                            post_url = normalize_post_url(f"https://www.facebook.com/{tid}")
            except Exception:
                pass

        post_data['post_url'] = post_url

        # Extract caption with improved filtering
        caption_text = ''
        try:
            msg = post_element.find_element(By.CSS_SELECTOR, "div[data-ad-preview='message']")
            caption_text = (msg.text or '').strip()
        except Exception:
            pass

        if not caption_text:
            try:
                # Look for actual post content with better selectors
                content_selectors = [
                    "div[data-ad-preview='message']",
                    "div[data-testid='post_message']", 
                    "div[role='article'] div[dir='auto']:not([aria-label])",
                    "span[dir='auto']"
                ]
                
                for selector in content_selectors:
                    try:
                        elements = post_element.find_elements(By.CSS_SELECTOR, selector)
                        for elem in elements:
                            try:
                                t = (elem.text or '').strip()
                                if not t or len(t) < 10:  # Skip very short text
                                    continue
                                
                                low = t.lower()
                                
                                # Enhanced skip words list including translation text
                                skip_words = [
                                    'like', 'comment', 'comments', 'share', 'see more', 'reply', 'edited', 'follow',
                                    'see original', 'rate this translation', 'see translation', 'translate', 
                                    'show original', 'original text', 'translation', 'translated from',
                                    'view more comments', 'write a comment', 'most relevant', 'newest first',
                                    'all comments', 'top comments', 'sort by', 'react', 'love', 'haha', 'wow',
                                    'sad', 'angry', 'care', 'minute ago', 'minutes ago', 'hour ago', 'hours ago',
                                    'day ago', 'days ago', 'week ago', 'weeks ago', 'month ago', 'months ago',
                                    'year ago', 'years ago', 'just now', 'sponsored', 'promote', 'boost',
                                    'create ad', 'view insights', 'edit post', 'delete post'
                                ]
                                
                                # Skip if contains any skip words
                                if any(sw in low for sw in skip_words):
                                    continue
                                
                                # Skip if it's just numbers or very short
                                if low.isdigit() or len(t) < 5:
                                    continue
                                
                                # Check if it looks like a comment (starts with name pattern)
                                if re.match(r'^[A-Z][a-z]+ [A-Z][a-z]+\s*$', t.strip()):
                                    continue
                                
                                # Check for translation indicators
                                translation_patterns = [
                                    r'·\s*see original\s*·',
                                    r'·\s*rate this translation\s*·',
                                    r'translated from \w+',
                                    r'see translation',
                                    r'show original'
                                ]
                                
                                if any(re.search(pattern, low) for pattern in translation_patterns):
                                    continue
                                
                                # If we get here, it looks like actual post content
                                caption_text = t
                                break
                            except Exception:
                                continue
                        
                        if caption_text:  # Found caption, stop looking
                            break
                            
                    except Exception:
                        continue
            except Exception:
                pass

        post_data['caption'] = caption_text

        # Extract images
        images = []
        try:
            imgs = post_element.find_elements(By.TAG_NAME, 'img')
            for im in imgs:
                try:
                    src = im.get_attribute('src') or im.get_attribute('data-src') or ''
                    if src and 'profile' not in src and src not in images:
                        images.append(src)
                except Exception:
                    continue
        except Exception:
            pass

        post_data['images'] = images
        post_data['comments'] = []  # Initialize comments list

        print(f"[+] Extracted post data for post #{post_number}")
        print(f"    - URL: {post_url[:50]}{'...' if len(post_url) > 50 else ''}")
        print(f"    - Caption: {caption_text[:50]}{'...' if len(caption_text) > 50 else ''}")
        print(f"    - Images: {len(images)} found")

    except Exception as e:
        print(f"[-] Error extracting post data: {e}")

    return post_data


def extract_shares_from_post(driver, post_element, post_number):
    """Extract share data from a post"""
    shares = []
    
    try:
        # Scroll to element
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", post_element)
        random_sleep(1, 2)

        # Find share button with count text
        share_buttons = post_element.find_elements(By.XPATH, ".//span[contains(text(),'share')]")
        target = None
        for btn in share_buttons:
            if btn.is_displayed() and "share" in btn.text.lower() and btn.text.lower() != "share":
                target = btn
                break

        if not target:
            print(f"[-] No share count visible for post #{post_number}")
            return shares

        print(f"[*] Found share button for post #{post_number}, clicking...")
        
        # Click to open popup
        driver.execute_script("arguments[0].click();", target)
        random_sleep(2, 3)

        # Wait for popup and scrape shares
        if wait_for_share_popup(driver):
            shares = scrape_shares_from_popup(driver, post_number)
        else:
            print(f"[-] Share popup did not open for post #{post_number}")

    except (StaleElementReferenceException, NoSuchElementException):
        print(f"[-] Post #{post_number} became stale or disappeared, skipping...")
    except Exception as e:
        print(f"[-] Unexpected error extracting shares from post #{post_number}: {e}")

    return shares


def extract_comments_from_post(driver, post_element, post_number):
    """Extract comment data from a post"""
    comments = []
    
    try:
        # Scroll to element
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", post_element)
        random_sleep(1, 2)
        
        # Find comment button within this specific post element
        comment_buttons = post_element.find_elements(
            By.XPATH,
            ".//div[@role='button' and (contains(translate(., 'COMMENT', 'comment'), 'comment') or contains(@aria-label, 'Comment'))]"
        )
        
        target = None
        for btn in comment_buttons:
            try:
                txt = (btn.text or btn.get_attribute("aria-label") or "").strip()
                if txt and re.search(r"\d", txt):
                    target = btn
                    break
            except:
                continue
        
        if not target:
            print(f"[-] No comment button found for post #{post_number}")
            return comments
        
        print(f"[*] Found comment button for post #{post_number}, clicking...")
        
        # Ensure no other comment sections are open first
        try:
            existing_dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
            if existing_dialogs:
                print(f"    🔧 Closing {len(existing_dialogs)} existing dialog(s) first...")
                for dialog in existing_dialogs:
                    try:
                        driver.execute_script("arguments[0].style.display = 'none';", dialog)
                    except:
                        pass
                time.sleep(1)
        except:
            pass
        
        # Click to open comment section
        print(f"    🖱️ Clicking comment button for post #{post_number}...")
        driver.execute_script("arguments[0].click();", target)
        random_sleep(2, 3)
        
        # Verify comment section opened
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']//div[contains(@aria-label,'Comment')]|//div[@role='dialog']//span[contains(text(),'comment')]|//div[@role='dialog']//span[contains(text(),'Comment')]"))
            )
            print(f"    ✅ Comment section opened successfully for post #{post_number}")
        except:
            print(f"    ⚠️ Comment section may not have opened properly for post #{post_number}")
        
        # Try to open comment sort menu and select "All comments"
        if open_comment_sort_menu(driver):
            select_all_comments_option(driver)
        
        time.sleep(1.5)
        
        # Scroll and extract comments
        comments = scroll_comment_popup_and_extract(driver, post_number)
        
        # Close comment section and verify it's closed
        close_comment_section(driver)
        
        # Additional verification - check if any dialog is still open
        try:
            dialogs = driver.find_elements(By.XPATH, "//div[@role='dialog']")
            if dialogs:
                print(f"    ⚠️ {len(dialogs)} dialog(s) still open, forcing close...")
                for dialog in dialogs:
                    try:
                        driver.execute_script("arguments[0].style.display = 'none';", dialog)
                    except:
                        pass
                time.sleep(1)
        except:
            pass
        
        print(f"    ✅ Comments extraction completed for post #{post_number}")
        
    except (StaleElementReferenceException, NoSuchElementException):
        print(f"[-] Post #{post_number} became stale or disappeared, skipping comments...")
    except Exception as e:
        print(f"[-] Unexpected error extracting comments from post #{post_number}: {e}")
    
    return comments


def scrape_integrated_data(driver, profile_url, max_posts=MAX_POSTS):
    """Main function to scrape both post data and shares in integration"""
    global CURRENT_POSTS_DATA, CURRENT_SHARES_DATA, CURRENT_COMMENTS_DATA, EMERGENCY_SAVE_ENABLED
    
    print(f"\n[*] Starting integrated scraping for {max_posts} posts from: {profile_url}")
    
    # Enable emergency save
    EMERGENCY_SAVE_ENABLED = True
    
    try:
        driver.get(profile_url)
    except (WebDriverException, InvalidSessionIdException):
        raise
    
    time.sleep(SCROLL_PAUSE_TIME)

    all_posts_data = []
    all_shares_data = []
    all_comments_data = []
    processed_posts = set()
    scrolls = 0
    max_scrolls = 30  # Increased to allow more scrolling for finding posts
    scrolls_without_new_posts = 0
    max_scrolls_without_progress = 6  # Increased from 3 to 6 - be more patient
    last_page_height = 0

    while len(all_posts_data) < max_posts and scrolls < max_scrolls:
        # Find all post elements on current screen with better filtering
        all_articles = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
        
        # Filter out non-post articles (comments, ads, etc.)
        posts = []
        for article in all_articles:
            try:
                # Check if this looks like an actual post
                article_text = article.text.lower()
                
                # Skip if it's likely a comment section or other non-post content
                skip_indicators = [
                    'write a comment',
                    'view more comments', 
                    'most relevant',
                    'all comments',
                    'top comments',
                    'newest first',
                    'see more comments'
                ]
                
                # Skip if it contains comment section indicators
                if any(indicator in article_text for indicator in skip_indicators):
                    continue
                
                # Check if it has typical post elements (like, comment, share buttons)
                has_like_btn = len(article.find_elements(By.XPATH, ".//div[@role='button' and contains(., 'Like')]")) > 0
                has_comment_btn = len(article.find_elements(By.XPATH, ".//div[@role='button' and contains(., 'Comment')]")) > 0  
                has_share_btn = len(article.find_elements(By.XPATH, ".//div[@role='button' and contains(., 'Share')]")) > 0
                
                # Must have at least 2 of the 3 main interaction buttons to be considered a post
                button_count = sum([has_like_btn, has_comment_btn, has_share_btn])
                if button_count < 2:
                    continue
                
                # Check if it has post-like content structure
                has_content = len(article.find_elements(By.CSS_SELECTOR, "div[data-ad-preview='message'], span[dir='auto']")) > 0
                
                if has_content:
                    posts.append(article)
                    
            except Exception:
                # If we can't analyze it, include it to be safe
                posts.append(article)
        
        print(f"[*] Found {len(posts)} valid posts on screen (filtered from {len(all_articles)} articles)")

        posts_processed_this_iteration = 0
        for post in posts:
            if len(all_posts_data) >= max_posts:
                break

            try:
                # Use post HTML hash as unique identifier
                post_html = post.get_attribute('outerHTML') or ''
                post_id = hashlib.sha1(post_html[:1000].encode('utf-8')).hexdigest()
                
                if post_id in processed_posts:
                    continue
                
                processed_posts.add(post_id)
                post_number = len(all_posts_data) + 1

                print(f"\n[*] Processing post #{post_number}")

                # Extract post data (URL, caption, images)
                post_data = extract_post_data(driver, post, post_number)
                all_posts_data.append(post_data)
                posts_processed_this_iteration += 1

                # Extract shares data
                shares_data = extract_shares_from_post(driver, post, post_number)
                if shares_data:
                    all_shares_data.extend(shares_data)
                    post_data['shares'] = shares_data
                
                # Extract comments data
                comments_data = extract_comments_from_post(driver, post, post_number)
                if comments_data:
                    all_comments_data.extend(comments_data)
                    post_data['comments'] = comments_data

                # Update global data for emergency save after each post
                CURRENT_POSTS_DATA = all_posts_data.copy()
                CURRENT_SHARES_DATA = all_shares_data.copy()
                CURRENT_COMMENTS_DATA = all_comments_data.copy()

                # Ensure we're back to the main feed before next post
                try:
                    # Scroll back to the post to ensure we're in the right context
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", post)
                    time.sleep(1)
                except:
                    pass

                # Pause between posts to ensure clean separation
                print(f"    ⏸️ Pausing before next post...")
                random_sleep(3, 5)

            except Exception as e:
                print(f"[-] Error processing post: {e}")
                continue

        # Check current page height to detect if we've reached the end
        current_page_height = driver.execute_script("return document.body.scrollHeight;")
        
        # Check if we processed any new posts this iteration
        if posts_processed_this_iteration == 0:
            scrolls_without_new_posts += 1
            print(f"[!] No new posts processed this iteration ({scrolls_without_new_posts}/{max_scrolls_without_progress})")
            
            # If page height hasn't changed and no new posts, we might be at the end
            if current_page_height == last_page_height and scrolls_without_new_posts >= 2:
                print(f"[!] Page height unchanged ({current_page_height}) - likely reached end of feed")
                scrolls_without_new_posts += 1  # Accelerate the stopping condition
        else:
            scrolls_without_new_posts = 0  # Reset counter when we find new posts
            print(f"[+] Processed {posts_processed_this_iteration} new posts this iteration")
        
        last_page_height = current_page_height

        # Stop if we haven't found new posts for several scrolls
        if scrolls_without_new_posts >= max_scrolls_without_progress:
            print(f"[!] No new posts found after {max_scrolls_without_progress} scrolls - stopping to prevent infinite loop")
            print(f"[📊] Final stats: {len(all_posts_data)} posts out of target {max_posts}")
            break

        # Scroll for more posts if needed
        if len(all_posts_data) < max_posts and scrolls < max_scrolls:
            scrolls += 1
            print(f"[↓] Scrolling for more posts (scroll #{scrolls})...")
            
            # Scroll more aggressively to load new content
            scroll_amount = 1200 + (scrolls * 200)  # Increase scroll amount progressively
            driver.execute_script(f'window.scrollBy(0, {scroll_amount});')
            time.sleep(SCROLL_PAUSE_TIME)
            
            # Give Facebook time to load new content
            if scrolls_without_new_posts > 0:
                print(f"[⏳] Waiting extra time for new content to load...")
                time.sleep(2)
            
            # Check if we can scroll further
            scroll_position = driver.execute_script("return window.pageYOffset + window.innerHeight;")
            page_height = driver.execute_script("return document.body.scrollHeight;")
            
            if scroll_position >= page_height - 100:  # Near bottom of page
                print(f"[📍] Near bottom of page (scroll: {scroll_position}, height: {page_height})")
                # Try a few more aggressive scrolls before giving up
                for i in range(3):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(1)
                    new_height = driver.execute_script("return document.body.scrollHeight;")
                    if new_height > page_height:
                        print(f"[📈] Page grew from {page_height} to {new_height}")
                        break
                    page_height = new_height
        elif len(all_posts_data) >= max_posts:
            print(f"[✅] Reached target of {max_posts} posts - stopping")
            break
        elif scrolls >= max_scrolls:
            print(f"[!] Reached maximum scroll limit ({max_scrolls}) - stopping")
            break

    return all_posts_data, all_shares_data, all_comments_data


def save_integrated_data(posts_data, shares_data, comments_data):
    """Save combined posts, shares, and comments data to a single integrated CSV file"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    combined_file = os.path.join(OUTPUT_DIR, f'combined_{timestamp}.csv')
    
    # Prepare combined data with the format: post_number,post_url,caption,images,person_who_shared,url_of_person_who_shared,commenter_name,comment_text
    combined_data = []
    
    # Create dictionaries to group shares and comments by post_number for easier lookup
    shares_by_post = {}
    for share in shares_data:
        post_num = share['post_number']
        if post_num not in shares_by_post:
            shares_by_post[post_num] = []
        shares_by_post[post_num].append(share)
    
    comments_by_post = {}
    for comment in comments_data:
        post_num = comment['post_number']
        if post_num not in comments_by_post:
            comments_by_post[post_num] = []
        comments_by_post[post_num].append(comment)
    
    # For each post, create rows combining post data with share and comment data
    for post in posts_data:
        post_number = post.get('post_number', '')
        post_url = post.get('post_url', '')
        caption = post.get('caption', '').replace('\n', ' ').strip()
        images = ';'.join(post.get('images', []))
        
        # Get shares and comments for this post
        post_shares = shares_by_post.get(post_number, [])
        post_comments = comments_by_post.get(post_number, [])
        
        # Create all combinations of shares and comments for this post
        if post_shares and post_comments:
            # If post has both shares and comments, create rows for each combination
            for share in post_shares:
                for comment in post_comments:
                    combined_data.append({
                        'post_number': post_number,
                        'post_url': post_url,
                        'caption': caption,
                        'images': images,
                        'person_who_shared': share.get('person_who_shared', ''),
                        'url_of_person_who_shared': share.get('url_of_person_who_shared', ''),
                        'commenter_name': comment.get('commenter_name', ''),
                        'comment_text': comment.get('comment_text', '')
                    })
        elif post_shares:
            # If post has only shares, create rows with empty comment fields
            for share in post_shares:
                combined_data.append({
                    'post_number': post_number,
                    'post_url': post_url,
                    'caption': caption,
                    'images': images,
                    'person_who_shared': share.get('person_who_shared', ''),
                    'url_of_person_who_shared': share.get('url_of_person_who_shared', ''),
                    'commenter_name': '',
                    'comment_text': ''
                })
        elif post_comments:
            # If post has only comments, create rows with empty share fields
            for comment in post_comments:
                combined_data.append({
                    'post_number': post_number,
                    'post_url': post_url,
                    'caption': caption,
                    'images': images,
                    'person_who_shared': '',
                    'url_of_person_who_shared': '',
                    'commenter_name': comment.get('commenter_name', ''),
                    'comment_text': comment.get('comment_text', '')
                })
        else:
            # If post has no shares or comments, create one row with empty fields
            combined_data.append({
                'post_number': post_number,
                'post_url': post_url,
                'caption': caption,
                'images': images,
                'person_who_shared': '',
                'url_of_person_who_shared': '',
                'commenter_name': '',
                'comment_text': ''
            })
    
    # Save combined data to CSV
    combined_fieldnames = ['post_number', 'post_url', 'caption', 'images', 'person_who_shared', 'url_of_person_who_shared', 'commenter_name', 'comment_text']
    
    with open(combined_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=combined_fieldnames)
        writer.writeheader()
        writer.writerows(combined_data)
    
    return combined_file, len(combined_data)


def main():
    """Main function to run the integrated Facebook scraper"""
    global GLOBAL_SEEN_COMMENTS
    driver = None
    
    # Set up signal handlers for emergency save
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination
    atexit.register(emergency_save)  # Called on normal exit too
    
    try:
        # Clear global tracking for new session
        GLOBAL_SEEN_COMMENTS.clear()
        
        print("="*60)
        print("FACEBOOK INTEGRATED SCRAPER")
        print("Posts + Shares + Comments Data Extraction")
        print("🚨 Emergency save enabled - data will be saved if interrupted!")
        print("="*60)
        
        # Get profile URL
        profile_url = get_profile_url()
        print(f"\nTarget Profile: {profile_url}")
        print(f"Posts to scrape: {MAX_POSTS}")
        
        # Confirm before starting
        confirm = input(f"\nProceed with integrated scraping? (y/n): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("Scraping cancelled.")
            sys.exit(0)
        
        # Initialize WebDriver with login
        if FB_LOGIN_AVAILABLE:
            try:
                driver = fb_login_main()
                print("\n✅ Facebook login successful")
            except Exception as e:
                print(f'\n⚠ fb_login failed: {e}')
                driver = None

        if driver is None:
            print("\n→ Using manual login fallback...")
            driver = manual_login_fallback()

        # Start integrated scraping
        print(f"\n→ Starting integrated scraping...")
        posts_data, shares_data, comments_data = scrape_integrated_data(driver, profile_url, MAX_POSTS)
        
        # Save results
        print(f"\n→ Saving results...")
        combined_file, total_rows = save_integrated_data(posts_data, shares_data, comments_data)
        
        # Print results
        print(f"\n✅ SCRAPING COMPLETED SUCCESSFULLY!")
        print(f"✅ Posts scraped: {len(posts_data)}")
        print(f"✅ Total shares collected: {len(shares_data)}")
        print(f"✅ Total comments collected: {len(comments_data)}")
        print(f"✅ Combined data rows: {total_rows}")
        print(f"✅ Integrated file saved: {combined_file}")
        
        # Disable emergency save after successful completion
        global EMERGENCY_SAVE_ENABLED
        EMERGENCY_SAVE_ENABLED = False

    except KeyboardInterrupt:
        print("\n\n⚠ Scraping interrupted by user")
        emergency_save()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during scraping: {e}")
        emergency_save()
        sys.exit(1)
    finally:
        try:
            if driver:
                print("→ Closing browser...")
                driver.quit()
                print("→ Browser closed")
        except Exception as e:
            print(f"→ Error closing browser: {e}")
            # If browser closing fails, still trigger emergency save
            if EMERGENCY_SAVE_ENABLED:
                emergency_save()


if __name__ == '__main__':
    main()