import time
import random
import csv
import hashlib
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from fb_login import main as fb_login_main


def find_scrollable_container_in_popup(driver, popup):
    """
    Inspect all divs inside popup to pick the one that actually scrolls (scrollHeight > clientHeight).
    Fallback to popup itself when none found.
    """
    scrollable = None
    divs = popup.find_elements(By.XPATH, ".//div")
    for div in divs:
        try:
            scroll_height = driver.execute_script("return arguments[0].scrollHeight;", div)
            client_height = driver.execute_script("return arguments[0].clientHeight;", div)
            if scroll_height and client_height and scroll_height > client_height + 50:
                scrollable = div
                break
        except Exception:
            continue
    if not scrollable:
        scrollable = popup
    return scrollable


def click_show_more_in_popup(driver, popup_container):
    """
    Click 'View more comments' / 'See more' style links inside the popup container to reveal nested comments.
    This is conservative: tries multiple candidate texts and clicks up to a few times.
    """
    candidates = [
        "View more comments",
        "View previous comments",
        "See more comments",
        "View more replies",
        "See more",
        "More comments"
    ]
    clicked_any = False
    for _ in range(3):  # attempt a few times while content loads
        found_one = False
        for text in candidates:
            try:
                # relative search so we only click links inside popup
                elems = popup_container.find_elements(By.XPATH, f".//a[contains(., '{text}') or .//span[contains(., '{text}')]]")
                for e in elems:
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", e)
                        time.sleep(0.2)
                        driver.execute_script("arguments[0].click();", e)
                        found_one = True
                        clicked_any = True
                        time.sleep(random.uniform(0.6, 1.2))
                    except Exception:
                        continue
            except Exception:
                continue
        if not found_one:
            break
    return clicked_any


def extract_comments_from_container(popup_container):
    """
    Extract commenter name, profile link (href), fbid (if present in link), and comment text.
    Only searches inside popup_container (relative XPATHs).
    """
    results = []

    # Limit search strictly to comment threads inside the popup
    # Facebook comments are typically under role='article' or data-visualcompletion="ignore-dynamic"
    candidate_comment_blocks = popup_container.find_elements(
        By.XPATH,
        ".//div[@role='article' or @aria-label='Comment' or .//a[contains(@href,'facebook.com')]]"
    )

    for block in candidate_comment_blocks:
        try:
            # Strictly ensure this block is inside the popup
            try:
                is_inside_popup = popup_container.find_element(By.XPATH, f".//div[@id='{block.get_attribute('id')}']") if block.get_attribute('id') else True
            except Exception:
                is_inside_popup = True
            if not is_inside_popup:
                continue

            # --- Extract profile link + name ---
            a = None
            try:
                a = block.find_element(By.XPATH, ".//a[contains(@href,'facebook.com')][1]")
            except Exception:
                anchors = block.find_elements(By.XPATH, ".//a[contains(@href,'facebook.com')]")
                a = anchors[0] if anchors else None

            name = ""
            profile_link = ""
            fbid = "N/A"

            if a:
                profile_link = a.get_attribute("href") or ""
                name = a.text.strip() or a.get_attribute("aria-label") or ""
                if not name:
                    try:
                        name = a.find_element(By.XPATH, ".//span").text.strip()
                    except Exception:
                        pass

                # Extract fbid from href if possible
                import re
                try:
                    href = profile_link
                    if "profile.php?id=" in href:
                        m = re.search(r"profile\.php\?id=(\d+)", href)
                        if m:
                            fbid = m.group(1)
                    else:
                        m = re.search(r"/(\d{6,})", href)
                        if m:
                            fbid = m.group(1)
                except Exception:
                    fbid = "N/A"

            # --- Extract comment text ---
            comment_text = ""
            try:
                # Only text blocks inside the popup container
                comment_elem = block.find_element(
                    By.XPATH,
                    ".//div[@dir='auto' and not(.//a[contains(@href,'facebook.com')]) and string-length(normalize-space(.))>0]"
                )
                comment_text = comment_elem.text.strip()
            except Exception:
                try:
                    el = block.find_element(By.XPATH, ".//span[string-length(normalize-space(.))>0]")
                    comment_text = el.text.strip()
                except Exception:
                    comment_text = ""

            # Only append if both name/comment found
            if name or comment_text:
                results.append({
                    "name": name,
                    "profile_link": profile_link,
                    "fbid": fbid,
                    "comment": comment_text
                })

        except Exception:
            continue

    # Deduplicate results
    seen = set()
    unique = []
    for item in results:
        key = (item.get("fbid", "N/A"), item.get("name", ""), item.get("comment", ""))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def scroll_and_extract_comments(driver, post_number):
    """
    Waits for the comment popup, finds the scrollable container inside it,
    clicks 'show more' links, scrolls until no new content appears, and returns list of comment dicts.
    """
    all_comments = {}
    try:
        popup = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, '//div[@role="dialog"]')))
        print("📋 Comment popup detected.")
    except Exception as e:
        print("⚠️ Could not detect comment popup:", e)
        return []

    scrollable = find_scrollable_container_in_popup(driver, popup)
    print("🔍 Using scrollable container:", scrollable.get_attribute("outerHTML")[:300])

    # Try clicking any 'show more' links first (a few times)
    click_show_more_in_popup(driver, scrollable)
    time.sleep(0.8)

    # Scroll loop similar to your reaction code
    last_height = -1
    same_height_count = 0
    max_rounds = 60
    round_i = 0

    while round_i < max_rounds:
        round_i += 1
        try:
            print(f"🔽 Popup scroll attempt #{round_i}")
            driver.execute_script("arguments[0].scrollTo(0, arguments[0].scrollHeight);", scrollable)
            time.sleep(random.uniform(1.2, 2.5))

            # after scroll, try clicking more-expansion links that may have appeared
            click_show_more_in_popup(driver, scrollable)
            time.sleep(0.6)

            # Extract visible comments inside popup
            new_items = scrollable.find_elements(By.XPATH, ".//div[.//a[contains(@href,'facebook.com')]]")
            # call extract function to get structured results
            extracted = extract_comments_from_container(scrollable)
            before_count = len(all_comments)
            for it in extracted:
                key = it["fbid"] if it["fbid"] != "N/A" else (it["name"] + "|" + it["comment"][:60])
                if key not in all_comments:
                    all_comments[key] = it
            after_count = len(all_comments)
            print(f"   ✅ Found {after_count - before_count} new comments (Total: {after_count})")

            # measure container scrollHeight to detect end
            new_height = driver.execute_script("return arguments[0].scrollHeight;", scrollable)
            if new_height == last_height:
                same_height_count += 1
                print(f"   ⏸️ No height change ({same_height_count}/3)")
            else:
                same_height_count = 0

            last_height = new_height

            if same_height_count >= 3:
                print("✅ Reached end of comments in popup.")
                break

        except Exception as e:
            print("⚠️ Scroll loop error:", e)
            break

    print(f"🎉 Finished popup scraping. Collected {len(all_comments)} unique commenters/comments.")
    return list(all_comments.values())


