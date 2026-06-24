import os
import re
from functools import partial
from flask import flash
from dotenv import load_dotenv
import requests

# importing functions that handle crawling
from crawler.deep_crawling import _get_links_using_bfs, _scrape_content

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



async def bfs(url):
    # function returns all the internal links & their depth in the given URL 
    dedup_links = await _get_links_using_bfs(url)

    return dedup_links

async def scrape_html(url):
    # function returns the scraped HTML markup
    html = await _scrape_content(url)

    return html

def call_firecrawl_map(url):
    payload = {
        "url": url,
        "sitemap": "skip",
        "includeSubdomains": True,
        "ignoreQueryParameters": True,
        "ignoreCache": True,
        "limit": 5000,
        "location": {
            "country": os.environ.get('COUNTRY', 'US'),
            "languages": ["en-US"]
        },
        "timeout": int(os.environ.get('TIMEOUT', "6000"))
    }
    print(payload)

    headers = {
        "Authorization": f"Bearer {os.environ['FIRECRAWL_API']}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        os.environ['FIRECRAWL_MAP_API'],
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


_flash_success_alert = partial(flash, category='success')

_flash_info_alert = partial(flash, category='info')

_flash_error_alert = partial(flash, category='error')


class UrlError(Exception):
    pass

class MaxDepthError(Exception):
    pass

class MaxPagesError(Exception):
    pass

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

    except (ValueError, TypeError):
        # couldn't convert the input to an integer
        error = "Max Pages & Max Depth should only be numbers"
    except MaxPagesError:
        error = "Max Pages should be a number between [1,100]"
    except MaxDepthError:
        error = "Max Depth should be a number between [1,5]"
    except UrlError:
        error = f"Url {url} is invalid"
    except Exception:
        error = "Misc Error"
    
    return error