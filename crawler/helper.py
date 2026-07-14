import os
import re

import requests
from difflib import SequenceMatcher
from functools import partial
from flask import flash
from dotenv import load_dotenv

# importing functions that handle crawling
from crawler.deep_crawling import get_links_using_bfs, scrape_markup_simple, get_links_using_prefetch_mode, extract_product

load_dotenv()

# Helper function to check the validity of the URL, using regular expression
def is_valid_url(url):
    # Regex for a valid URL
    # ^ start anchor
    # https?:// means either http or https
    # (www\.)? means www. is optional 
    # [a-zA-Z0-9.-]+ means accept english letters, numbers, dots and hyphens. Atleast one character should be present
    # \.[a-zA-Z]{2,} means a atleast 2 letters followed by . (ex: .com, .org, .au, .uk, .in)
    # (/.*)? includes sub-directories 
    # $ ending point. no characters or spaces allowed after this point.
    regex = r"^https?://(www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/.*)?$"
    # if the inputted url passed the reg ex, .match() returns the URL if not returns None
    return re.match(regex, url) is not None

# helper function to check the valid range of max_pages and max_depth
def is_valid_range(num, max=5):
    if 1 <= num <= max:
        return num
    return None

async def prefetch_links(url):
    return await get_links_using_prefetch_mode(url)

async def bfs(url, max_depth, max_pages):
    # function returns all the internal links & their depth in the given URL 
    return await get_links_using_bfs(url, max_depth, max_pages)

async def scrape_html(url):
    # function returns the scraped HTML markup
    return await scrape_markup_simple(url)

async def scrape_product(url):
    # function returns the scraped HTML markup
    return await extract_product(url)


def find_website(db, website_id):
    row = db.execute("""
        SELECT * FROM website
        WHERE website_id = ?
    """,
    (website_id,)
    ).fetchone()

    if row and row['website_id']:
        return True
    
    return False
    


# same product = similar name + similar brand + close price
# normalizes a string
def normalize_text(value):
    # "Corsair-Vengeance RAM!" -> "corsair vengeance ram!"
    value = (value or '').lower()

    # Replaces anything that is not a lowercase letter or number with a space. also removes extra spaces at the start/end.
    # "corsair-vengeance_8gb!!!" -> "corsair vengeance 8gb"
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()

# Compares two normalized strings and returns a score from 0.0 to 1.0.
# similarity("Corsair RAM 8GB", "corsair ram 8 gb")
# Might return something high like 0.9.
# if similarity(name1, name2) >= 0.92: -> probably same product
def similarity(a, b):
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


# Turns messy price strings into floats.
# "₹4,999" -> 4999.0
# "Rs. 12,500.00" -> 12500.0
# None -> None
def normalize_price(value):
    if value is None:
        return None
    cleaned = re.sub(r'[^0-9.]', '', str(value))
    return float(cleaned) if cleaned else None


# Checks if two prices are close enough. 0.03 means 3%.
# price_close("₹10,000", "₹10,100")
# Difference is 1%, so returns True.
def price_close(a, b, tolerance=0.02):
    a = normalize_price(a)
    b = normalize_price(b)
    if a is None or b is None:
        return True
    # does the percentage check:
    return abs(a - b) / max(a, b) <= tolerance


def is_duplicated_product(db, website_id, resp):
    product_code = (resp.get('product_code') or '').strip()

    if product_code:
        row = db.execute("""
            SELECT item_id
            FROM item
            WHERE website_id = ? AND lower(product_code) = lower(?)
            """,
            (website_id, product_code)
        ).fetchone()

        if row:
            return True
        
    existing = db.execute(
        """
        SELECT item_id, name, brand, price
        FROM item
        WHERE website_id = ?
        """,
        (website_id,)
    ).fetchall()

    for item in existing:
        name_score = similarity(resp.get('name'), item['name'])
        brand_score = similarity(resp.get('brand'), item['brand'])

        if (
            name_score >= 0.92
            and brand_score >= 0.85
            and price_close(resp.get('price'), item['price'])
        ):
            return True
        



def call_firecrawl_map(url):
    payload = {
        "url": url,
        "sitemap": "skip",
        "includeSubdomains": True,
        "ignoreQueryParameters": True,
        "ignoreCache": True,
        "limit": 5000,
        "location": {
            "country": os.environ.get('COUNTRY', 'IN'),
            "languages": [os.environ.get('LOACALE', 'en-IN')]
        },
        "timeout": int(os.environ.get('TIMEOUT', "6000"))
    }
    if 'FIRECRAWL_TOKEN' not in os.environ:
        raise ValueError('Missing required environment variable: FIRECRAWL_TOKEN')

    headers = {
        "Authorization": f"Bearer {os.environ['FIRECRAWL_TOKEN']}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        os.environ.get('FIRECRAWL_MAP_API', 'https://api.firecrawl.dev/v2/map'),
        json=payload,
        headers=headers,
        timeout=70
    )
    # Throws an HTTPError if the status code is 4xx or 5xx
    response.raise_for_status()
    
    data = response.json()

    if not data.get("success"):
        raise RuntimeError(data)
    
    return data.get("links", [])

def create_website(db, url, job_id, max_depth=None, max_pages=None):
    cur = db.execute(
        'INSERT INTO website (website_url, job_id, max_depth, max_pages) VALUES (?, ?, ?, ?)',
        (url, job_id, max_depth, max_pages)
    )

    return cur.lastrowid

