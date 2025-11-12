"""
Integrated Facebook Scraper - Combines Post, Likes, and Shares Scraping
This script scrapes posts from a Facebook profile and for each post:
1. Extracts post data (URL, caption, images)
2. Scrapes likes/reactions
3. Scrapes shares
All data is saved to separate CSV files with timestamps.
"""

import os
import time
import json
import random
import pandas as pd
import hashlib
import csv
import re
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
    WebDriverException, InvalidSessionIdException
)
from fb_login import main as fb_login

# ---------------- CONFIG ----------------
PROFILE_URL = "https://www.facebook.com/profile.php?id=100064151734126"
OUTPUT_DIR = "facebook_data"
MAX_POSTS_TO_SCRAPE = 3
SCROLL_PAUSE_TIME = 8
# ----------------------------------------

os.makedirs(OUTPUT_DIR, exist_ok=True)


class IntegratedFacebookScraper:
    def __init__(self):
        self.driver = None
        self.all_posts_data = []
        self.all_likes_data = []
        self.all_shares_data = []
        self.processed_posts = set()
        
    def random_sleep(self, min_s=1.5, max_s=3.5):
        """Random sleep to avoid detection"""
        time.sleep(random.uniform(min_s, max_s))
        
    def close_dialog(self):
        """Close popup dialog if open"""
        try:
            close_btn = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@aria-label='Close' and @role='button']"))
            )
            self.driver.execute_script("arguments[0].click();", close_btn)
            self.random_sleep(1, 2)
        except Exception:
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            self.random_sleep(1, 2)
            
    def scroll_to_element(self, element):
        """Ensure the element is visible before clicking"""
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        self.random_sleep(1, 2)
        
    def normalize_post_url(self, url: str) -> str:
        """Normalize post URL for consistency"""
        if not url:
            return ''
        try:
            p = urlparse(url)
            path = p.path.rstrip('/')
            return urlunparse((p.scheme, p.netloc, path, '', '', ''))
        except Exception:
            return url.split('?')[0].rstrip('/')
            
    def extract_fbid(self, profile_link):
        """Extracts FBID or username from a Facebook profile URL."""
        try:
            if "profile.php?id=" in profile_link:
                match = re.search(r"profile\.php\?id=(\d+)", profile_link)
                if match:
                    return match.group(1)
            match = re.search(r"[?&]id=(\d+)", profile_link)
            if match:
                return match.group(1)
            username_match = re.search(r"facebook\.com/([^/?&]+)", profile_link)
            if username_match:
                return username_match.group(1)
            return None
        except Exception:
            return None
    
    def scrape_post_data(self, post, post_number):
        """Extract post data (URL, caption, images) from a post element"""
        print(f"[*] Extracting post data for post #{post_number}")
        
        try:
            # Extract post URL - try multiple methods
            post_url = ''
            try:
                # Method 1: Look for permalink in links
                anchors = post.find_elements(By.TAG_NAME, 'a')
                candidates = []
                for a in anchors:
                    try:
                        href = (a.get_attribute('href') or '').strip()
                        if href and 'facebook.com' in href:
                            if any(x in href for x in ['/posts/', 'permalink.php', '/photos/', '/videos/', 'story.php']):
                                candidates.append(href)
                    except Exception:
                        continue

                if candidates:
                    post_url = self.normalize_post_url(candidates[0])
                
                # Method 2: Try to construct from data attributes
                if not post_url:
                    try:
                        data_ft = post.get_attribute('data-ft') or ''
                        if 'top_level_post_id' in data_ft:
                            import re
                            match = re.search(r'top_level_post_id["\s:=]+(\d+)', data_ft)
                            if match:
                                post_id = match.group(1)
                                post_url = f"https://www.facebook.com/permalink.php?story_fbid={post_id}"
                    except Exception:
                        pass
                        
            except Exception as e:
                print(f"[-] Error extracting URL: {e}")
                post_url = ''

            # Extract caption - try multiple selectors
            caption_text = ''
            caption_selectors = [
                "div[data-ad-preview='message']",
                "div[data-testid='post_message']", 
                "span[dir='auto']",
                "div[dir='auto']"
            ]
            
            for selector in caption_selectors:
                try:
                    elements = post.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        text = (elem.text or '').strip()
                        if text and len(text) > 10:  # Must have substantial content
                            # Skip navigation/UI text
                            skip_words = ['like', 'comment', 'share', 'see more', 'reply', 'follow', 'join', 'hours', 'minutes']
                            if not any(skip in text.lower() for skip in skip_words):
                                if not text.isdigit():  # Skip pure numbers
                                    caption_text = text
                                    break
                    if caption_text:
                        break
                except Exception:
                    continue
            
            # If still no caption, try getting any substantial text
            if not caption_text:
                try:
                    all_text = post.text or ''
                    lines = [line.strip() for line in all_text.split('\n') if line.strip()]
                    for line in lines:
                        if len(line) > 20 and not any(skip in line.lower() for skip in ['like', 'comment', 'share']):
                            caption_text = line
                            break
                except Exception:
                    pass

            # Extract images - more comprehensive approach
            images = []
            try:
                imgs = post.find_elements(By.TAG_NAME, 'img')
                for im in imgs:
                    try:
                        src = im.get_attribute('src') or im.get_attribute('data-src') or ''
                        if src and src.startswith('http'):
                            # Filter out profile pictures and UI elements
                            if not any(skip in src.lower() for skip in ['profile', 'avatar', 'icon', 'emoji']):
                                if src not in images:
                                    images.append(src)
                    except Exception:
                        continue
            except Exception:
                pass

            post_data = {
                'post_number': post_number,
                'post_url': post_url or '',
                'caption': caption_text or f'Post #{post_number}',  # Fallback caption
                'images': ';'.join(images),
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            print(f"[+] Extracted post data:")
            print(f"    - URL: {'✓' if post_url else '✗'} ({post_url[:50]}...)" if post_url else "    - URL: ✗")
            print(f"    - Caption: {len(caption_text)} chars ({'✓' if caption_text else '✗'})")
            print(f"    - Images: {len(images)} found")
            return post_data
            
        except Exception as e:
            print(f"[-] Error extracting post data: {e}")
            return {
                'post_number': post_number,
                'post_url': '',
                'caption': f'Error extracting post #{post_number}',
                'images': '',
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    
    def extract_names_from_popup(self):
        """Extracts all visible user names from the open reaction popup - COPIED FROM WORKING FILE"""
        extracted_data = []
        seen_fbids = set()
        try:
            name_elements = self.driver.find_elements(
                By.XPATH,
                '//a[starts-with(@href, "https://www.facebook.com/") and @role="link" and normalize-space(text()) != ""]'
            )
            for a in name_elements:
                try:
                    name = a.text.strip()
                    link = a.get_attribute("href")
                    if not name or len(name) < 2:
                        continue
                    if any(x in link for x in ["/pages/", "/groups/", "/events/", "/stories/", "/photo/", "/video/"]):
                        continue
                    fbid = self.extract_fbid(link)
                    if fbid and fbid in seen_fbids:
                        continue
                    if fbid:
                        seen_fbids.add(fbid)
                    extracted_data.append({
                        "name": name,
                        "link": link,
                        "fbid": fbid if fbid else "N/A"
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ Error extracting names: {e}")
        return extracted_data

    def scroll_and_scrape_popup(self):
        """EXACT COPY from working all_working_like_reactions.py"""
        all_names = {}
        try:
            # Wait for popup
            popup = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
            )
            print("📋 Popup detected. Looking for scrollable container...")

            # Find the actual scrollable div (this is the stable selector)
            scroll_container = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//div[contains(@class, 'x2atdfe') and contains(@class, 'x1c1uobl')]"
                ))
            )
            print("✅ Found scrollable container for popup.")

            last_height = self.driver.execute_script("return arguments[0].scrollHeight;", scroll_container)
            same_height_count = 0
            scroll_attempts = 0

            while True:
                self.driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scroll_container)
                time.sleep(1.8)

                new_height = self.driver.execute_script("return arguments[0].scrollHeight;", scroll_container)

                # Extract names after each scroll
                new_data = self.extract_names_from_popup()
                before = len(all_names)
                for person in new_data:
                    key = person['fbid'] if person['fbid'] != "N/A" else person['name']
                    if key not in all_names:
                        all_names[key] = person
                after = len(all_names)
                print(f"   ➕ {after - before} new names (Total: {after})")

                if new_height == last_height:
                    same_height_count += 1
                else:
                    same_height_count = 0
                last_height = new_height
                scroll_attempts += 1

                # Stop when no more new content or after 20 scrolls
                if same_height_count >= 3 or scroll_attempts > 20:
                    print("✅ Reached end of popup content.")
                    break

            print(f"🎉 Finished scrolling. Total names: {len(all_names)}")

        except Exception as e:
            print(f"❌ Error scrolling popup: {e}")
            import traceback; traceback.print_exc()

        return list(all_names.values())

    def scrape_likes_for_post(self, post, post_number):
        """Scrape likes/reactions using PROVEN working logic from all_working_like_reactions.py"""
        print(f"[*] Scraping likes for post #{post_number}")
        likes_data = []
        
        try:
            self.scroll_to_element(post)
            self.random_sleep(1, 2)
            
            # Use EXACT selector from working file
            reaction_buttons = post.find_elements(
                By.XPATH,
                './/div[@role="button" and .//div[contains(text(), "All reactions:")]]'
            )
            
            if not reaction_buttons:
                print("[-] No reaction button found for this post")
                return likes_data
            
            button = reaction_buttons[0]
            print(f"✅ Found reaction button")
            
            # Click the reaction button (EXACT logic from working file)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(2)
            self.driver.execute_script("arguments[0].click();", button)
            print("✅ Opened reactions popup")
            time.sleep(3)

            # Ensure popup and click "All" if needed (EXACT logic from working file)
            popup = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
            )
            try:
                all_tab = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, '//div[@role="tablist"]//span[text()="All"]'))
                )
                self.driver.execute_script("arguments[0].click();", all_tab)
                print("✅ Clicked 'All' tab")
                time.sleep(2)
            except Exception:
                print("⚠️ 'All' tab not found or already active.")

            # Use EXACT scrolling logic from working file
            all_reactors = self.scroll_and_scrape_popup()
            for person in all_reactors:
                likes_data.append({
                    "post_number": post_number,
                    "name": person['name'],
                    "profile_url": person['link'],
                    "fbid": person['fbid']
                })

            print(f"✅ Saved {len(all_reactors)} names for Post #{post_number}")

            # Close popup (EXACT logic from working file)
            try:
                close_btn = self.driver.find_element(
                    By.XPATH, '//div[@aria-label="Close" or (@role="button" and contains(@aria-label, "Close"))]'
                )
                self.driver.execute_script("arguments[0].click();", close_btn)
                print("🔒 Closed popup")
            except Exception:
                self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                print("🔒 Closed popup with ESC")

            time.sleep(3)
            
        except Exception as e:
            print(f"[-] Error scraping likes: {e}")
            import traceback; traceback.print_exc()
            
        return likes_data
    
    def wait_for_share_popup(self):
        """Wait for the popup to appear after clicking 'shares' - EXACT COPY from working file"""
        try:
            WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
                )
            )
            return True
        except TimeoutException:
            return False

    def scrape_shares_dialog(self, post_number):
        """EXACT COPY from working scrap_share_vibhor.py"""
        sharers = []
        seen = set()
        print(f"[*] Scraping sharers for post #{post_number}")

        try:
            popup = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
                )
            )
            print("✅ Share popup detected.")
        except TimeoutException:
            print("[-] Popup not detected.")
            return sharers

        # --- Find scrollable div ---
        scrollable_container = None
        divs = popup.find_elements(By.XPATH, ".//div")
        for div in divs:
            try:
                scroll_height = self.driver.execute_script("return arguments[0].scrollHeight;", div)
                client_height = self.driver.execute_script("return arguments[0].clientHeight;", div)
                if scroll_height and scroll_height > client_height + 100:
                    scrollable_container = div
                    print("✅ Found scrollable container inside share popup.")
                    break
            except Exception:
                continue

        if not scrollable_container:
            print("⚠ No scrollable div found — using popup as fallback.")
            scrollable_container = popup

        last_height = 0
        same_height_count = 0
        scroll_round = 0
        max_scroll_rounds = 50  # increased slightly for deeper loading

        while scroll_round < max_scroll_rounds:
            scroll_round += 1
            print(f"🔽 Scroll attempt #{scroll_round}")

            # ✅ Small reverse scroll (up then down) to trigger lazy loading
            self.driver.execute_script("arguments[0].scrollBy(0, -200);", scrollable_container)
            time.sleep(1)
            self.driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable_container)
            time.sleep(5.5)

            # ✅ Collect all visible anchor tags (Selenium-based)
            links = scrollable_container.find_elements(By.XPATH, ".//a[contains(@href,'facebook.com')]")

            for link in links:
                try:
                    name_el = link.find_element(By.XPATH, ".//span")
                    name = name_el.text.strip()
                    if not name:
                        continue

                    # ✂ Filter out junk
                    if not any(c.isalpha() for c in name):
                        continue
                    if len(name) > 100 or len(name) < 2:
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
            new_height = self.driver.execute_script("return arguments[0].scrollHeight;", scrollable_container)
            if new_height == last_height:
                same_height_count += 1
                print(f"⏸ No scroll height change ({same_height_count}/3)")
                # 🟡 Trigger light reverse scroll to force load
                self.driver.execute_script("arguments[0].scrollBy(0, -400);", scrollable_container)
                time.sleep(2.5)
            else:
                same_height_count = 0
            last_height = new_height

            if same_height_count >= 3:
                print("✅ Reached end of popup list (no more content).")
                break

        self.close_dialog()
        print(f"[+] Collected {len(sharers)} clean sharers for post {post_number}")
        return sharers

    def scrape_shares_for_post(self, post, post_number):
        """Scrape shares using EXACT logic from working scrap_share_vibhor.py"""
        print(f"[*] Scraping shares for post #{post_number}")
        shares_data = []
        
        try:
            self.scroll_to_element(post)
            self.random_sleep(1.5, 2.5)

            # Find share element with count text (EXACT from working file)
            share_buttons = post.find_elements(By.XPATH, ".//span[contains(text(),'share')]")
            target = None
            for btn in share_buttons:
                if btn.is_displayed() and "share" in btn.text.lower() and btn.text.lower() != "share":
                    target = btn
                    break

            if not target:
                print("[-] No share count visible for this post.")
                return []

            # Click to open popup once (EXACT from working file)
            self.driver.execute_script("arguments[0].click();", target)
            self.random_sleep(2, 3)

            # Wait for popup (EXACT from working file)
            if not self.wait_for_share_popup():
                print("[-] Popup did not open properly.")
                return []

            # Scrape names (EXACT from working file)
            sharers = self.scrape_shares_dialog(post_number)
            return sharers
            
        except Exception as e:
            print(f"[-] Error scraping shares: {e}")
            
        return shares_data
    
    def process_single_post(self, post, post_number):
        """Process a single post: extract data, scrape likes, scrape shares"""
        print(f"\n{'='*60}")
        print(f"PROCESSING POST #{post_number}")
        print(f"{'='*60}")
        
        try:
            # 1. Extract post data (URL, caption, images)
            post_data = self.scrape_post_data(post, post_number)
            if post_data:
                self.all_posts_data.append(post_data)
            
            self.random_sleep(2, 3)
            
            # 2. Scrape likes/reactions for this post
            likes_data = self.scrape_likes_for_post(post, post_number)
            if likes_data:
                self.all_likes_data.extend(likes_data)
            
            self.random_sleep(2, 3)
            
            # 3. Scrape shares for this post
            shares_data = self.scrape_shares_for_post(post, post_number)
            if shares_data:
                self.all_shares_data.extend(shares_data)
            
            print(f"[✅] Completed processing post #{post_number}")
            print(f"    - Post data: {'✓' if post_data else '✗'}")
            print(f"    - Likes: {len(likes_data)} collected")
            print(f"    - Shares: {len(shares_data)} collected")
            
        except Exception as e:
            print(f"[-] Error processing post #{post_number}: {e}")
    
    def save_all_data(self):
        """Save all collected data to CSV files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create combined data structure
        combined_data = []
        
        # Group likes and shares by post number
        likes_by_post = {}
        shares_by_post = {}
        
        # Group likes by post
        for like in self.all_likes_data:
            post_num = like['post_number']
            if post_num not in likes_by_post:
                likes_by_post[post_num] = []
            likes_by_post[post_num].append(like['name'])
        
        # Group shares by post
        for share in self.all_shares_data:
            post_num = share['post_number']
            if post_num not in shares_by_post:
                shares_by_post[post_num] = []
            shares_by_post[post_num].append(share['person_who_shared'])
        
        # Create combined rows
        for post in self.all_posts_data:
            post_num = post['post_number']
            
            # Get likes for this post
            post_likes = likes_by_post.get(post_num, [])
            likes_count = len(post_likes)
            likers = "; ".join(post_likes) if post_likes else ""
            
            # Get shares for this post
            post_shares = shares_by_post.get(post_num, [])
            shares_count = len(post_shares)
            sharers = "; ".join(post_shares) if post_shares else ""
            
            combined_row = {
                'Post_URL': post.get('post_url', ''),
                'Caption': post.get('caption', ''),
                'Images': post.get('images', ''),
                'Likes_Count': likes_count,
                'Likers': likers,
                'Shares_Count': shares_count,
                'Sharers': sharers
            }
            combined_data.append(combined_row)
        
        # Save combined CSV
        if combined_data:
            combined_csv = os.path.join(OUTPUT_DIR, f"combined_{timestamp}.csv")
            pd.DataFrame(combined_data).to_csv(combined_csv, index=False, encoding="utf-8-sig")
            print(f"[+] Saved COMBINED data to {combined_csv}")
        
        # Also save individual files for backup
        if self.all_posts_data:
            posts_csv = os.path.join(OUTPUT_DIR, f"facebook_posts_integrated_{timestamp}.csv")
            pd.DataFrame(self.all_posts_data).to_csv(posts_csv, index=False, encoding="utf-8-sig")
            print(f"[+] Saved posts backup to {posts_csv}")
        
        if self.all_likes_data:
            likes_csv = os.path.join(OUTPUT_DIR, f"facebook_likes_integrated_{timestamp}.csv")
            pd.DataFrame(self.all_likes_data).to_csv(likes_csv, index=False, encoding="utf-8-sig")
            print(f"[+] Saved likes backup to {likes_csv}")
        
        if self.all_shares_data:
            shares_csv = os.path.join(OUTPUT_DIR, f"facebook_shares_integrated_{timestamp}.csv")
            pd.DataFrame(self.all_shares_data).to_csv(shares_csv, index=False, encoding="utf-8-sig")
            print(f"[+] Saved shares backup to {shares_csv}")
        
        # Create session summary
        summary = {
            "scraping_session": timestamp,
            "profile_url": PROFILE_URL,
            "posts_processed": len(self.all_posts_data),
            "total_likes_collected": len(self.all_likes_data),
            "total_shares_collected": len(self.all_shares_data),
            "completion_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        summary_csv = os.path.join(OUTPUT_DIR, f"scraping_summary_{timestamp}.csv")
        pd.DataFrame([summary]).to_csv(summary_csv, index=False, encoding="utf-8-sig")
        print(f"[+] Saved session summary to {summary_csv}")
        
        return combined_csv if combined_data else None
    
    def run_integrated_scraper(self):
        """Main method to run the integrated scraper"""
        print("\n" + "="*80)
        print("🚀 INTEGRATED FACEBOOK SCRAPER STARTED")
        print("="*80)
        print(f"Profile: {PROFILE_URL}")
        print(f"Max posts to scrape: {MAX_POSTS_TO_SCRAPE}")
        print("="*80)
        
        try:
            # Login to Facebook
            print("[*] Logging into Facebook...")
            self.driver = fb_login()
            print("✅ Successfully logged in")
            
            # Navigate to profile
            print(f"[*] Navigating to profile: {PROFILE_URL}")
            self.driver.get(PROFILE_URL)
            time.sleep(8)
            print("✅ Profile loaded")
            
            post_counter = 0
            scroll_round = 0
            max_scroll_rounds = 25
            
            while post_counter < MAX_POSTS_TO_SCRAPE and scroll_round < max_scroll_rounds:
                # Find posts on current view - use more specific selectors
                posts = self.driver.find_elements(By.XPATH, "//div[@role='article']")
                if not posts:
                    # Fallback selectors
                    posts = self.driver.find_elements(By.XPATH, "//div[contains(@class,'x1yztbdb')]")
                if not posts:
                    posts = self.driver.find_elements(By.CSS_SELECTOR, "[data-pagelet*='FeedUnit']")
                
                print(f"[*] Found {len(posts)} potential posts on screen (scroll round {scroll_round + 1})")
                
                new_posts_found = False
                
                for i, post in enumerate(posts):
                    if post_counter >= MAX_POSTS_TO_SCRAPE:
                        break
                    
                    try:
                        # Check if post is visible and has content
                        if not post.is_displayed():
                            continue
                            
                        # Get post HTML for unique identification
                        post_html = post.get_attribute("innerHTML")
                        if not post_html or len(post_html) < 100:  # Skip very small elements
                            continue
                        
                        # Create more robust post ID
                        post_id = hash(post_html[:800])  # Use more content for ID
                        
                        if post_id in self.processed_posts:
                            continue
                        
                        # More lenient validation - check for any interactive elements
                        post_text = post.text.lower() if post.text else ""
                        has_content = any(keyword in post_html.lower() or keyword in post_text for keyword in [
                            'like', 'comment', 'share', 'react', 'aria-label', 'role="button"', 'data-testid'
                        ])
                        
                        # Additional check - look for typical post structure
                        has_structure = bool(
                            post.find_elements(By.TAG_NAME, 'span') or 
                            post.find_elements(By.TAG_NAME, 'a') or
                            post.find_elements(By.TAG_NAME, 'img')
                        )
                        
                        if not (has_content or has_structure):
                            print(f"[-] Post {i+1} skipped - no valid content detected")
                            continue
                        
                        # Mark as processed and increment counter
                        self.processed_posts.add(post_id)
                        post_counter += 1
                        new_posts_found = True
                        
                        print(f"[✅] Processing valid post #{post_counter}")
                        
                        # Process this post completely
                        self.process_single_post(post, post_counter)
                        
                        # Random delay between posts
                        self.random_sleep(3, 5)
                        
                    except Exception as e:
                        print(f"[-] Error processing post {i+1}: {e}")
                        continue
                
                # If we processed max posts, break
                if post_counter >= MAX_POSTS_TO_SCRAPE:
                    print(f"[✅] Reached maximum posts limit ({MAX_POSTS_TO_SCRAPE})")
                    break
                
                # Scroll down for more posts
                if not new_posts_found:
                    scroll_round += 1
                    print(f"[↓] Scrolling for more posts (round {scroll_round})...")
                    self.driver.execute_script("window.scrollBy(0, window.innerHeight * 1.5);")
                    time.sleep(SCROLL_PAUSE_TIME)
                else:
                    # Reset scroll counter if we found new posts
                    scroll_round = 0
            
            print(f"\n[🎉] SCRAPING COMPLETED!")
            print(f"Posts processed: {post_counter}")
            print(f"Total likes collected: {len(self.all_likes_data)}")
            print(f"Total shares collected: {len(self.all_shares_data)}")
            
            # Save all data
            combined_file = self.save_all_data()
            
            # Display final summary
            print(f"\n{'='*60}")
            print(f"📊 FINAL SUMMARY")
            print(f"{'='*60}")
            if combined_file:
                print(f"✅ MAIN COMBINED FILE: {combined_file}")
            print(f"📝 Posts: {len(self.all_posts_data)}")
            print(f"👍 Total Likes: {len(self.all_likes_data)}")
            print(f"📤 Total Shares: {len(self.all_shares_data)}")
            print(f"{'='*60}")
            
            # Show sample of combined data
            if self.all_posts_data:
                print(f"\n📋 SAMPLE DATA FROM COMBINED FILE:")
                print(f"Post 1 - Caption: {self.all_posts_data[0].get('caption', '')[:100]}...")
                post_1_likes = len([l for l in self.all_likes_data if l['post_number'] == 1])
                post_1_shares = len([s for s in self.all_shares_data if s['post_number'] == 1])
                print(f"Post 1 - Likes: {post_1_likes}, Shares: {post_1_shares}")
                print(f"{'='*60}")
            
            
        except Exception as e:
            print(f"[-] Fatal error in main scraper: {e}")
        
        finally:
            if self.driver:
                print("[*] Closing browser...")
                self.driver.quit()
                print("✅ Browser closed")


def main():
    scraper = IntegratedFacebookScraper()
    scraper.run_integrated_scraper()


if __name__ == "__main__":
    main()