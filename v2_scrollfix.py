# fb_reactions_scraper_fixed.py

import time
import csv
import sys
import os
import traceback
import hashlib
import random
import pyautogui
import regex
from bs4 import BeautifulSoup

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from fb_login import main as login


# ============================================================
# CLEAN NAME
# ============================================================
def clean_name(name):
    if not name:
        return False
    pattern = r"^[\p{L}\s.'-]+$"
    try:
        return bool(regex.match(pattern, name))
    except:
        return False


# ============================================================
# BS4 PARSER
# ============================================================
def extract_names_bs4(popup_html):
    soup = BeautifulSoup(popup_html, "html.parser")
    reactors = []

    for a in soup.find_all("a", href=True):
        name = a.get_text(strip=True)
        link = a["href"]

        if not name or len(name) < 2:
            continue

        if not any(x in link for x in ["/profile.php?id=", "facebook.com/"]):
            continue

        if any(x in link for x in ["/pages/", "/groups/", "/events/", "/stories/",
                                   "/photo/", "/video/"]):
            continue

        if not clean_name(name):
            continue

        reactors.append({"name": name, "link": link})

    return reactors


# ============================================================
# POPUP SCROLL
# ============================================================
def scroll_popup_and_extract(driver, popup):
    print("🔄 Scrolling popup to load all reactions...")

    screen_width, screen_height = pyautogui.size()
    center_x = screen_width // 2
    center_y = screen_height // 2

    pyautogui.moveTo(center_x, center_y, duration=0.4)
    time.sleep(0.3)

    seen = set()
    prev_count = 0
    no_change = 0
    loops = 0

    while True:
        loops += 1
        pyautogui.scroll(random.randint(-340, -200))
        time.sleep(random.uniform(1.8, 2.8))

        try:
            popup = driver.find_element(By.XPATH, '//div[@role="dialog"]')
        except:
            print("⚠️ Popup vanished.")
            break

        html = popup.get_attribute("outerHTML")
        names = extract_names_bs4(html)

        for p in names:
            seen.add(f"{p['name']}|{p['link']}")

        if len(seen) == prev_count:
            no_change += 1
            if no_change >= 4:
                break
        else:
            no_change = 0
            prev_count = len(seen)

        if loops >= 200:
            break

    # Final parsing
    try:
        popup = driver.find_element(By.XPATH, '//div[@role="dialog"]')
        html = popup.get_attribute("outerHTML")
        final = extract_names_bs4(html)
    except:
        final = []

    unique = []
    stored = set()
    for p in final:
        key = f"{p['name']}|{p['link']}"
        if key not in stored:
            stored.add(key)
            unique.append(p)

    print(f"✔ Extracted: {len(unique)}")
    return unique


# ============================================================
# SAVE PROGRESS
# ============================================================
def save_progress(filename, data):
    if not data:
        return

    folder = os.path.dirname(os.path.abspath(filename))
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Post_Number", "Reactor_Name", "Profile_Link"])
        writer.writeheader()
        for row in data:
            writer.writerow(row)

    print(f"💾 Saved → {filename} ({len(data)} rows)")


# ============================================================
# FIND REACTION BUTTONS
# ============================================================
def find_reaction_buttons(driver):
    XPATHS = [
        '//div[@role="button" and .//*[contains(text(),"All reactions")]]',
        '//div[@role="button" and descendant::*[contains(., "Reactions")]]',
        '//div[@role="button" and descendant::*[contains(., "React")]]',
        '//div[@role="button" and descendant::*[contains(., "K") or contains(., "M") or contains(., "0") or contains(., "1")]]',
        '//div[@role="button" and (@aria-haspopup="dialog")]',
        '//div[@role="button" and descendant::img[contains(@src,"reaction")]]'
    ]

    for xp in XPATHS:
        try:
            elements = driver.find_elements(By.XPATH, xp)
            if elements:
                return elements
        except:
            continue

    return []


