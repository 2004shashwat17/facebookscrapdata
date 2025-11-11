import os
import time
import json
import random
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException
)
from fb_login import main as fb_login

# ---------------- CONFIG ----------------
PROFILE_URL = "https://www.facebook.com/profile.php?id=100064151734126"
OUTPUT_DIR = "facebook_data"
MAX_POSTS_TO_SCRAPE = 3
SCROLL_PAUSE_TIME = 10
# ----------------------------------------

os.makedirs(OUTPUT_DIR, exist_ok=True)


def random_sleep(min_s=1.5, max_s=3.5):
    time.sleep(random.uniform(min_s, max_s))


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
    """Wait for the popup to appear after clicking 'shares'."""
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
    """Scrape sharer names from popup reliably by scrolling inside the correct container."""
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
        print("[-] Popup not detected.")
        return sharers

    # --- Find scrollable div ---
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
        driver.execute_script("arguments[0].scrollBy(0, -200);", scrollable_container)
        time.sleep(1)
        driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable_container)
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
        new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_container)
        if new_height == last_height:
            same_height_count += 1
            print(f"⏸ No scroll height change ({same_height_count}/3)")
            # 🟡 Trigger light reverse scroll to force load
            driver.execute_script("arguments[0].scrollBy(0, -400);", scrollable_container)
            time.sleep(2.5)
        else:
            same_height_count = 0
        last_height = new_height

        if same_height_count >= 3:
            print("✅ Reached end of popup list (no more content).")
            break

    close_dialog(driver)
    print(f"[+] Collected {len(sharers)} clean sharers for post {post_number}")
    return sharers




def scroll_to_element(driver, element):
    """Ensure the element is visible before clicking"""
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    random_sleep(1, 2)


def process_post(driver, post, index):
    print(f"\n[*] Processing post #{index}")
    try:
        scroll_to_element(driver, post)
        random_sleep(1.5, 2.5)

        # Find share element with count text
        share_buttons = post.find_elements(By.XPATH, ".//span[contains(text(),'share')]")
        target = None
        for btn in share_buttons:
            if btn.is_displayed() and "share" in btn.text.lower() and btn.text.lower() != "share":
                target = btn
                break

        if not target:
            print("[-] No share count visible for this post.")
            return []

        # Click to open popup once
        driver.execute_script("arguments[0].click();", target)
        random_sleep(2, 3)

        # Wait for popup
        if not wait_for_share_popup(driver):
            print("[-] Popup did not open properly.")
            return []

        # Scrape names
        sharers = scrape_shares_dialog(driver, index)
        return sharers

    except (StaleElementReferenceException, NoSuchElementException):
        print("[-] Post became stale or disappeared, skipping...")
        return []
    except Exception as e:
        print(f"[-] Unexpected error on post {index}: {e}")
        return []


def scrape_facebook_shares():
    print("\nFACEBOOK SHARE SCRAPER STARTED")
    driver = fb_login()
    driver.get(PROFILE_URL)
    time.sleep(6)

    all_shares = []
    processed_posts = set()
    scroll_round = 0
    post_counter = 0

    while post_counter < MAX_POSTS_TO_SCRAPE:
        posts = driver.find_elements(By.XPATH, "//div[contains(@class,'x1yztbdb') and .//span[contains(text(),'share')]]")
        print(f"[*] Found {len(posts)} posts on screen")

        for post in posts:
            # Use part of HTML as unique signature
            post_id = hash(post.get_attribute("innerHTML")[:400])
            if post_id in processed_posts:
                continue

            processed_posts.add(post_id)
            post_counter += 1

            result = process_post(driver, post, post_counter)
            if result:
                all_shares.extend(result)

            if post_counter >= MAX_POSTS_TO_SCRAPE:
                break

            random_sleep(2, 3)

        if post_counter >= MAX_POSTS_TO_SCRAPE:
            break

        scroll_round += 1
        print(f"[↓] Scrolling for more posts (round {scroll_round})...")
        driver.execute_script("window.scrollBy(0, window.innerHeight * 1.5);")
        time.sleep(SCROLL_PAUSE_TIME)
        if scroll_round > 20:
            print("[-] Reached scroll limit. Stopping.")
            break

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(OUTPUT_DIR, f"facebook_shares_{timestamp}.csv")
    pd.DataFrame(all_shares).to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\n[+] Saved all sharers to {csv_path}")
    print(f"[+] Total sharers collected: {len(all_shares)}")

    driver.quit()


if __name__ == "__main__":
    scrape_facebook_shares()