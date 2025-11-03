
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time


def scroll_and_click_button(driver):
    '''Scroll down and click the button to load button "All comments| Most relevant,...'''
    cnt = 3
    try:
        # Scroll down until the button is found and clickable
        while True:
            if cnt <= 0:
                break
            try:
                # Prefer text-based fallback for the sort menu trigger
                possible_triggers = [
                    "Most relevant", "All comments", "Newest", "Oldest"
                ]
                clicked = False
                for label in possible_triggers:
                    try:
                        el = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{label}')]"))
                        )
                        el.click()
                        clicked = True
                        print("Button clicked successfully.")
                        break
                    except Exception:
                        continue
                if clicked:
                    break
                # Fallback: brittle class-based selector (last resort)
                button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "div.x9f619.x1n2onr6.x1ja2u2z.x6s0dn4.x3nfvp2.xxymvpz"))
                )
                button.click()
                print("Button clicked successfully.")
                break
            except Exception as e:
                # Scroll down a bit and try again
                driver.execute_script("window.scrollBy(0, 1000);")
                cnt -= 1
        return True
    except Exception as e:
        print("Unable to locate and click the button.", e)
        return False

def click_view_more_btn(driver):
    '''Click the view more button to change the show style of comments of a post'''

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    # Find the view more button (try several common labels)
    labels = [
        'View more comments', 'See more comments', 'more comments',
        'View more replies', 'See more replies', 'more replies'
    ]
    clicked = False
    for label in labels:
        try:
            view_more_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(), '{label}')]"))
            )
            view_more_btn.click()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        # Fallback: generic button role near comments container
        try:
            generic_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@role='button' and .//span[contains(text(),'more')]]"))
            )
            generic_btn.click()
        except Exception:
            raise
    print("View more button clicked successfully.")
    return None

def click_showed_type_btn(driver, btn_name):
    '''Click the button to show the most relevant comments or all comments under a post by the argument btn_name'''

    try:
        # Scroll down to the button and click
        driver.execute_script("window.scrollTo(0, window.scrollY)")  # Scroll to the top

        # Try requested label first, then fallbacks
        labels = [btn_name, 'Most relevant', 'All comments', 'Newest', 'Oldest']
        for label in labels:
            try:
                button = WebDriverWait(driver, 6).until(
                    EC.element_to_be_clickable((By.XPATH, f"//*[contains(text(), '{label}')]"))
                )
                button.click()
                return True
            except Exception:
                continue
    except Exception as e:
        print("Can not click", btn_name)
        return False

def show_more_comments1(driver, time=200):
    import time as _time
    while True:
        try:
            click_view_more_btn(driver)
            # Try to scroll the comments feed area only
            try:
                comments_feed = driver.find_element(By.CSS_SELECTOR, "div[role='feed']")
                for _ in range(3):
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", comments_feed)
                    _time.sleep(1)
            except Exception:
                # Fallback: scroll window
                driver.execute_script("window.scrollBy(0, 500);")
            time -= 1
            if time < 0:
                break
            _time.sleep(1)  # Give time for comments to load
        except Exception as e:
            print("Out of contents")
            break

def show_more_comments(driver):
    '''Show more comments under a post'''

    # Limit the number of attempts to load more comments
    max_attempts = 10  # Adjust based on typical post length and your needs
    attempts = 0
    last_count = 0
    stable_attempts = 3  # Number of attempts with no new comments before considering end

    # Keep trying to load more comments until the limit is reached
    while attempts < max_attempts:
        try:
            click_view_more_btn(driver)
            time.sleep(2)  # Give some time for comments to load
            current_count = len(driver.find_elements(By.XPATH, "//div[contains(@class, 'x1n2onr6 x46jau6')]"))

            if current_count == last_count:
                stable_attempts -= 1
                if stable_attempts == 0:
                    print("No more comments to load.")
                    break
            else:
                last_count = current_count
                stable_attempts = 3  # Reset the stable_attempts counter

            attempts += 1
        except Exception as e:
            print("All comments loaded.")
            break

