import os
import re

import requests
from functools import partial
from flask import flash
from dotenv import load_dotenv
from bs4 import BeautifulSoup


# importing functions that handle crawling
from crawler.deep_crawling import get_links_using_bfs, scrape_content, get_links_using_prefetch_mode
from crawler.audit import scrape_html_bulk

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

async def crawl_bulk(urls):
    return await scrape_html_bulk(urls)

async def prefetch_links(url):
    return await get_links_using_prefetch_mode(url)

async def bfs(url):
    # function returns all the internal links & their depth in the given URL 
    return await get_links_using_bfs(url)

async def scrape_html(url):
    # function returns the scraped HTML markup
    return await scrape_content(url)

def call_firecrawl_map(url):
    payload = {
        "url": url,
        "sitemap": "skip",
        "includeSubdomains": True,
        "ignoreQueryParameters": True,
        "ignoreCache": True,
        "limit": 5000,
        "location": {
            "country": os.environ.get('COUNTRY', 'IND'),
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

def create_website(db, url, job_id):
    cur = db.execute(
        'INSERT INTO website (website_url, job_id) VALUES (?, ?)',
        (url, job_id)
    )

    return cur.lastrowid

def create_markup(db, url_id, job_id):
    cur = db.execute(
        'INSERT INTO markup (url_id, job_id) VALUES (?, ?)',
        (url_id, job_id)
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

def create_url_address(db, url, job_id):
    cur = db.execute(
        """
        INSERT INTO internal_url (url_address, job_id)
        VALUES (?,?)
        """,
        (url, job_id)
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


def save_html_tags(db, html, url_id):
    soup = BeautifulSoup(html, 'html.parser')

    title = []
    headings1 = []
    headings2 = []
    alt = []

    for tag in soup.find_all(['title', 'h1', 'h2', 'img']):
        if tag.name == 'title':
            title.append((str(tag), url_id))
        elif tag.name == 'h1':
            headings1.append((str(tag), url_id))
        elif tag.name == 'h2':
            headings2.append((str(tag), url_id))
        elif tag.name == 'img':
            if tag.has_attr('alt'):
                alt.append((tag['alt'], str(tag), url_id))
            else:
                alt.append((None, str(tag), url_id))
    
    db.executemany(
        """
        INSERT INTO title_tag (title, url_id)
        VALUES (?,?)
        """,
        title
    )
    db.executemany(
        """
        INSERT INTO h1_tag (h1, url_id)
        VALUES (?,?)
        """,
        headings1
    )
    db.executemany(
        """
        INSERT INTO h2_tag (h2, url_id)
        VALUES (?,?)
        """,
        headings2
    )
    db.executemany(
        """
        INSERT INTO img_alt_tag (alt_text, img_tag, url_id)
        VALUES (?,?,?)
        """,
        alt
    )

    title.clear()
    headings1.clear()
    headings2.clear()
    alt.clear()