def open_facebook_comments():
    driver = fb_login_main()
    wait = WebDriverWait(driver, 15)

    profile_url = "https://www.facebook.com/shashwat.saxena.14473"
    driver.get(profile_url)
    time.sleep(5)

    print("✅ Opened Facebook profile. Scrolling through posts...")

    clicked_posts = set()
    last_height = driver.execute_script("return document.body.scrollHeight")

    # Initialize CSV file with headers
    with open("facebook_comments.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["post_number", "commenter_name", "profile_link", "fbid", "comment_text"])

    while True:
        try:
            comment_buttons = driver.find_elements(
                By.XPATH,
                "//div[@role='button' and (descendant::span[contains(translate(., 'COMMENTS', 'comments'),'comment') or contains(.,'Comment') or contains(.,'comments')])]"
            )

            print(f"🔍 Found {len(comment_buttons)} possible comment buttons on screen")

            for index, button in enumerate(comment_buttons):
                try:
                    # Identify a stable post container (data-ft or fallback hashing)
                    post_container = None
                    for level in range(1, 10):
                        try:
                            ancestor = button.find_element(By.XPATH, f"./ancestor::div[{level}]")
                            if ancestor.get_attribute("data-ft"):
                                post_container = ancestor
                                break
                        except Exception:
                            continue

                    if post_container and post_container.get_attribute("data-ft"):
                        post_id = post_container.get_attribute("data-ft")
                    else:
                        post_html = button.get_attribute("outerHTML")
                        post_id = hashlib.md5(post_html.encode("utf-8")).hexdigest()

                    if post_id in clicked_posts:
                        continue

                    clicked_posts.add(post_id)

                    # Scroll and click the comment button
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                    time.sleep(1.2)
                    driver.execute_script("arguments[0].click();", button)
                    print(f"💬 Opened comment popup for post #{len(clicked_posts)}")

                    # Wait a little for popup
                    time.sleep(2)
                    comments = scroll_and_extract_comments(driver, len(clicked_posts))

                    # Save comments to CSV
                    if comments:
                        with open("facebook_comments.csv", "a", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            for c in comments:
                                writer.writerow([len(clicked_posts), c.get("name"), c.get("profile_link"), c.get("fbid"), c.get("comment")])
                        print(f"💾 Saved {len(comments)} comments for post #{len(clicked_posts)}")
                    else:
                        print("⚠️ No comments extracted from popup.")

                    # Close popup
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(1.2)
                    print("❌ Closed comment popup\n")

                except Exception as e:
                    print(f"⚠️ Could not process comment button #{index + 1}: {e}")
                    continue

            # Scroll page to load more posts
            driver.execute_script("window.scrollBy(0, window.innerHeight * 0.8);")
            time.sleep(random.uniform(3, 5))

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                print("✅ Reached the end of visible posts.")
                break
            last_height = new_height

        except Exception as main_e:
            print(f"⚠️ Main loop error: {main_e}")
            break

    print(f"🎉 Finished scraping all comments. Total unique posts visited: {len(clicked_posts)}")
    driver.quit()


if __name__ == "__main__":
    open_facebook_comments()
