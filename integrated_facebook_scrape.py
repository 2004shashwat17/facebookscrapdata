import os
import time
import csv
import json
import random
import hashlib
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
import pandas as pd
import re

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
    ElementClickInterceptedException,
)

from bs4 import BeautifulSoup
import pyautogui

# Import your login helper
import fb_login

# ============== CONFIG ===============
PROFILE_URL = "https://www.facebook.com/BJP4UK"
OUTPUT_DIR = "facebook_data"
SCROLL_PAUSE_MIN = 1.5
SCROLL_PAUSE_MAX = 3.0
WAIT_TIMEOUT = 15
COMMENT_SCROLLS = 6
COMMENT_SCROLL_PAUSE = 3.0
MAX_EMPTY_SCROLLS = 5

# Create output directory
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Global variables for tracking
collected_data = {
    'posts': [],
    'shares': [],
    'comments': []
}
processed_posts = set()
current_post_number = 0
driver = None

def debug_print(message):
    """Print debug message with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def save_data_to_files():
    """Save all data to single integration.csv file in exact format requested"""
    integration_file = os.path.join(OUTPUT_DIR, "integration.csv")
    
    try:
        all_rows = []
        
        for post in collected_data['posts']:
            post_number = post['post_number']
            post_id = post.get('post_id', '')
            caption = post['caption']
            image_urls = post['image_urls']
            
            # Get comments and shares for this post
            post_comments = [c for c in collected_data['comments'] if c['post_number'] == post_number]
            post_shares = [s for s in collected_data['shares'] if s['post_number'] == post_number]
            
            if not post_comments and not post_shares:
                # Post with no comments or shares
                all_rows.append([post_number, post_id, caption, image_urls, '', '', '', ''])
            else:
                # Create combinations of comments and shares
                max_items = max(len(post_comments), len(post_shares), 1)
                
                for i in range(max_items):
                    comment_person = post_comments[i]['name'] if i < len(post_comments) else ''
                    comment_text = post_comments[i]['comment'] if i < len(post_comments) else ''
                    share_person = post_shares[i]['person_who_shared'] if i < len(post_shares) else ''
                    share_url = post_shares[i]['url_of_person_who_shared'] if i < len(post_shares) else ''
                    
                    all_rows.append([
                        post_number, post_id, caption, image_urls,
                        comment_person, comment_text, share_person, share_url
                    ])
        
        # Write to file with exact headers requested
        with open(integration_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'post_number', 'post_id', 'caption', 'image_urls',
                'person_who_commet', 'what commetn', 'person whoh ashwred', 'shred_person_url'
            ])
            writer.writerows(all_rows)
        
        debug_print(f"✅ Updated integration.csv with {len(all_rows)} rows")
        debug_print(f"📊 Posts: {len(collected_data['posts'])}, Shares: {len(collected_data['shares'])}, Comments: {len(collected_data['comments'])}")
        
    except Exception as e:
        debug_print(f"❌ Error saving integration data: {e}")

def save_emergency_data():
    """Save current data as emergency backup"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    emergency_file = os.path.join(OUTPUT_DIR, f"emergency_save_{timestamp}.json")
    
    try:
        emergency_data = {
            'timestamp': timestamp,
            'current_post_number': current_post_number,
            'processed_posts': list(processed_posts),
            'collected_data': collected_data
        }
        
        with open(emergency_file, 'w', encoding='utf-8') as f:
            json.dump(emergency_data, f, indent=2, ensure_ascii=False)
        
        debug_print(f"🆘 Emergency save completed: {emergency_file}")
        return emergency_file
    except Exception as e:
        debug_print(f"❌ Emergency save failed: {e}")
        return None

def signal_handler(signum, frame):
    """Handle interruption signals"""
    debug_print(f"\n🛑 Received signal {signum}. Saving data and exiting...")
    save_emergency_data()
    save_data_to_files()
    
    if driver:
        try:
            driver.quit()
        except:
            pass
    
    debug_print("👋 Graceful shutdown completed")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Terminal kill

def random_sleep(min_s=1.5, max_s=3.0):
    """Random sleep with debug output"""
    sleep_time = random.uniform(min_s, max_s)
    time.sleep(sleep_time)

def make_post_hash(*parts: str) -> str:
    """Create unique hash for post identification"""
    m = hashlib.sha256()
    for p in parts:
        if p is None:
            p = ""
        m.update(p.encode("utf-8", errors="ignore"))
    return m.hexdigest()