def show_all_replies(driver, threshold, ite):
    '''Show all replies of comments under a post
    Limited time: start - end = 3s => If there is no comment shown in 3s, stop
    Threshold: maximum number of comments'''
    arr = []
    cnt = 1
    while True:
        start = time.time() 
        if cnt > threshold: #Threshold
            break
        try:
            # Find replied comments
            all_replied_comments = driver.find_elements(By.XPATH, "//div[contains(@class, 'x1n2onr6 x46jau6')]")
        except:
            break
        
        # save count of comments to check if all comments are shown
        arr.append(len(all_replied_comments))
        if arr.count(max(arr)) >= ite:
            print("All replies are shown")
            return
        
        # Try to show sub-replied comments in replied-comments
        for comment in all_replied_comments:

            driver.execute_script("window.scrollBy(0, -50);")  # Scroll down 50px to load more comments
        
            try:
                view_more_buttons = WebDriverWait(comment, 10).until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'html-div xe8uvvx xdj266r x11i5rnm xat24cr x1mh8g0r xexx8yu x4uap5 x18d9i69 xkhd6sd x78zum5 x1iyjqo2 x21xpn4 x1n2onr6')]")))
                view_more_buttons.click()
                sub_cmt = comment.find_elements(By.XPATH, "//div[contains(@class, 'x1n2onr6 x1swvt13 x1iorvi4 x78zum5 x1q0g3np x1a2a7pz')]")
                for sub_cmt in comment:
                    try:
                        view_more_sub_buttons = WebDriverWait(sub_cmt, 10).until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'html-div xe8uvvx xdj266r x11i5rnm xat24cr x1mh8g0r xexx8yu x4uap5 x18d9i69 xkhd6sd x78zum5 x1iyjqo2 x21xpn4 x1n2onr6')]")))
                        view_more_sub_buttons.click()
                        #cnt += 1
                    except:
                        break

                cnt += 1

            except Exception as e:
                break

            finally:
                end = time.time()
                if end - start > 3:
                    #print("Finally")
                    return

def filter_spam(text):
    '''Filter spam comments based on user-defined keywords'''

    spam_text = ['http', 'miễn phí', '100%', 'kèo bóng', 'khóa học', 'netflix', 'Net Flix', 'shopee', 'lazada']
    for spam in spam_text:
        if spam in text.lower():
            return True
    return False

def open_comments_popup_for_visible_post(driver, comment_button_selector):
    '''Click the comments button on the currently visible post to open the popup'''
    try:
        # Try strict CSS provided by user first
        buttons = driver.find_elements(By.CSS_SELECTOR, comment_button_selector)
        for btn in buttons:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(btn))
                btn.click()
                # Wait for modal/dialog to appear
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//*[@role='dialog' or @aria-modal='true']"))
                )
                return True
            except Exception:
                continue
        # Fallback: click any button labeled Comment
        try:
            fallback = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@role='button' and .//span[contains(text(),'Comment')]]"))
            )
            fallback.click()
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[@role='dialog' or @aria-modal='true']"))
            )
            return True
        except Exception:
            return False
    except Exception:
        return False

