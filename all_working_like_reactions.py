from selenium import webdriver 
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
import time
import csv
import sys
import os
import re

# Import your existing login function
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from fb_login import main as login


def extract_fbid(profile_link):
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


def extract_names_from_popup(driver):
    """Extracts all visible user names from the open reaction popup."""
    extracted_data = []
    seen_fbids = set()
    try:
        name_elements = driver.find_elements(
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
                fbid = extract_fbid(link)
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


def scroll_and_scrape_popup(driver):
    """
    Scrolls the Facebook reaction popup and extracts all visible user names.
    Targets the actual scroll container for reliable behavior.
    """
    all_names = {}
    try:
        # Wait for popup
        popup = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
        )
        print("📋 Popup detected. Looking for scrollable container...")

        # Find the actual scrollable div (this is the stable selector)
        scroll_container = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//div[contains(@class, 'x2atdfe') and contains(@class, 'x1c1uobl')]"
            ))
        )
        print("✅ Found scrollable container for popup.")

        last_height = driver.execute_script("return arguments[0].scrollHeight;", scroll_container)
        same_height_count = 0
        scroll_attempts = 0

        while True:
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scroll_container)
            time.sleep(1.8)

            new_height = driver.execute_script("return arguments[0].scrollHeight;", scroll_container)

            # Extract names after each scroll
            new_data = extract_names_from_popup(driver)
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


def scrape_reactions(driver, profile_url, output_filename="facebook_reactions.csv"):
    all_reactions_data = []
    processed_posts = 0
    try:
        driver.get(profile_url)
        print("Navigated to profile. Waiting for page to load...")
        time.sleep(5)

        while processed_posts < 50:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            print("Scrolling to load more posts...")
            time.sleep(3)

            reaction_buttons = driver.find_elements(
                By.XPATH,
                '//div[@role="button" and .//div[contains(text(), "All reactions:")]]'
            )
            print(f"Found {len(reaction_buttons)} reaction buttons total")

            for idx in range(processed_posts, len(reaction_buttons)):
                if idx >= len(reaction_buttons):
                    break
                reaction_buttons = driver.find_elements(
                    By.XPATH,
                    '//div[@role="button" and .//div[contains(text(), "All reactions:")]]'
                )
                if idx >= len(reaction_buttons):
                    break
                button = reaction_buttons[idx]

                try:
                    print(f"\n{'='*60}")
                    print(f"🟢 Processing post #{idx + 1}")
                    print(f"{'='*60}")

                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                    time.sleep(2)
                    driver.execute_script("arguments[0].click();", button)
                    print("✅ Opened reactions popup")
                    time.sleep(3)

                    # Ensure popup and click "All" if needed
                    popup = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
                    )
                    try:
                        all_tab = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, '//div[@role="tablist"]//span[text()="All"]'))
                        )
                        driver.execute_script("arguments[0].click();", all_tab)
                        print("✅ Clicked 'All' tab")
                        time.sleep(2)
                    except Exception:
                        print("⚠️ 'All' tab not found or already active.")

                    # Scroll and scrape
                    all_reactors = scroll_and_scrape_popup(driver)
                    for person in all_reactors:
                        all_reactions_data.append({
                            "Post_Number": f"Post_{idx + 1}",
                            "Reactor_Name": person['name'],
                            "Profile_Link": person['link'],
                            "FBID": person['fbid']
                        })

                    print(f"✅ Saved {len(all_reactors)} names for Post #{idx + 1}")

                    # Close popup
                    try:
                        close_btn = driver.find_element(
                            By.XPATH, '//div[@aria-label="Close" or (@role="button" and contains(@aria-label, "Close"))]'
                        )
                        driver.execute_script("arguments[0].click();", close_btn)
                        print("🔒 Closed popup")
                    except Exception:
                        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                        print("🔒 Closed popup with ESC")

                    time.sleep(3)

                except TimeoutException:
                    print(f"❌ Timeout on post #{idx + 1}")
                    continue
                except Exception as e:
                    print(f"❌ Error on post #{idx + 1}: {str(e)[:120]}")
                    import traceback; traceback.print_exc()
                    continue

            processed_posts = len(reaction_buttons)
            if processed_posts >= 50:
                print("✅ Reached 50 posts limit. Stopping...")
                break

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback; traceback.print_exc()

    finally:
        if all_reactions_data:
            with open(output_filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['Post_Number', 'Reactor_Name', 'Profile_Link', 'FBID']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_reactions_data)
            print(f"💾 Data saved to {output_filename}")
            print(f"📊 Total scraped: {len(all_reactions_data)}")
            unique = set(r['FBID'] for r in all_reactions_data if r['FBID'] != 'N/A')
            print(f"👥 Unique users: {len(unique)}")
        else:
            print("❌ No data found.")


def main():
    print("🔐 Logging into Facebook...")
    driver = login()
    if driver:
        try:
            profile_url = "https://www.facebook.com/profile.php?id=100064151734126"
            output_file = "dhdsdhest.csv"
            print(f"🎯 Starting scraping for: {profile_url}")
            scrape_reactions(driver, profile_url, output_file)
        except Exception as e:
            print(f"❌ Scraping error: {e}")
            import traceback; traceback.print_exc()
        finally:
            input("\nPress Enter to close browser...")
            driver.quit()
    else:
        print("❌ Login failed. Cannot start scraper.")


if __name__ == "__main__":
    main()
