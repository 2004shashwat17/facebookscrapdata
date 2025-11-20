import time
import re
import hashlib
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    NoSuchElementException,
)
from fb_login import main as fb_login
import pyautogui
import random
import csv
import os

# ===== CONFIG =====
PROFILE_URL = "https://www.facebook.com/shashwat.saxena.14473"
WAIT_AFTER_CLICK = 5
SCROLL_PAUSE = 6
MAX_SCROLL_ATTEMPTS = 10
COMMENT_SCROLLS = 6
COMMENT_SCROLL_PAUSE = 3.0

CSV_FILE = "shashwat_comments_output.csv"

# Create CSV if it doesn't exist
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["post_number", "name", "comment"])


# ================== HELPERS ================== #

def save_comment(post_number, name, comment):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([post_number, name, comment])


def open_comment_sort_menu(driver):
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


def extract_comments(driver, post_number, seen_ids):
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
                print(f"        👤 {name} → {comment}")
                save_comment(post_number, name, comment)
                new_count += 1

    except Exception as e:
        print(f"    ⚠️ Error extracting comments: {e}")

    return new_count


def scroll_comment_popup(driver, post_number):
    print("    ↕️ Scrolling inside comment section...")

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
        MAX_TOTAL_SCROLLS = 300
        total_scrolls = 0

        while True:
            scroll_amount = random.randint(-950, -700)
            pyautogui.scroll(scroll_amount)
            total_scrolls += 1

            print(f"    📜 Scroll #{total_scrolls} (amount: {scroll_amount})")
            time.sleep(random.uniform(1.2, 2.0))

            new_comments = extract_comments(driver, post_number, seen_ids)

            if new_comments == 0:
                stagnant_scrolls += 1
            else:
                stagnant_scrolls = 0

            if stagnant_scrolls >= MAX_STAGNANT_SCROLLS:
                print("    🚫 No new comments for multiple scrolls — finished loading all comments.")
                break

            if total_scrolls >= MAX_TOTAL_SCROLLS:
                print("    ⚠️ Reached max safe scroll limit — stopping to prevent infinite loop.")
                break

        print("    ✅ Fully loaded all available comments.")

    except Exception as e:
        print(f"    ⚠️ Could not scroll comment popup: {e}")


def close_comment_section(driver):
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
                print("    ✅ Closed using 'X' button.")
                return
            except:
                pass

        driver.execute_script("""
            document.querySelectorAll('[aria-label="Close"], [aria-label="close"]').forEach(b => b.click());
        """)

    except Exception:
        pass

    time.sleep(1)


def click_all_comment_buttons(driver):
    print(f"[*] Opening Facebook profile: {PROFILE_URL}")
    driver.get(PROFILE_URL)
    time.sleep(6)

    clicked = set()
    total = 0
    no_new_scrolls = 0

    # NEW: track absolute scroll position
    last_scroll_y = 0

    while True:
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, "//div[@role='button']"))
            )
        except:
            break

        comment_buttons = driver.find_elements(
            By.XPATH,
            "//div[@role='button' and (contains(translate(., 'COMMENT', 'comment'), 'comment') or contains(@aria-label, 'Comment'))]"
        )

        new_found = 0

        for btn in comment_buttons:
            try:
                txt = (btn.text or btn.get_attribute("aria-label") or "").strip()
                if not txt or not re.search(r"\d", txt):
                    continue

                try:
                    post_element = btn.find_element(By.XPATH,
                        "./ancestor::div[contains(@data-ad-preview,'message') or @role='article']"
                    )
                    identifier = hashlib.md5(post_element.text[:300].encode()).hexdigest()
                except:
                    identifier = str(btn.location['y'])

                if identifier in clicked:
                    continue

                clicked.add(identifier)
                new_found += 1

                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(1.5)

                btn.click()
                time.sleep(2.5)

                if open_comment_sort_menu(driver):
                    select_all_comments_option(driver)

                time.sleep(1.5)

                scroll_comment_popup(driver, total + 1)

                print(f"    ⏳ Waiting {WAIT_AFTER_CLICK}s before closing...")
                time.sleep(WAIT_AFTER_CLICK)

                close_comment_section(driver)

                total += 1
                print(f"    ✅ Done with post #{total}.\n")

            except:
                continue

        if new_found == 0:
            no_new_scrolls += 1
            if no_new_scrolls >= MAX_SCROLL_ATTEMPTS:
                print("[!] No more comment buttons — stopping.")
                break
        else:
            no_new_scrolls = 0

        # NEW: absolute scrolling → prevents page jumping back up
        last_scroll_y += 950
        driver.execute_script(f"window.scrollTo(0, {last_scroll_y});")

        print("[*] Scrolling page down...")
        time.sleep(SCROLL_PAUSE)

        if total >= 1000:
            break

    print(f"\n[✅] Completed — processed {total} posts.\n")


if __name__ == "__main__":
    driver = fb_login()
    click_all_comment_buttons(driver)
    print("[*] Script finished. Browser stays open.")
