"""
friends_friends_list.py
Scrape your friends network recursively: your friends + their friends.

Now extracts each user's true Facebook numeric ID (fbid) by parsing the HTML source.
"""

import csv
import time
import random
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def extract_fbid_from_source(driver):
    """
    Extract the numeric Facebook ID (fbid) directly from the HTML source of a profile.
    Looks for `"profile_owner":{"id":"<fbid>"` in the page source.
    """
    try:
        html = driver.page_source
        match = re.search(r'"profile_owner":\{"id":"(\d+)"', html)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def extract_fbid_from_url(url: str) -> str:
    """
    Fallback: extract a Facebook ID or username from a profile URL if needed.
    """
    if not url:
        return ""

    # Case 1: numeric ID in URL
    match = re.search(r"profile\.php\?id=(\d+)", url)
    if match:
        return match.group(1)

    # Case 2: vanity username style URL
    username = url.rstrip("/").split("/")[-1]
    if username and username not in ["friends", "photos", "videos"]:
        return f"username:{username}"

    return ""


def scrape_friends_page(driver, profile_url, scroll_limit=5):
    """
    Scrape all friends from a given profile URL.
    Returns list of dicts: [{"name": ..., "url": ..., "fbid": ...}, ...]
    """
    friends_url = profile_url.rstrip("/") + "/friends"
    driver.get(friends_url)
    wait = WebDriverWait(driver, 20)

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[role='link'] span.x193iq5w")))
    except Exception:
        print(f"[-] Could not load friends for {profile_url}")
        return []

    time.sleep(2)

    # Scroll to load more friends
    for _ in range(scroll_limit):
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
        time.sleep(random.uniform(1.5, 3.0))

    friends = []
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")

    for a in anchors:
        try:
            url = a.get_attribute("href")
            span = a.find_element(By.CSS_SELECTOR, "span.x193iq5w")
            name = span.text.strip()

            if name and url and "facebook.com" in url and "/friends" not in url:
                # Open the profile in a new tab temporarily to extract true fbid
                driver.execute_script("window.open(arguments[0]);", url)
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(2)

                fbid = extract_fbid_from_source(driver)
                if not fbid:
                    fbid = extract_fbid_from_url(url)

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

                friends.append({"name": name, "url": url, "fbid": fbid})
                print(f"   [+] {name} → fbid: {fbid}")
        except Exception:
            continue

    print(f"[+] Found {len(friends)} friends at {profile_url}")
    return friends


def scrape_friends_network(driver, output_csv="friends_network.csv", scroll_limit=5):
    """
    Scrape your friends network (you + your friends + their friends).
    Saves to CSV with numeric fbids where available.
    """
    network = []

    # Step 1 — get your own profile and fbid
    driver.get("https://www.facebook.com/me")
    wait = WebDriverWait(driver, 15)
    time.sleep(3)

    try:
        name_span = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.x193iq5w")))
        my_name = name_span.text.strip()
        my_url = driver.current_url
        my_fbid = extract_fbid_from_source(driver)
        if not my_fbid:
            my_fbid = extract_fbid_from_url(my_url)
    except Exception:
        print("[-] Could not get own profile details.")
        return

    print(f"[+] Starting with profile: {my_name} ({my_url}) — fbid={my_fbid}")

    # Step 2 — scrape your own friends
    my_friends = scrape_friends_page(driver, my_url, scroll_limit=scroll_limit)

    # Save own friends (Level 1)
    for fr in my_friends:
        network.append({
            "source_name": my_name,
            "source_url": my_url,
            "source_fbid": my_fbid,
            "friend_name": fr["name"],
            "friend_url": fr["url"],
            "friend_fbid": fr["fbid"]
        })

    # Step 3 — scrape each friend's friends (Level 2)
    for idx, fr in enumerate(my_friends, start=1):
        print(f"\n[{idx}/{len(my_friends)}] Scraping friends of {fr['name']} ...")
        subfriends = scrape_friends_page(driver, fr["url"], scroll_limit=3)

        for sf in subfriends:
            network.append({
                "source_name": fr["name"],
                "source_url": fr["url"],
                "source_fbid": fr["fbid"],
                "friend_name": sf["name"],
                "friend_url": sf["url"],
                "friend_fbid": sf["fbid"]
            })

        time.sleep(random.uniform(3, 6))  # polite delay

    # Step 4 — Save network to CSV
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "source_name", "source_url", "source_fbid",
            "friend_name", "friend_url", "friend_fbid"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(network)

    print(f"[✅] Friends network saved to {output_csv}")


# Example usage
if __name__ == "__main__":
    from fb_login import main
    driver = main()
    scrape_friends_network(driver, output_csv="friends_network.csv", scroll_limit=3)