def get_comments_from_popup(driver, modal_root_selector, comments_limit=10, strict_scroll_css=None, strict_comments_css=None):
    '''Within an open comments popup, scroll twice and collect top comments'''
    collected = []
    try:
        # Get modal root; if strict selector fails, fallback to role=dialog
        try:
            modal = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, modal_root_selector))
            )
        except Exception:
            modal = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.XPATH, "//*[@role='dialog' or @aria-modal='true']"))
            )

        # Use strict CSS for scroll container if provided
        if strict_scroll_css:
            try:
                scrollable = modal.find_element(By.CSS_SELECTOR, strict_scroll_css)
            except Exception:
                scrollable = None
        else:
            scrollable = None

        # Find a scrollable container inside the modal (robust to class changes)
        if scrollable is None:
            scrollable = driver.execute_script(
            """
            const root = arguments[0];
            let q = [root];
            while (q.length) {
                const el = q.shift();
                const style = window.getComputedStyle(el);
                const canScroll = el.scrollHeight > el.clientHeight && (style.overflowY === 'auto' || style.overflowY === 'scroll');
                if (canScroll) return el;
                q.push(...el.children);
            }
            return root;
            """,
            modal,
        )

        # Focus the scrollable container and scroll using its own scrollbar
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'nearest'});", scrollable)
            scrollable.click()
        except Exception:
            pass

        # Scroll the container twice: JS + PAGE_DOWN to avoid hitting the input box
        for _ in range(2):
            driver.execute_script(
                "arguments[0].scrollTop = Math.min(arguments[0].scrollTop + arguments[0].clientHeight, arguments[0].scrollHeight);",
                scrollable,
            )
            try:
                scrollable.send_keys(Keys.PAGE_DOWN)
            except Exception:
                pass
            time.sleep(1.2)

        # Collect comment text nodes within modal
        # If strict CSS for comments supplied, try it first
        if strict_comments_css:
            nodes = scrollable.find_elements(By.CSS_SELECTOR, strict_comments_css)
            xpath_sets = []
        else:
            nodes = []
            xpath_sets = [
                ".//div[contains(@class,'x1vvkbs')][not(.//div[@role='button'])]",
                ".//div[contains(@class,'xdj266r') and contains(@class,'xat24cr')]",
                ".//span[contains(@class,'x1vvkbs')]",
            ]
        seen = set()
        if not nodes:
            for xp in xpath_sets:
                nodes.extend(scrollable.find_elements(By.XPATH, xp))
            for el in nodes:
                txt = el.text.strip()
                if not txt or txt.lower() in ("like", "reply", "share", "write a comment", "write a reply"):
                    continue
                if txt in seen:
                    continue
                seen.add(txt)
                collected.append(txt)
                if len(collected) >= comments_limit:
                    return collected
        return collected
    except Exception:
        return collected

def close_comments_popup(driver):
    '''Close the open popup by clicking the X or pressing ESC'''
    try:
        # Try close button
        candidates = [
            (By.XPATH, "//div[@role='dialog']//div[@role='button' and @aria-label='Close']"),
            (By.XPATH, "//div[@role='dialog']//div[@role='button' and .//*[local-name()='svg']]"),
        ]
        for by, sel in candidates:
            try:
                btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
                btn.click()
                return True
            except Exception:
                continue
        # Fallback: ESC
        from selenium.webdriver.common.keys import Keys
        body = driver.find_element(By.TAG_NAME, 'body')
        body.send_keys(Keys.ESCAPE)
        return True
    except Exception:
        return False

def scroll_profile_collect_post_urls(driver, max_posts=10, max_scrolls=40):
    '''On a profile/page feed, scroll and collect up to max_posts post permalinks and snippets.'''
    collected = []
    seen = set()
    scrolls = 0
    while len(collected) < max_posts and scrolls < max_scrolls:
        # Find post articles currently in DOM
        articles = driver.find_elements(By.XPATH, "//div[@role='article']")
        for art in articles:
            try:
                # Find a timestamp/permalink anchor inside the article
                link = None
                for a in art.find_elements(By.XPATH, ".//a[@role='link']"):
                    href = a.get_attribute('href') or ''
                    if any(s in href for s in ['/posts/', '/photos/', 'permalink.php', '/videos/']):
                        link = href
                        break
                if not link:
                    continue
                if link in seen:
                    continue
                seen.add(link)
                # Extract a short text snippet for context
                snippet = ''
                try:
                    tnode = art.find_element(By.XPATH, ".//div[contains(@class,'x1vvkbs') or contains(@class,'xdj266r')]")
                    snippet = (tnode.text or '').strip()
                except Exception:
                    pass
                collected.append({
                    'url': link,
                    'snippet': snippet[:300]
                })
                if len(collected) >= max_posts:
                    break
            except Exception:
                continue
        # Scroll to load more
        driver.execute_script("window.scrollBy(0, 1200);")
        time.sleep(1.2)
        scrolls += 1
    return collected