def extract_caption_from_html(html: str) -> str:
    """Parse caption HTML and return cleaned text"""
    soup = BeautifulSoup(html or "", "html.parser")
    pieces = []

    for el in soup.descendants:
        # Text nodes
        if isinstance(el, str):
            txt = el.strip()
            if txt:
                pieces.append(txt)
        # Hashtag links
        elif getattr(el, "name", None) == "a":
            txt = el.get_text().strip()
            if txt.startswith("#") and txt:
                pieces.append(txt)
        # Image emoji or accessible alt
        elif getattr(el, "name", None) == "img":
            alt = el.get("alt")
            if alt:
                pieces.append(alt.strip())

    return " ".join(pieces).strip()

def extract_image_urls_from_article(article_elem) -> List[str]:
    """Extract image URLs from post article element"""
    try:
        img_elems = article_elem.find_elements(By.CSS_SELECTOR, 'img[src*="scontent"]')
    except Exception:
        return []

    urls = []
    for im in img_elems:
        try:
            src = im.get_attribute("src")
        except StaleElementReferenceException:
            continue
        if src and "scontent" in src:
            if src not in urls:
                urls.append(src)
    return urls



def find_article_from_caption_elem(driver, caption_elem):
    """Find the enclosing article/post element from caption element"""
    try:
        article = caption_elem.find_element(By.XPATH, "./ancestor::*[@role='article' or @role='presentation' or contains(@data-testid,'story')]")
        return article
    except Exception:
        try:
            el = caption_elem
            for _ in range(6):
                el = el.find_element(By.XPATH, "./parent::*")
            return el
        except Exception:
            return None

def gather_visible_posts(driver) -> List[Tuple[str, object, object]]:
    """Gather all visible posts on the page"""
    posts = []
    caption_selectors = [
        '[data-ad-rendering-role="story_message"]',
        '[data-ad-preview="message"]',
    ]
    caption_elems = []
    for sel in caption_selectors:
        try:
            caption_elems.extend(driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception:
            continue

    seen_articles = set()
    for cap in caption_elems:
        try:
            article = find_article_from_caption_elem(driver, cap)
            if article is None:
                continue
            
            # Use article attribute id or compute hash
            article_id = None
            try:
                article_id = article.get_attribute("id")
            except Exception:
                article_id = None

            if not article_id:
                try:
                    data_ft = article.get_attribute("data-ft")
                except Exception:
                    data_ft = None
                if data_ft:
                    article_id = make_post_hash(data_ft)
            
            if not article_id:
                try:
                    inner_html = cap.get_attribute("innerHTML") or ""
                except Exception:
                    inner_html = ""
                imgs = extract_image_urls_from_article(article)
                first_img = imgs[0] if imgs else ""
                article_id = make_post_hash(inner_html, first_img)
            
            if article_id in seen_articles:
                continue
            seen_articles.add(article_id)
            posts.append((article_id, cap, article))
            
        except (StaleElementReferenceException, WebDriverException):
            continue

    return posts

# ============== SHARE SCRAPING FUNCTIONS ==============

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
        except Exception:
            pass
        random_sleep(1, 2)

def wait_for_share_popup(driver):
    """Wait for the share popup to appear"""
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
            )
        )
        return True
    except TimeoutException:
        return False

def scrape_shares_dialog(driver, post_number):
    """Scrape sharer names from popup"""
    sharers = []
    seen = set()
    debug_print(f"📤 Scraping shares for post #{post_number}")

    try:
        popup = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
            )
        )
        debug_print("✅ Share popup detected")
    except TimeoutException:
        debug_print("❌ Share popup not detected")
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
                debug_print("✅ Found scrollable container")
                break
        except Exception:
            continue

    if not scrollable_container:
        debug_print("⚠️ No scrollable container found, using popup")
        scrollable_container = popup

    last_height = 0
    same_height_count = 0
    scroll_round = 0
    max_scroll_rounds = 50

    while scroll_round < max_scroll_rounds:
        scroll_round += 1
        debug_print(f"🔽 Share scroll #{scroll_round}")

        # Scroll to load more content
        driver.execute_script("arguments[0].scrollBy(0, -200);", scrollable_container)
        time.sleep(1)
        driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable_container)
        time.sleep(2)

        # Collect visible sharers
        links = scrollable_container.find_elements(By.XPATH, ".//a[contains(@href,'facebook.com')]")

        for link in links:
            try:
                name_el = link.find_element(By.XPATH, ".//span")
                name = name_el.text.strip()
                if not name or not any(c.isalpha() for c in name):
                    continue
                if len(name) > 100 or len(name) < 2:
                    continue

                href = link.get_attribute("href")
                if href and "facebook.com" in href:
                    href = href.split("?")[0]
                    if name not in seen:
                        seen.add(name)
                        share_data = {
                            "post_number": post_number,
                            "person_who_shared": name,
                            "url_of_person_who_shared": href
                        }
                        sharers.append(share_data)
                        debug_print(f"💾 Saved share from {name}")
            except Exception:
                continue

        # Check scroll progress
        new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_container)
        if new_height == last_height:
            same_height_count += 1
            debug_print(f"⏸️ No height change ({same_height_count}/3)")
            if same_height_count >= 3:
                debug_print("✅ Reached end of share list")
                break
        else:
            same_height_count = 0
        last_height = new_height

    close_dialog(driver)
    debug_print(f"✅ Collected {len(sharers)} shares for post #{post_number}")
    return sharers

