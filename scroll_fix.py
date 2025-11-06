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
from bs4 import BeautifulSoup

# Import your existing login function
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from fb_login import main as login


def extract_fbid(profile_link):
    """
    Extracts the FBID from a profile link.
    """
    try:
        # Case 1: Direct numeric ID in URL
        if "profile.php?id=" in profile_link:
            match = re.search(r"profile\.php\?id=(\d+)", profile_link)
            if match:
                return match.group(1)

        # Case 2: Username-based URL (we'll extract the numeric ID if available)
        match = re.search(r"[?&]id=(\d+)", profile_link)
        if match:
            return match.group(1)

        # Case 3: Fallback — if it's a username link, just return username as ID substitute
        username_match = re.search(r"facebook\.com/([^/?&]+)", profile_link)
        if username_match:
            return username_match.group(1)

        return None
    except Exception:
        return None


def extract_names_from_popup(driver):
    """
    Extracts all currently visible names from the popup.
    Returns a list of dicts with name, link, and fbid.
    """
    extracted_data = []
    seen_fbids = set()
    
    try:
        popup = driver.find_element(By.XPATH, '//div[@role="dialog"]')
        popup_html = popup.get_attribute("outerHTML")
        soup = BeautifulSoup(popup_html, "html.parser")
        
        name_elements = soup.find_all("a", href=True)
        
        for a in name_elements:
            name = a.get_text(strip=True)
            link = a["href"]
            
            # Skip invalid entries
            if not name or len(name) < 2:
                continue
            if not any(x in link for x in ["/profile.php?id=", "facebook.com/"]):
                continue
            if any(x in link for x in ["/pages/", "/groups/", "/events/", "/stories/", "/photo/", "/video/"]):
                continue
            
            # Extract FBID
            fbid = extract_fbid(link)
            
            # Skip duplicates based on FBID
            if fbid and fbid in seen_fbids:
                continue
            
            if fbid:
                seen_fbids.add(fbid)
            
            extracted_data.append({
                "name": name,
                "link": link,
                "fbid": fbid if fbid else "N/A"
            })
    
    except Exception as e:
        print(f"⚠️ Error extracting names: {e}")
    
    return extracted_data


