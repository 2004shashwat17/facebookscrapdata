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
from selenium.common.exceptions import TimeoutException
from fb_login import main as fb_login

# ---------------- CONFIG ----------------
PROFILE_URL = "https://www.facebook.com/BeingSalmanKhan"
OUTPUT_DIR = "facebook_data"
MAX_POSTS_TO_SCRAPE = 50
    SCROLL_PAUSE_TIME = 10
# ----------------------------------------

os.makedirs(OUTPUT_DIR, exist_ok=True)


def random_sleep(min_s=1.5, max_s=3.5):
    """Human-like sleep"""
    time.sleep(random.uniform(min_s, max_s))


def close_dialog(driver):
    """Close popup dialog if open"""
    try:
        close_btn = driver.find_element(
            By.XPATH, "//div[@aria-label='Close' and @role='button']"
        )
        driver.execute_script("arguments[0].click();", close_btn)
        random_sleep(1, 2)
    except Exception:
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except:
            pass


def find_and_click_see_shares(driver):
    """Find and click 'See who shared' or share-count link, then wait for popup"""
    print("[*] Looking for 'See who shared' or share-count link...")
    random_sleep(1, 2)

    see_shares_selectors = [
        "//span[contains(text(), 'See who shared')]",
        "//div[contains(text(), 'See who shared')]",
        "//a[contains(text(), 'See who shared')]",
        "//a[contains(@href, '/shares/view')]",
        "//span[contains(text(), 'shared this')]",
        "//span[contains(text(), 'shares')]",
        "//a[contains(., 'shares')]",
        "//a[contains(., 'People who shared this')]",
    ]

    clicked = False
    for selector in see_shares_selectors:
        try:
            elements = driver.find_elements(By.XPATH, selector)
        except Exception:
            continue
        for elem in elements:
            try:
                if not elem.is_displayed():
                    continue
                text = (elem.text or "").strip()
                if not text or text.lower() == "share":
                    continue

                if any(x in text.lower() for x in ["see who shared", "people who shared", "shares"]):
                    try:
                        elem.click()
                        clicked = True
                        print(f"[+] Clicked share element: '{text[:80]}'")
                    except Exception:
                        driver.execute_script("arguments[0].click();", elem)
                        clicked = True
                        print(f"[+] Clicked share element via JS: '{text[:80]}'")
                    random_sleep(2, 3)
                    break
            except Exception:
                continue
        if clicked:
            break

    if not clicked:
        print("[-] No clickable 'See who shared' / 'shares' element found.")
        return False

    # Wait for popup
    print("[*] Waiting for 'People who shared this' popup to appear...")
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
            )
        )
        print("[+] 'People who shared this' dialog detected.")
        return True
    except TimeoutException:
        print("[-] Timeout: popup not detected after click.")
        return False


def scrape_shares_dialog(driver, post_number):
    """Scrape sharer names + profile URLs from popup"""
    print(f"[*] Scraping sharers for post {post_number}...")
    sharers = []
    seen = set()
    no_new, last_count = 0, 0

    try:
        popup = WebDriverWait(driver, 12).until(
            EC.presence_of_element_located(
                (By.XPATH, "//div[@aria-label='People who shared this' and @role='dialog']")
            )
        )
    except TimeoutException:
        print("[-] Could not detect popup.")
        return sharers

    for attempt in range(40):
        soup = BeautifulSoup(driver.page_source, "html.parser")
        dialog = soup.find("div", {"aria-label": "People who shared this", "role": "dialog"})
        if not dialog:
            break

        for a in dialog.find_all("a", href=True):
            name_span = a.find("span")
            if not name_span:
                continue
            name = name_span.get_text(strip=True)
            if not name or len(name) < 2 or len(name) > 150:
                continue
            if any(x in name.lower() for x in ["share", "comment", "see more", "attachment"]):
                continue

            href = a["href"].split("?")[0]
            if href.startswith("/"):
                href = "https://www.facebook.com" + href

            if name not in seen:
                seen.add(name)
                sharers.append({
                    "post_number": post_number,
                    "person_who_shared": name,
                    "url_of_person_who_shared": href
                })

        print(f"[*] Scroll {attempt+1}: {len(sharers)} sharers found")

        if len(sharers) == last_count:
            no_new += 1
            if no_new >= 3:
                break
        else:
            last_count = len(sharers)
            no_new = 0

        try:
            driver.execute_script("""
                var dialog = document.querySelector('div[aria-label="People who shared this"][role="dialog"]');
                if (!dialog) return;
                var scrollable = dialog.querySelectorAll('*');
                for (var el of scrollable) {
                    if (el.scrollHeight && el.scrollHeight > el.clientHeight + 20) {
                        el.scrollBy(0, 800);
                        return;
                    }
                }
                dialog.scrollBy(0, 800);
            """)
        except:
            break

        time.sleep(2.5)

    close_dialog(driver)
    print(f"[+] Finished scraping {len(sharers)} sharers for post {post_number}")
    return sharers


def scroll_page_to_load_posts(driver, scrolls=10):
    """Scroll the profile page to load posts"""
    print("[*] Scrolling to load posts...")
    for i in range(scrolls):
        driver.execute_script("window.scrollBy(0, window.innerHeight * 0.9);")
        time.sleep(SCROLL_PAUSE_TIME)
        print(f"[*] Scroll {i+1}/{scrolls} done.")


def detect_posts(driver):
    """Rough post count detection (HTML structure changes frequently)"""
    soup = BeautifulSoup(driver.page_source, "html.parser")
    posts = soup.find_all("div", class_=lambda c: c and "x1yztbdb" in c)
    print(f"[+] Detected {len(posts)} posts")
    return posts


def process_single_post(driver, index):
    print(f"\n============================================================")
    print(f"[*] Processing post {index}")
    print("============================================================")
    try:
        buttons = driver.find_elements(By.XPATH, "//span[contains(text(),'shares')]")
        if not buttons:
            print("[-] No share element found.")
            return []

        target = None
        for btn in buttons:
            if btn.is_displayed() and "share" in btn.text.lower() and btn.text.strip() != "Share":
                target = btn
                break

        if not target:
            print("[-] No valid share-count button found.")
            return []

        ActionChains(driver).move_to_element(target).click().perform()
        random_sleep(2, 3)

        if not find_and_click_see_shares(driver):
            print("[-] No popup appeared for this post.")
            return []

        sharers = scrape_shares_dialog(driver, index)
        return sharers

    except Exception as e:
        print(f"[-] Error in post {index}: {e}")
        return []


def scrape_facebook_shares():
    print("\nFACEBOOK PROFILE POST SHARE SCRAPER")
    print("=" * 60)
    driver = fb_login()

    driver.get(PROFILE_URL)
    time.sleep(6)

    scroll_page_to_load_posts(driver)
    posts = detect_posts(driver)
    total = min(MAX_POSTS_TO_SCRAPE, len(posts))
    print(f"[*] Will process {total} posts...\n")

    all_rows = []
    for i in range(1, total + 1):
        result = process_single_post(driver, i)
        if result:
            all_rows.extend(result)

    # Save to single CSV file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(OUTPUT_DIR, f"facebook_shares_{timestamp}.csv")
    pd.DataFrame(all_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[+] Data saved to: {csv_path}")

    print(f"\nTotal posts processed: {total}")
    print(f"Total sharers collected: {len(all_rows)}")

    driver.quit()


if __name__ == "__main__":
    scrape_facebook_shares()
