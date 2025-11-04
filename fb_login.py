import time
import pickle
import random
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# ===== CONFIG =====
FB_EMAIL = "shashwatsaxena1980@gmail.com"       # <-- Put your Facebook email here
FB_PASSWORD = "Ravi@123"    # <-- Put your Facebook password here

COOKIES_FILE = Path("cookies.pkl")
HEADLESS = False


# ===== DRIVER CREATION =====
def create_driver(headless: bool = HEADLESS):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
        """
    })
    return driver


# ===== COOKIE HELPERS =====
def save_cookies(driver, path: Path = COOKIES_FILE):
    with open(path, "wb") as f:
        pickle.dump(driver.get_cookies(), f)
    print(f"[+] Saved {len(driver.get_cookies())} cookies to {path}")


def load_cookies(driver, path: Path = COOKIES_FILE):
    if not path.exists():
        return False
    try:
        cookies = pickle.load(open(path, "rb"))
    except Exception as e:
        print("[-] Failed to read cookies:", e)
        return False

    driver.get("https://www.facebook.com/")
    time.sleep(2)
    for c in cookies:
        try:
            driver.add_cookie(c)
        except Exception:
            continue
    driver.refresh()
    time.sleep(3)
    print(f"[+] Loaded cookies from {path}")
    return True


# ===== HUMAN-LIKE TYPING =====
def type_like_human(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.08, 0.25))


# ===== LOGIN DETECTION =====
def wait_for_login(driver, timeout=60):
    """
    Waits until login is confirmed by checking:
    - URL (should contain 'facebook.com/?sk=' or '/home.php')
    - Key elements that appear after login
    """
    print("[*] Waiting for login confirmation...")
    end_time = time.time() + timeout

    selectors = [
        "div[role='feed']",
        "div[data-pagelet='Feed']",
        "div[data-pagelet='Root']",
        "a[aria-label='Home']",
        "svg[aria-label='Facebook']"
    ]

    while time.time() < end_time:
        current_url = driver.current_url
        if "facebook.com/?sk=" in current_url or "home.php" in current_url:
            print("[+] Login detected via URL redirect.")
            return True

        for sel in selectors:
            try:
                if driver.find_element(By.CSS_SELECTOR, sel):
                    print(f"[+] Login detected via selector: {sel}")
                    return True
            except Exception:
                continue

        time.sleep(2)

    print("[-] Login detection timeout reached.")
    return False


# ===== MAIN LOGIN =====
def main():
    driver = create_driver()
    wait = WebDriverWait(driver, 30)

    print("[*] Opening Facebook...")
    driver.get("https://www.facebook.com/")
    time.sleep(2)

    # Try cookies first
    if COOKIES_FILE.exists():
        print("[*] Attempting to load saved cookies...")
        if load_cookies(driver):
            if wait_for_login(driver, timeout=30):
                print("[+] Logged in via cookies.")
                return driver
            else:
                print("[-] Cookies expired or not valid anymore.")

    # Login manually
    print("[*] Logging in with credentials...")
    driver.get("https://www.facebook.com/login")
    wait.until(EC.presence_of_element_located((By.NAME, "email")))

    email_field = driver.find_element(By.NAME, "email")
    pass_field = driver.find_element(By.NAME, "pass")

    print("[*] Typing email...")
    type_like_human(email_field, FB_EMAIL)
    time.sleep(random.uniform(0.5, 1.0))

    print("[*] Typing password...")
    type_like_human(pass_field, FB_PASSWORD)
    time.sleep(random.uniform(0.5, 1.0))

    driver.find_element(By.NAME, "login").click()
    print("[*] Submitted login form, waiting for home feed...")

    # Wait until logged in
    if wait_for_login(driver, timeout=90):
        print("[+] Login successful.")
        save_cookies(driver)
        return driver
    else:
        print("[-] Could not detect successful login. Manual check may be required.")
        driver.quit()
        raise RuntimeError("Login failed.")


if __name__ == "__main__":
    driver = main()
    print("[+] Driver ready for scraping.")