def scroll_and_scrape_popup(driver):
    """
    Scrolls the Facebook reactions popup fully and extracts all names, links, and FBIDs.
    Works reliably with modern Facebook layouts.
    """
    all_names = {}
    seen_fbids = set()

    try:
        # Wait for popup to appear
        popup = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
        )
        print("📋 Popup detected. Starting extraction...")

        # --- Find the true scrollable container ---
        scrollable_container = None
        divs = popup.find_elements(By.XPATH, ".//div")

        for div in divs:
            try:
                scroll_height = driver.execute_script("return arguments[0].scrollHeight;", div)
                client_height = driver.execute_script("return arguments[0].clientHeight;", div)
                if scroll_height and scroll_height > client_height + 100:
                    scrollable_container = div
                    print("✅ Found actual scrollable container inside popup.")
                    break
            except Exception:
                continue

        if not scrollable_container:
            print("⚠️ No scrollable div found — using popup itself.")
            scrollable_container = popup

        # Debug snippet of container HTML
        snippet = scrollable_container.get_attribute("outerHTML")[:800]
        print("🔍 Scrollable container snippet:\n", snippet, "\n--- END SNIPPET ---\n")

        # --- Scroll until no more new names appear ---
        last_height = 0
        same_height_count = 0
        scroll_round = 0
        max_scroll_rounds = 40

        while scroll_round < max_scroll_rounds:
            scroll_round += 1
            print(f"🔽 Scroll attempt #{scroll_round}")

            # Scroll to bottom of container
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable_container)
            time.sleep(2.5)  # Wait for new users to load

            # Extract visible names after scroll
            new_data = extract_names_from_popup(driver)
            before_count = len(all_names)
            for person in new_data:
                key = person['fbid'] if person['fbid'] != "N/A" else person['name']
                if key not in all_names:
                    all_names[key] = person
            after_count = len(all_names)

            print(f"   ✅ Found {after_count - before_count} new names (Total: {after_count})")

            # Check if scroll height has changed
            new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable_container)
            if new_height == last_height:
                same_height_count += 1
                print(f"   ⏸️ No scroll height change ({same_height_count}/3)")
            else:
                same_height_count = 0

            last_height = new_height

            # Stop if no new content after several rounds
            if same_height_count >= 3:
                print("✅ Reached end of popup list. Stopping scroll.")
                break

        print(f"\n🎉 Scroll finished. Total unique names collected: {len(all_names)}")

    except Exception as e:
        print(f"❌ Error during popup scroll: {e}")
        import traceback
        traceback.print_exc()

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

                # Re-find buttons to avoid stale element reference
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

                    # Wait for popup to appear
                    popup = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
                    )

                    # Click "All" tab if available
                    try:
                        all_tab = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, '//div[@role="tablist"]//span[text()="All"]'))
                        )
                        driver.execute_script("arguments[0].click();", all_tab)
                        print("✅ Clicked 'All' tab")
                        time.sleep(2)
                    except Exception:
                        print("⚠️ 'All' tab not found or already selected.")

                    # ✅ Scroll and scrape incrementally
                    all_reactors = scroll_and_scrape_popup(driver)
                    
                    # Add to results
                    for person in all_reactors:
                        all_reactions_data.append({
                            "Post_Number": f"Post_{idx + 1}",
                            "Reactor_Name": person['name'],
                            "Profile_Link": person['link'],
                            "FBID": person['fbid']
                        })
                    
                    print(f"\n✅ Total names saved for Post #{idx + 1}: {len(all_reactors)}")

                    # Close popup
                    try:
                        close_button = driver.find_element(
                            By.XPATH, '//div[@aria-label="Close" or (@role="button" and contains(@aria-label, "Close"))]'
                        )
                        driver.execute_script("arguments[0].click();", close_button)
                        print("🔒 Closed popup with close button")
                    except Exception:
                        try:
                            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                            print("🔒 Closed popup with ESC key")
                        except:
                            print("⚠️ Could not close popup, continuing...")

                    time.sleep(3)

                except TimeoutException:
                    print(f"❌ Timeout waiting for popup on post #{idx + 1}")
                    continue
                except Exception as e:
                    print(f"❌ Error processing post #{idx + 1}: {str(e)[:150]}...")
                    import traceback
                    traceback.print_exc()
                    continue

            processed_posts = len(reaction_buttons)
            if processed_posts >= 50:
                print("\n✅ Reached 50 posts limit. Stopping...")
                break

    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        if all_reactions_data:
            with open(output_filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['Post_Number', 'Reactor_Name', 'Profile_Link', 'FBID']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_reactions_data)

            print(f"\n{'='*60}")
            print(f"💾 Data saved to {output_filename}")
            print(f"📊 Total entries scraped: {len(all_reactions_data)}")
            
            # Show unique count
            unique_fbids = set(row['FBID'] for row in all_reactions_data if row['FBID'] != 'N/A')
            print(f"👥 Unique users: {len(unique_fbids)}")
            print(f"{'='*60}")
        else:
            print("\n❌ No data found in popups.")


def main():
    print("🔐 Logging into Facebook...")
    driver = login()

    if driver:
        try:
            profile_url = "https://www.facebook.com/profile.php?id=100064151734126"
            output_file = "100064151734126_file.csv"

            print(f"🎯 Starting reaction scraping for: {profile_url}")
            scrape_reactions(driver, profile_url, output_file)

        except Exception as e:
            print(f"❌ Error during scraping: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            input("\nPress Enter to close the browser...")
            driver.quit()
    else:
        print("❌ Failed to log in. Cannot proceed with scraping.")


if __name__ == "__main__":
    main()