def create_markup(db, job_id, url_id=None, website_id=None):
    cur = db.execute(
        'INSERT INTO markup (url_id, job_id, website_id) VALUES (?, ?, ?)',
        (url_id, job_id, website_id)
    )

    return cur.lastrowid

def create_crawl_job(db, job_type):
    cur = db.execute(
        """
        INSERT INTO crawl_job (job_type, job_status)
        VALUES (?,?)
        """,
        (job_type, 'PENDING')
    )
    return cur.lastrowid


def mark_crawl_job_started(db, task_id, job_id):
    status = os.environ.get('CODE_STARTED', 'STARTED')
    db.execute(
        """
        UPDATE crawl_job
        SET job_status = ?, task_id = ?, started_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
        """,
        (status, task_id, job_id)
    )
    db.commit()


def mark_crawl_job_success(db, job_id):
    status = os.environ.get('CODE_SUCCESS', 'SUCCESS')
    db.execute(
        """
        UPDATE crawl_job
        SET job_status = ?, finished_at = CURRENT_TIMESTAMP
        WHERE job_id = ?
        """,
        (status, job_id)
    )
    db.commit()

def mark_crawl_job_failure(db, error_message, job_id):
    status = os.environ.get('CODE_FAILURE', 'FAILURE')
    db.execute(
    """
    UPDATE crawl_job
    SET job_status = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
    WHERE job_id = ?
    """,
    (status, error_message, job_id)
    )
    db.commit()

def assign_celery_task_id_to_crawl_job(db, task_id, job_id):
    db.execute(
        """
        UPDATE crawl_job
        SET task_id = ?
        WHERE job_id = ?
        """,
        (task_id, job_id)
    )
    db.commit()

flash_success_alert = partial(flash, category='success')

flash_info_alert = partial(flash, category='info')

flash_error_alert = partial(flash, category='error')


class UrlError(Exception):
    def __init__(self, log_message='Invalid URL'):
        super().__init__(log_message) # passing the log message to base Exception class
        self.log_message = log_message

class MaxDepthError(Exception):
    def __init__(self, log_message='Max Depth should be a number between [1,5]'):
        super().__init__(log_message) # passing the log message to base Exception class
        self.log_message = log_message

class MaxPagesError(Exception):
    def __init__(self, log_message='Max Pages should be a number between [1,100]'):
        super().__init__(log_message) # passing the log message to base Exception class
        self.log_message = log_message

class CRAWL_FAILED(Exception):
    def __init__(self, error_code='CRAWLING_FAILURE', log_message='Crawling pipeline failure'):
        super().__init__(log_message) # passing the log message to base Exception class
        self.error_code = error_code
        self.log_message = log_message

class NO_HTML(Exception):
    def __init__(self, error_code='NO_HTML_FAILURE', log_message='Crawler returned no/empty HTML'):
        super().__init__(log_message) # passing the log message to the base Exception class
        self.error_code = error_code
        self.log_message = log_message

class HTML_404(Exception):
    def __init__(self, error_code='404_FAILURE', log_message='Page is not found'):
        super().__init__(log_message) # passing the log message to the base Exception class
        self.error_code = error_code
        self.log_message = log_message

class ANTI_BOT_403(Exception):
    def __init__(self, error_code='403_FAILURE', log_message='Page seems blocked'):
        super().__init__(log_message) # passing the log message to the base Exception class
        self.error_code = error_code
        self.log_message = log_message

class ERROR_CODE_202(Exception):
    def __init__(self, error_code='202_FAILURE', log_message='Incomplete request'):
        super().__init__(log_message) # passing the log message to the base Exception class
        self.error_code = error_code
        self.log_message = log_message

class ERROR_CODE_429(Exception):
    def __init__(self, error_code='429_FAILURE', log_message='Overwhelmed server'):
        super().__init__(log_message) # passing the log message to the base Exception class
        self.error_code = error_code
        self.log_message = log_message

class ERROR_CODE_400(Exception):
    def __init__(self, error_code='400_BAD_INPUT', log_message='Bad input provided'):
        super().__init__(log_message) # passing the log message to the base Exception class
        self.error_code = error_code
        self.log_message = log_message

def data_sanity_checks(url='', max_pages=10, max_depth=5):
    error = None
    # simple data sanity checks before moving forward
    try:  
        # verify the format of the url before sending it to crawl4ai
        valid_url = url.strip() if is_valid_url(url) else None

        if not valid_url:
            raise UrlError

        # performing type conversion
        # by default strings are passed
        raw_max_pages = int(max_pages)
        raw_max_depth = int(max_depth)

        # check for the valid range of max_pages and max_depth
        valid_max_pages = is_valid_range(raw_max_pages, max=100)
        valid_max_depth = is_valid_range(raw_max_depth)

        if not valid_max_depth:
            raise MaxDepthError
        elif not valid_max_pages:
            raise MaxPagesError

    except (ValueError, TypeError) as e:
        # couldn't convert the input to an integer
        error = "Max Pages & Max Depth should only be numbers"
    except (MaxPagesError, MaxDepthError) as e:
        error = e.log_message
    except UrlError as e:
        error = f"{e.log_message}: {url}"
    except Exception:
        error = "Misc Error"
    
    return error


def check_url(url):
    error = None
    try:
        valid_url = url.strip() if is_valid_url(url) else None
        if not valid_url:
            raise UrlError
    except UrlError:
        error = "Invalid URL Entered"
    except Exception:
        error = "Misc Error"
    return error
        