def scrape_post_shares(driver, post_element, post_number):
    """Scrape shares for a specific post"""
    try:
        # Find share button with count
        share_buttons = post_element.find_elements(By.XPATH, ".//span[contains(text(),'share')]")
        target = None
        for btn in share_buttons:
            if btn.is_displayed() and "share" in btn.text.lower() and btn.text.lower() != "share":
                target = btn
                break

        if not target:
            debug_print(f"❌ No share count found for post #{post_number}")
            return []

        # Click to open popup
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
        random_sleep(1, 2)
        driver.execute_script("arguments[0].click();", target)
        random_sleep(2, 3)

        # Wait for popup and scrape
        if wait_for_share_popup(driver):
            return scrape_shares_dialog(driver, post_number)
        else:
            debug_print(f"❌ Share popup didn't open for post #{post_number}")
            return []

    except Exception as e:
        debug_print(f"❌ Error scraping shares for post #{post_number}: {e}")
        return []

# ============== COMMENT SCRAPING FUNCTIONS ==============

def save_comment(post_number, name, comment):
    """Save comment to collected data"""
    comment_data = {
        'post_number': post_number,
        'name': name.strip() if name else '',
        'comment': comment.strip() if comment else ''
    }
    collected_data['comments'].append(comment_data)
    debug_print(f"💾 Saved comment from {name}: {comment[:30]}...")

def open_comment_sort_menu(driver):
    """Open comment sorting menu"""
    try:
        sort_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@role='button']//span[contains(text(),'Most relevant')]"
            ))
        )
        debug_print("🔽 Clicking 'Most relevant' sorting button")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sort_button)
        time.sleep(0.8)
        sort_button.click()
        time.sleep(1.2)
        return True
    except Exception as e:
        debug_print(f"⚠️ Could not click 'Most relevant': {e}")
        return False

def select_all_comments_option(driver):
    """Select 'All comments' option"""
    try:
        all_comments_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@role='menuitem']//span[contains(text(),'All comments')]"
            ))
        )
        debug_print("☑️ Selecting 'All comments' option")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", all_comments_btn)
        time.sleep(0.8)
        all_comments_btn.click()
        time.sleep(1.2)
        return True
    except Exception as e:
        debug_print(f"⚠️ Could not select 'All comments': {e}")
        return False

def extract_comments(driver, post_number, seen_ids):
    """Extract comments from current view"""
    new_count = 0

    try:
        comment_blocks = driver.find_elements(
            By.XPATH,
            "//div[contains(@aria-label,'Comment') and .//div[@dir='auto']]"
        )

        for block in comment_blocks:
            try:
                name_el = block.find_element(
                    By.XPATH,
                    ".//a[@role='link']//span[@dir='auto']"
                )
                name = name_el.text.strip()
            except:
                name = ""

            try:
                comment_el = block.find_element(
                    By.XPATH,
                    ".//div[@dir='auto' and @data-ad-preview='message']"
                )
                comment = comment_el.text.strip()
            except:
                try:
                    comment_el = block.find_element(
                        By.XPATH, ".//div[@dir='auto']"
                    )
                    comment = comment_el.text.strip()
                except:
                    comment = ""

            unique_hash = hashlib.md5((name + comment).encode()).hexdigest()

            if unique_hash in seen_ids:
                continue

            seen_ids.add(unique_hash)

            if name or comment:
                debug_print(f"💬 {name}: {comment[:50]}...")
                save_comment(post_number, name, comment)
                new_count += 1

    except Exception as e:
        debug_print(f"⚠️ Error extracting comments: {e}")

    return new_count

