# fb_scraper.py
import time
import csv
import random
import hashlib
from pathlib import Path
from typing import List, Tuple, Set, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
)

from bs4 import BeautifulSoup

# Import your login helper
import fb_login

# ---------- CONFIG ----------
PROFILE_URL = "https://www.facebook.com/shashwat.saxena.14473"  # <-- change this to the profile URL you want
OUTPUT_CSV = Path("output.csv")
SCROLL_PAUSE_MIN = 1.0
SCROLL_PAUSE_MAX = 2.0
MAX_EMPTY_SCROLLS = 5   # stop after this many consecutive scrolls that yield no new posts
WAIT_TIMEOUT = 15
# ----------------------------

def make_post_hash(*parts: str) -> str:
    m = hashlib.sha256()
    for p in parts:
        if p is None:
            p = ""
        m.update(p.encode("utf-8", errors="ignore"))
    return m.hexdigest()


def extract_caption_from_html(html: str) -> str:
    """
    Parse caption HTML and return cleaned text including:
    - text nodes
    - hashtag text (from <a> elements that start with '#')
    - emoji alt text from <img alt="...">
    """
    soup = BeautifulSoup(html or "", "html.parser")
    pieces = []

    for el in soup.descendants:
        # Text nodes
        if isinstance(el, str):
            txt = el.strip()
            if txt:
                pieces.append(txt)
        # Hashtag links
        elif getattr(el, "name", None) == "a":
            txt = el.get_text().strip()
            if txt.startswith("#") and txt:
                pieces.append(txt)
        # Image emoji or accessible alt
        elif getattr(el, "name", None) == "img":
            alt = el.get("alt")
            if alt:
                pieces.append(alt.strip())

    # join with single spaces and normalize whitespace
    return " ".join(pieces).strip()


def extract_image_urls_from_article(article_elem) -> List[str]:
    """
    Given an article (post) WebElement, find all images with scontent CDN and return src URLs.
    """
    try:
        img_elems = article_elem.find_elements(By.CSS_SELECTOR, 'img[src*="scontent"]')
    except Exception:
        return []

    urls = []
    for im in img_elems:
        try:
            src = im.get_attribute("src")
        except StaleElementReferenceException:
            continue
        if src and "scontent" in src:
            if src not in urls:
                urls.append(src)
    return urls


def find_article_from_caption_elem(driver, caption_elem):
    """
    Given a caption element (data-ad-rendering-role="story_message"), try to find
    the enclosing article / post element by walking up ancestors. We'll try:
    - find ancestor with role="article"
    - fallback to parent up some levels
    """
    try:
        # Try xpath to ancestor with role contains article
        article = caption_elem.find_element(By.XPATH, "./ancestor::*[@role='article' or @role='presentation' or contains(@data-testid,'story')]")
        return article
    except Exception:
        # fallback: go up 6 levels to try to hit the post container
        try:
            el = caption_elem
            for _ in range(6):
                el = el.find_element(By.XPATH, "./parent::*")
            return el
        except Exception:
            return None


def gather_visible_posts(driver) -> List[Tuple[str, object, object]]:
    """
    Return a list of tuples (post_unique_key, caption_element, article_element)
    post_unique_key is one of:
      - article id attribute
      - hashed fallback
    """
    posts = []
    # find caption elements (these represent the post message blocks)
    caption_selectors = [
        '[data-ad-rendering-role="story_message"]',
        '[data-ad-preview="message"]',
    ]
    caption_elems = []
    for sel in caption_selectors:
        try:
            caption_elems.extend(driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception:
            continue

    seen_articles = set()
    for cap in caption_elems:
        try:
            article = find_article_from_caption_elem(driver, cap)
            if article is None:
                continue
            # Use article attribute id or data-ft or aria-posinset as possible id; else compute hash
            article_id = None
            try:
                article_id = article.get_attribute("id")
            except Exception:
                article_id = None

            if not article_id:
                try:
                    data_ft = article.get_attribute("data-ft")
                except Exception:
                    data_ft = None
                if data_ft:
                    article_id = make_post_hash(data_ft)
            if not article_id:
                # fallback: hash caption HTML + first image src
                try:
                    inner_html = cap.get_attribute("innerHTML") or ""
                except Exception:
                    inner_html = ""
                imgs = extract_image_urls_from_article(article)
                first_img = imgs[0] if imgs else ""
                article_id = make_post_hash(inner_html, first_img)
            # avoid duplicates in same gather
            if article_id in seen_articles:
                continue
            seen_articles.add(article_id)
            posts.append((article_id, cap, article))
        except StaleElementReferenceException:
            continue
        except WebDriverException:
            continue

    return posts


def ensure_csv_header(path: Path):
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["post_id", "caption", "image_urls"])


