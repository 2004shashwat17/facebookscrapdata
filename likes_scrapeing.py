from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import csv
import sys
import os
from bs4 import BeautifulSoup

# Import your existing login function
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from fb_login import main as login


def scrape_reactions(driver, profile_url, output_filename="facebook_reactions.csv"):
    """
    Navigates to a profile, finds posts, opens reactions popup, and scrapes ONLY the names visible inside the popup.
    """
    all_reactions_data = []
    processed_posts = 0

    try:
        driver.get(profile_url)
        print("Navigated to profile. Waiting for page to load...")
        time.sleep(5)

        while processed_posts < 50:
            # Scroll to bottom to load more posts
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            print("Scrolling to load more posts...")
            time.sleep(3)

            # Find all reaction buttons
            reaction_buttons = driver.find_elements(By.XPATH, '//div[contains(@aria-label, "Like:") and @role="button"]')
            print(f"Found {len(reaction_buttons)} reaction buttons total")

            # Process new posts only
            for idx in range(processed_posts, len(reaction_buttons)):
                if idx >= len(reaction_buttons):
                    break

                button = reaction_buttons[idx]
                try:
                    print(f"🟢 Processing post #{idx + 1}")
                    driver.execute_script("arguments[0].scrollIntoView(true);", button)
                    time.sleep(2)

                    # Click reaction button
                    driver.execute_script("arguments[0].click();", button)
                    print(f"🟢 Opened reactions popup for post #{idx + 1}")
                    time.sleep(3)

                    # Wait for popup
                    popup = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]'))
                    )

                    # Get popup HTML only
                    popup_html = popup.get_attribute("outerHTML")
                    soup = BeautifulSoup(popup_html, "html.parser")

                    # Extract names from popup only
                    reactors_for_this_post = []
                    name_elements = soup.find_all("a", href=True)

                    for a in name_elements:
                        name = a.get_text(strip=True)
                        link = a["href"]

                        # Skip empty, short, or non-user links
                        if not name or len(name) < 2:
                            continue
                        if not any(x in link for x in ["/profile.php?id=", "facebook.com/"]):
                            continue
                        if any(x in link for x in ["/pages/", "/groups/", "/events/", "/stories/", "/photo/", "/video/"]):
                            continue

                        # Clean name (no special characters)
                        import re
                        if not re.match(r"^[A-Za-zÀ-ÿ\s.'-]+$", name):
                            continue

                        if name in reactors_for_this_post:
                            continue

                        # Determine reaction type (optional)
                        reaction_type = "Like"
                        parent = a.find_parent("div")
                        if parent:
                            img = parent.find("img")
                            if img and "src" in img.attrs:
                                src = img["src"].lower()
                                if "love" in src:
                                    reaction_type = "Love"
                                elif "care" in src:
                                    reaction_type = "Care"
                                elif "haha" in src:
                                    reaction_type = "Haha"
                                elif "wow" in src:
                                    reaction_type = "Wow"
                                elif "sad" in src:
                                    reaction_type = "Sad"
                                elif "angry" in src:
                                    reaction_type = "Angry"

                        reactors_for_this_post.append(name)
                        all_reactions_data.append({
                            "Post_Number": f"Post_{idx + 1}",
                            "Reactor_Name": name,
                            "Profile_Link": link,
                            "Reaction_Type": reaction_type
                        })

                    print(f"  ✅ Scraped {len(reactors_for_this_post)} names from popup for post #{idx + 1}")

                    # Close popup
                    try:
                        close_button = driver.find_element(By.XPATH, '//div[@aria-label="Close" or @role="button" and contains(@aria-label, "Close")]')
                        driver.execute_script("arguments[0].click();", close_button)
                    except Exception:
                        from selenium.webdriver.common.keys import Keys
                        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)

                    print(f"  🔒 Closed popup for post #{idx + 1}")
                    time.sleep(2)

                except TimeoutException:
                    print(f"  ❌ Timeout waiting for popup on post #{idx + 1}")
                    continue
                except Exception as e:
                    print(f"  ❌ Error processing post #{idx + 1}: {str(e)[:100]}...")
                    continue

            processed_posts = len(reaction_buttons)
            if processed_posts >= 50:
                print("Reached 50 posts limit. Stopping...")
                break

    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
    finally:
        if all_reactions_data:
            with open(output_filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Post_Number', 'Reactor_Name', 'Profile_Link', 'Reaction_Type']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for data in all_reactions_data:
                    writer.writerow(data)
            print(f"\n💾 Scraping completed! Data saved to {output_filename}")
            print(f"📊 Total reactions scraped: {len(all_reactions_data)}")
            print(f"📝 Total posts processed: {processed_posts}")
        else:
            print("\n❌ No data found in popups.")


def main():
    print("🔐 Logging into Facebook...")
    driver = login()

    if driver:
        try:
            profile_url = "https://www.facebook.com/shashwat.saxena.14473"
            output_file = "facebook_reactions_data.csv"

            print(f"🎯 Starting reaction scraping for: {profile_url}")
            scrape_reactions(driver, profile_url, output_file)

        except Exception as e:
            print(f"❌ Error during scraping: {str(e)}")
        finally:
            input("\nPress Enter to close the browser...")
            driver.quit()
    else:
        print("❌ Failed to log in. Cannot proceed with scraping.")


if __name__ == "__main__":
    main()