def scroll_comment_popup(driver, post_number):
    """Scroll inside comment popup to load all comments"""
    debug_print(f"↕️ Scrolling comments for post #{post_number}")

    try:
        screen_width, screen_height = pyautogui.size()
        cx = screen_width // 2
        cy = screen_height // 2

        pyautogui.moveTo(cx, cy, duration=0.4)
        time.sleep(0.5)

        seen_ids = set()
        extract_comments(driver, post_number, seen_ids)

        stagnant_scrolls = 0
        MAX_STAGNANT_SCROLLS = 8
        MAX_TOTAL_SCROLLS = 100
        total_scrolls = 0

        while total_scrolls < MAX_TOTAL_SCROLLS:
            scroll_amount = random.randint(-950, -700)
            pyautogui.scroll(scroll_amount)
            total_scrolls += 1

            debug_print(f"📜 Comment scroll #{total_scrolls}")
            time.sleep(random.uniform(1.2, 2.0))

            new_comments = extract_comments(driver, post_number, seen_ids)

            if new_comments == 0:
                stagnant_scrolls += 1
            else:
                stagnant_scrolls = 0

            if stagnant_scrolls >= MAX_STAGNANT_SCROLLS:
                debug_print("🚫 No new comments found, stopping")
                break

        debug_print("✅ Finished loading comments")

    except Exception as e:
        debug_print(f"⚠️ Error scrolling comments: {e}")

def close_comment_section(driver):
    """Close comment popup"""
    try:
        for _ in range(4):
            try:
                driver.switch_to.active_element.send_keys(Keys.ESCAPE)
            except:
                pass
            time.sleep(0.2)

        close_buttons = driver.find_elements(
            By.XPATH, "//div[@aria-label='Close' or @aria-label='close']"
        )
        for btn in close_buttons[:2]:
            try:
                btn.click()
                debug_print("✅ Closed comment popup")
                return
            except:
                pass

        driver.execute_script("""
            document.querySelectorAll('[aria-label="Close"], [aria-label="close"]').forEach(b => b.click());
        """)

    except Exception:
        pass

    time.sleep(1)

def scrape_post_comments(driver, post_element, post_number):
    """Scrape comments for a specific post"""
    try:
        # Find comment button
        comment_buttons = post_element.find_elements(
            By.XPATH,
            ".//div[@role='button' and (contains(translate(., 'COMMENT', 'comment'), 'comment') or contains(@aria-label, 'Comment'))]"
        )

        target = None
        for btn in comment_buttons:
            txt = (btn.text or btn.get_attribute("aria-label") or "").strip()
            if txt and re.search(r"\d", txt):
                target = btn
                break

        if not target:
            debug_print(f"❌ No comment button found for post #{post_number}")
            return

        # Click comment button
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
        time.sleep(1.5)
        target.click()
        time.sleep(2.5)

        # Set comment sorting
        if open_comment_sort_menu(driver):
            select_all_comments_option(driver)

        time.sleep(1.5)

        # Scroll and extract comments
        scroll_comment_popup(driver, post_number)

        debug_print(f"⏳ Waiting before closing comment popup")
        time.sleep(2)

        # Close comment popup
        close_comment_section(driver)

        debug_print(f"✅ Finished scraping comments for post #{post_number}")

    except Exception as e:
        debug_print(f"❌ Error scraping comments for post #{post_number}: {e}")

def process_single_post(driver, post_id, caption_elem, article_elem, post_number):
    """Process a single post: extract data, scrape shares and comments"""
    global current_post_number
    current_post_number = post_number
    
    debug_print(f"\n🔄 Processing post #{post_number}: {post_id[:12]}...")

    try:
        # Extract post data
        try:
            caption_html = caption_elem.get_attribute("innerHTML") or ""
        except StaleElementReferenceException:
            debug_print(f"❌ Caption became stale for post #{post_number}")
            return False
        
        caption_text = extract_caption_from_html(caption_html)
        
        try:
            image_urls = extract_image_urls_from_article(article_elem)
        except Exception:
            image_urls = []
        
        # Save post data
        post_data = {
            'post_number': post_number,
            'post_id': post_id,
            'caption': caption_text,
            'image_urls': "|".join(image_urls)
        }
        collected_data['posts'].append(post_data)
        
        debug_print(f"📝 Post data: {len(caption_text)} chars, {len(image_urls)} images, ID: {post_id[:12]}...")

        # Scrape shares for this post
        shares = scrape_post_shares(driver, article_elem, post_number)
        if shares:
            collected_data['shares'].extend(shares)
            debug_print(f"📤 Found {len(shares)} shares")

        # Scrape comments for this post
        scrape_post_comments(driver, article_elem, post_number)
        
        # Count comments for this post
        post_comments = [c for c in collected_data['comments'] if c['post_number'] == post_number]
        debug_print(f"💬 Found {len(post_comments)} comments")

        # Save data after each post completion
        save_data_to_files()
        debug_print(f"💾 Data saved after post #{post_number}")
        
        return True

    except Exception as e:
        debug_print(f"❌ Error processing post #{post_number}: {e}")
        return False

