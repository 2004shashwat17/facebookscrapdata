import configuration as cf
import pandas as pd
import numpy as np
import json

from selenium.webdriver.common.by import By

import time
from io import StringIO
import os




def crawl(driver, url, username, password, threshold, ite):

    driver.get(url)
    # Login Facebook
    cf.login_facebook(username, password, driver)
    if cf.scroll_and_click_button(driver):
      cf.click_showed_type_btn(driver, "All comments")

      #Show more comments
      try:
        cf.show_more_comments1(driver, 100)
      except:
        print('No more cmt')

      # Scroll to top
      driver.find_element(By.TAG_NAME, 'body').send_keys(cf.Keys.CONTROL + cf.Keys.HOME)

      # Show comment and scroll step by step
      driver.execute_script("window.scrollTo(0, 700);") #cuộn
      driver.execute_script("window.scrollTo(0, 700);")  #cuộn

      # Sleep 5s
      time.sleep(5)

      # Scroll để các button visible and show replies
      driver.execute_script("window.scrollTo(0, 900);")

      #Show replies
      try:
        cf.show_all_replies(driver, threshold, ite)
      except Exception as e:
        print('Replies are limited', e)
        pass

      #driver.minimize_window()
      #driver.maximize_window()

      # Get comments
      cmts, cnt = cf.get_comments(driver, 2500)

      return cmts, cnt
    else:
      print("No comment found!")
      return None

def crawl_page_top_comments(driver, page_url, username, password, comments_per_post=10, posts_to_visit=1):
    '''Open a page, iterate posts, open popup, scroll twice, scrape top comments, close popup'''
    from configuration.action import open_comments_popup_for_visible_post, get_comments_from_popup, close_comments_popup

    driver.get(page_url)
    cf.login_facebook(username, password, driver)

    results = []
    visited = 0
    while visited < posts_to_visit:
        # Scroll a bit to bring next post into view
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(1)

        # Open popup using provided selector from user
        comment_btn_selector = "#_r_jr_ > div > div:nth-child(2) >  i"
        opened = open_comments_popup_for_visible_post(driver, comment_btn_selector)
        if not opened:
            # If cannot open, continue scrolling
            continue

        # Strict modal root selector provided by user (fallbacks inside helper)
        modal_root_selector = "#mount_0_0_U3 > div > div:nth-child(1) > div > div:nth-child(5) > div > div.__fb-light-mode.x1n2onr6.xzkaem6 > div.x9f619.x1n2onr6.x1ja2u2z > div > div.x1uvtmcs.x4k7w5x.x1h91t0o.x1beo9mf.xaigb6o.x12ejxvf.x3igimt.xarpa2k.xedcshv.x1lytzrv.x1t2pt76.x7ja8zs.x1n2onr6.x1qrby5j.x1jfb8zj > div > div > div > div > div > div"
        # Strict CSS selectors provided by user (session-dependent; used first)
        strict_scroll_css = "div.x14nfmen.x1s85apg.x5yr21d.xtijo5x.xg01cxk.x10l6tqk.x13vifvy.x1wsgiic.x19991ni.xwji4o3.x1kky2od.x1sd63oq"
        strict_comments_css = None
        comments = get_comments_from_popup(
            driver,
            modal_root_selector,
            comments_limit=comments_per_post,
            strict_scroll_css=strict_scroll_css,
            strict_comments_css=strict_comments_css,
        )
        for text in comments:
            results.append({"text": text})

        close_comments_popup(driver)
        visited += 1

    return results

def crawl_profile_top_posts(driver, profile_url, username, password, max_posts=10):
    '''Open a profile/page and collect top post permalinks and snippets.'''
    from configuration.action import scroll_profile_collect_post_urls
    driver.get(profile_url)
    cf.login_facebook(username, password, driver)
    posts = scroll_profile_collect_post_urls(driver, max_posts=max_posts)
    return posts

def crawl_profile_posts_comments(driver, profile_url, username, password, posts_to_visit=10, comments_per_post=10, popup_scrolls=2):
    '''Profile flow: scroll to gather posts, then for each post open comments popup, scroll, extract.'''
    from configuration.action import find_visible_posts, scrape_comments_for_article

    driver.get(profile_url)
    cf.login_facebook(username, password, driver)

    gathered = []
    visited = 0
    # Keep scrolling profile and process posts as they appear
    while visited < posts_to_visit:
        posts = find_visible_posts(driver)
        if not posts:
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(1)
            continue
        for art in posts:
            if visited >= posts_to_visit:
                break
            comments = scrape_comments_for_article(driver, art, scroll_times=popup_scrolls, max_comments=comments_per_post)
            for text in comments:
                gathered.append({"post_index": visited + 1, "text": text})
            visited += 1
        driver.execute_script("window.scrollBy(0, 1200);")
        time.sleep(1)
    return gathered

if __name__ == '__main__':

    cnt = 0
    threshold = 60 #Base on the Internet speed (300 - 400)
    ite = 20 # Use to check whether it reaches the end of the page (Should be 20 - 30)

    # Login info (env overrides, fallback to empty -> Facebook login page will show fields)
    username = os.environ.get("FACEBOOK_USERNAME", "")
    password = os.environ.get("FACEBOOK_PASSWORD", "")

    # Post URL or Page/Profile URL from env or prompt
    page_url = os.environ.get("FACEBOOK_PAGE_URL")
    post_url = os.environ.get("FACEBOOK_POST_URL")
    profile_url = os.environ.get("FACEBOOK_PROFILE_URL")
    driver = cf.configure_driver()
    # starter = 0
    # limit = 10

    if profile_url:
        # Full comments-per-post flow on profile
        data = crawl_profile_posts_comments(driver, profile_url, username, password, posts_to_visit=10, comments_per_post=10, popup_scrolls=2)
    elif page_url:
        data = crawl_page_top_comments(driver, page_url, username, password, comments_per_post=10, posts_to_visit=3)
    else:
        url = post_url or cf.get_url()
        data, _ = crawl(driver, url, username, password, threshold, ite)
    cmt_data_json = json.dumps(data, ensure_ascii=False)
    cmts = pd.read_json(StringIO(cmt_data_json), orient='records')

    # Save to project-local CSV
    output_path = os.path.join(os.path.dirname(__file__), 'posts.csv' if profile_url else 'comments.csv')
    cf.save_to_csv(cmts, output_path)
    time.sleep(50)
    driver.quit()