def find_visible_posts(driver):
    '''Return list of article elements currently in viewport order.'''
    arts = driver.find_elements(By.XPATH, "//div[@role='article']")
    # Keep only visible ones
    visibles = []
    for a in arts:
        try:
            if a.is_displayed():
                rect = a.rect
                if rect.get('height', 0) > 100:
                    visibles.append(a)
        except Exception:
            continue
    return visibles

def click_comments_button_in_article(driver, article):
    '''Click the comments button inside a post.'''
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", article)
        time.sleep(0.6)
        # Prefer explicit Comment button in the action bar
        btn = article.find_element(By.XPATH, ".//div[@role='button' and .//span[contains(text(),'Comment')] and not(@contenteditable='true')]")
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(btn))
        btn.click()
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[@role='dialog' or @aria-modal='true']"))
        )
        return True
    except Exception:
        # Fallback: click the comments count link near the action bar
        try:
            link = article.find_element(By.XPATH, ".//a[contains(@href,'comment') or contains(.,'comments')]")
            link.click()
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[@role='dialog' or @aria-modal='true']"))
            )
            return True
        except Exception:
            return False

def scrape_comments_for_article(driver, article, scroll_times=2, max_comments=10):
    '''Open popup for article, scroll and extract comments, then close.'''
    opened = click_comments_button_in_article(driver, article)
    if not opened:
        return []
    modal_root_selector = "div[role='dialog']"
    comments = get_comments_from_popup(driver, modal_root_selector, comments_limit=max_comments)
    # If not enough, scroll more within the modal
    if len(comments) < max_comments:
        try:
            modal = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, modal_root_selector))
            )
            for _ in range(max(0, scroll_times - 2)):
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollTop + arguments[0].clientHeight;", modal)
                time.sleep(1.0)
                more = get_comments_from_popup(driver, modal_root_selector, comments_limit=max_comments)
                comments = more if len(more) > len(comments) else comments
        except Exception:
            pass
    close_comments_popup(driver)
    return comments[:max_comments]

def get_comments(driver, limit_text=2500):
    '''Get comments under a post and filter spam comments
    Return:  - dataframe of comments: id, text, is_spam, tag_name.
             - number of comments'''
    cnt = 0
    treasured_comments = []
    is_spam = 0
    comments = driver.find_elements(By.XPATH, "//div[contains(@class, 'x1n2onr6 x1swvt13 x1iorvi4 x78zum5 x1q0g3np x1a2a7pz') or contains(@class, 'x1n2onr6 xurb0ha x1iorvi4 x78zum5 x1q0g3np x1a2a7pz')]")
    for comment in comments:
        try:
            # Check if comment contains text
            text_ele = comment.find_element(By.XPATH, ".//div[contains(@class, 'xdj266r x11i5rnm xat24cr x1mh8g0r x1vvkbs')]")
            username = comment.find_element(By.XPATH, ".//span[@class='x3nfvp2']/span")

            if text_ele:
                try:
                    name_tag = text_ele.find_element(By.XPATH, ".//span[@class='xt0psk2']/span")
                    name_tag = name_tag.text
                except:
                    name_tag = None

                # Limit the number of comments  
                cnt += 1
                if cnt > limit_text:
                    break
                text = text_ele.text
                if cnt % 10 == 0:
                    print("Count: ", cnt)

                # Filter spam comments    
                if filter_spam(text):
                    is_spam = 1
                else:
                    is_spam = 0
                treasured_comments.append({
                    "id" : cnt,
                    "username": username.text,
                    "text": text,
                    'tag_name': name_tag,
                    'is_spam': is_spam
                })
        except Exception as e:
            continue
    print("Crawl successfully!!! \nTotal Comments: ", cnt)
    return treasured_comments, cnt

def get_url():
    '''Get the URL of a Facebook post from the user input'''
    #get url from input
    url = input("Enter the URL: ")
    return url


def save_to_csv(df, file_name):
    '''Save the dataframe to a CSV file'''
    df.to_csv(file_name, index=False)