def append_row_to_csv(path: Path, row: List[str]):
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def scroll_once(driver):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")


def main():
    print("[*] Starting fb_scraper...")
    # get logged in driver from your fb_login module
    driver = fb_login.main()
    wait = WebDriverWait(driver, WAIT_TIMEOUT)

    print(f"[*] Navigating to target profile: {PROFILE_URL}")
    driver.get(PROFILE_URL)

    # Wait a bit for profile feed to load
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='main'], div[role='feed']")), message="Profile main not found")
    except TimeoutException:
        # not fatal, continue and try to gather posts anyway
        print("[!] Profile main/feed container not detected within timeout — continuing anyway.")

    ensure_csv_header(OUTPUT_CSV)
    seen_posts: Set[str] = set()
    # load existing post_ids from CSV to avoid duplicates across runs
    if OUTPUT_CSV.exists():
        try:
            with OUTPUT_CSV.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    if r and "post_id" in r:
                        seen_posts.add(r["post_id"])
        except Exception:
            pass

    print(f"[*] Already seen {len(seen_posts)} posts from existing CSV (if any).")

    empty_scrolls = 0
    total_new = 0
    last_count = 0

    # initial gather
    posts = gather_visible_posts(driver)
    last_count = len(posts)
    print(f"[*] Found {last_count} visible post candidates initially.")

    while True:
        # gather visible posts
        try:
            posts = gather_visible_posts(driver)
        except Exception as e:
            print("[!] Error gathering posts:", e)
            posts = []

        new_found_this_round = 0
        for post_id, caption_elem, article_elem in posts:
            if post_id in seen_posts:
                continue
            # extract caption html safely
            try:
                caption_html = caption_elem.get_attribute("innerHTML") or ""
            except StaleElementReferenceException:
                continue
            except Exception:
                caption_html = ""
            caption_text = extract_caption_from_html(caption_html)

            # extract image urls
            try:
                image_urls = extract_image_urls_from_article(article_elem)
            except Exception:
                image_urls = []

            # write to CSV
            try:
                append_row_to_csv(OUTPUT_CSV, [post_id, caption_text, "|".join(image_urls)])
                print(f"[+] Saved post {post_id} - images: {len(image_urls)} - caption len: {len(caption_text)}")
            except Exception as e:
                print("[!] Failed to write CSV row:", e)
                continue

            seen_posts.add(post_id)
            new_found_this_round += 1
            total_new += 1

        if new_found_this_round:
            empty_scrolls = 0
        else:
            empty_scrolls += 1

        # attempt to scroll and wait for new content
        scroll_once(driver)
        sleep_time = random.uniform(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX)
        time.sleep(sleep_time)

        # quick heuristic: if we tried MAX_EMPTY_SCROLLS without finding new posts, stop
        if empty_scrolls >= MAX_EMPTY_SCROLLS:
            print(f"[-] No new posts found in {MAX_EMPTY_SCROLLS} consecutive scrolls — stopping.")
            break

        # safety: also stop if we've scraped a very large number (avoid infinite loop)
        if total_new > 5000:
            print("[!] Scraped over 5000 new posts this run — aborting as a safety limit.")
            break

    print(f"[*] Scraper finished. New posts saved this run: {total_new}")
    print(f"[*] Output CSV: {OUTPUT_CSV.resolve()}")
    # optional: keep browser open or quit
    try:
        driver.quit()
    except Exception:
        pass


if __name__ == "__main__":
    main()