# ============================================================
# MAIN SCRAPER (FIXED)
# ============================================================
def scrape_reactions(driver, profile_url, output="fb_reactions.csv"):

    driver.get(profile_url)
    time.sleep(6)

    clicked_posts = set()
    all_reactions = []

    MAX_SCROLL_ATTEMPTS = 10
    SCROLL_PAUSE = 5
    scroll_attempts_no_new = 0
    total_processed = 0

    print("\n🔵 Starting scrolling...\n")

    while True:

        # Freeze height and scan once
        previous_height = driver.execute_script("return document.body.scrollHeight")

        reaction_buttons = find_reaction_buttons(driver)
        static_buttons = reaction_buttons.copy()
        print(f"🔍 Found {len(static_buttons)} buttons in view")

        new_found = 0

        # Process each button in static list
        for idx, btn in enumerate(static_buttons):

            try:
                text = (btn.text or btn.get_attribute("aria-label") or "").strip()
                if not any(c.isdigit() for c in text):
                    continue

                # -------------------------
                # IDENTIFIER SYSTEM (A + B)
                # -------------------------
                try:
                    post_el = btn.find_element(By.XPATH, "./ancestor::div[@role='article']")

                    try:
                        post_link = post_el.find_element(
                            By.XPATH, ".//a[contains(@href,'/posts/')]"
                        ).get_attribute("href")
                        identifier = post_link
                    except:
                        snippet = post_el.text[:300]
                        identifier = hashlib.md5(snippet.encode()).hexdigest()

                except:
                    identifier = str(btn.location.get("y", ""))

                if not identifier:
                    identifier = f"index_{idx}"

                if identifier in clicked_posts:
                    continue

                clicked_posts.add(identifier)
                new_found += 1

                # Save scroll position BEFORE clicking popup
                current_scroll = driver.execute_script("return window.pageYOffset;")

                # Scroll button into view
                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'instant', block:'center'});",
                    btn,
                )
                time.sleep(1)

                # Click popup
                try:
                    driver.execute_script("arguments[0].click();", btn)
                except:
                    try:
                        btn.click()
                    except:
                        continue

                # Wait for popup
                try:
                    popup = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located(
                            (By.XPATH, '//div[@role="dialog"]')
                        )
                    )
                except TimeoutException:
                    print("⚠ Popup did not open")
                    continue

                # Scroll popup and extract names
                names = scroll_popup_and_extract(driver, popup)
                for p in names:
                    all_reactions.append({
                        "Post_Number": f"Post_{total_processed + 1}",
                        "Reactor_Name": p["name"],
                        "Profile_Link": p["link"]
                    })

                save_progress(output, all_reactions)

                # Close popup
                try:
                    close = driver.find_element(
                        By.XPATH, '//div[@aria-label="Close" or contains(@aria-label,"Close")]'
                    )
                    driver.execute_script("arguments[0].click();", close)
                except:
                    try:
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    except:
                        pass

                time.sleep(1)

                # -------------------------
                # RESTORE ORIGINAL SCROLL (CRITICAL FIX)
                # -------------------------
                driver.execute_script(f"window.scrollTo(0, {current_scroll});")
                time.sleep(1)

                total_processed += 1

            except Exception as e:
                print(f"❌ Error: {e}")
                traceback.print_exc()
                continue

        # Handle end-of-feed
        if new_found == 0:
            scroll_attempts_no_new += 1
            if scroll_attempts_no_new >= MAX_SCROLL_ATTEMPTS:
                print("\n🛑 No new posts found — reached end.\n")
                break
        else:
            scroll_attempts_no_new = 0

        # Scroll down properly
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(SCROLL_PAUSE)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == previous_height:
            print("🛑 Reached bottom of page.")
            break

        if total_processed >= 100:
            print("🛑 Safety limit hit (100 posts).")
            break

    print("\n✅ Finished scraping!\n")
    save_progress(output, all_reactions)


# ============================================================
# MAIN
# ============================================================
def main():
    driver = login()
    if not driver:
        print("❌ Login failed.")
        return

    profile = "https://www.facebook.com/ariel.jallorina.73"
    outfile = "airtel_v2_REACTIONS_FIXED.csv"

    scrape_reactions(driver, profile, outfile)

    input("\nPress Enter to close browser...")
    driver.quit()


if __name__ == "__main__":
    main()