def scroll_once(driver):
    """Scroll page down once"""
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

def main():
    """Main function to run integrated scraper"""
    global driver, current_post_number
    
    debug_print("🚀 Starting Integrated Facebook Scraper")
    debug_print(f"🎯 Target Profile: {PROFILE_URL}")
    
    try:
        # Login to Facebook
        debug_print("🔐 Logging into Facebook...")
        driver = fb_login.main()
        debug_print("✅ Login successful")
        
        # Navigate to profile
        debug_print(f"🌐 Navigating to profile...")
        driver.get(PROFILE_URL)
        
        # Wait for profile to load
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='main'], div[role='feed']")))
            debug_print("✅ Profile loaded successfully")
        except TimeoutException:
            debug_print("⚠️ Profile load timeout - continuing anyway")

        seen_posts = set()
        empty_scrolls = 0
        post_counter = 0

        debug_print("🔍 Starting infinite scroll and data extraction...")

        while True:
            try:
                # Gather visible posts
                posts = gather_visible_posts(driver)
                debug_print(f"👀 Found {len(posts)} visible posts")
                
                new_found_this_round = 0
                
                for post_id, caption_elem, article_elem in posts:
                    if post_id in seen_posts:
                        continue
                    
                    post_counter += 1
                    seen_posts.add(post_id)
                    processed_posts.add(post_id)
                    
                    # Process this post completely
                    success = process_single_post(driver, post_id, caption_elem, article_elem, post_counter)
                    
                    if success:
                        new_found_this_round += 1
                        debug_print(f"✅ Completed post #{post_counter}")
                    else:
                        debug_print(f"❌ Failed to process post #{post_counter}")
                    
                    # Small delay between posts
                    random_sleep(2, 4)
                
                if new_found_this_round > 0:
                    empty_scrolls = 0
                    debug_print(f"📊 Found {new_found_this_round} new posts this round")
                else:
                    empty_scrolls += 1
                    debug_print(f"⏳ Empty scroll #{empty_scrolls}/{MAX_EMPTY_SCROLLS}")
                
                # Check if we should stop
                if empty_scrolls >= MAX_EMPTY_SCROLLS:
                    debug_print(f"🏁 No new posts found in {MAX_EMPTY_SCROLLS} scrolls - ending scraping")
                    break
                
                # Safety limit
                if post_counter >= 1000:
                    debug_print("⚠️ Reached safety limit of 1000 posts - stopping")
                    break
                
                # Scroll for more posts
                debug_print("⬇️ Scrolling for more posts...")
                scroll_once(driver)
                sleep_time = random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX)
                time.sleep(sleep_time)
                
            except Exception as e:
                debug_print(f"❌ Error in main loop: {e}")
                empty_scrolls += 1
                if empty_scrolls >= MAX_EMPTY_SCROLLS:
                    break
                continue

        # Final save
        debug_print("💾 Performing final data save...")
        save_data_to_files()
        
        # Print summary
        debug_print("\n📊 SCRAPING COMPLETED!")
        debug_print(f"📝 Total Posts: {len(collected_data['posts'])}")
        debug_print(f"📤 Total Shares: {len(collected_data['shares'])}")
        debug_print(f"💬 Total Comments: {len(collected_data['comments'])}")
        debug_print(f"🎯 Profile: {PROFILE_URL}")

    except KeyboardInterrupt:
        debug_print("\n⚠️ Interrupted by user")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        debug_print(f"❌ Fatal error: {e}")
        save_emergency_data()
        save_data_to_files()
    finally:
        if driver:
            try:
                debug_print("🔒 Closing browser...")
                driver.quit()
            except:
                pass
        debug_print("👋 Script finished")

if __name__ == "__main__":
    main()