
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager



def login_facebook(username, password, driver):
    '''Log in to Facebook'''

    try:
        # Wait 10s until the login form is loaded
        username_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.NAME, "email")))
        username_field.send_keys(username)

        password_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.NAME, "pass")))
        password_field.send_keys(password)

        # Submit log in form 
        password_field.send_keys(Keys.RETURN)

    except Exception as e:
        print("Logged in failed. \n")

    finally:
        print("Logged in successfully")
        
def configure_driver():
    '''Configure the webdriver'''

    chrome_options = Options()
    # Turn off Chrome notification and set language to English
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_experimental_option('prefs', {'intl.accept_languages': 'en,en_US'})

    # Prefer Selenium Manager to auto-resolve the correct ChromeDriver
    # This avoids binary incompatibility issues on Windows
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def set_up_driver(url, service):
    '''Set up the driver and get url'''
    driver = configure_driver()

    # get url
    driver.get(url)
    return driver

