import os
import re
import json

from flask import jsonify


import requests
from openai import OpenAI
from difflib import SequenceMatcher
from functools import partial
from flask import flash
from dotenv import load_dotenv

# importing functions that handle crawling
from crawler.deep_crawling import get_links_using_bfs, scrape_markup

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


async def bfs(url, max_depth, max_pages):
    # function returns all the internal links & their depth in the given URL 
    return await get_links_using_bfs(url, max_depth, max_pages)

async def scrape_html(urls):
    # function returns the scraped HTML markup
    return await scrape_markup(urls)


def find_website(db, website_id):
    row = db.execute("""
        SELECT * FROM website
        WHERE website_id = ?
    """,
    (website_id,)
    ).fetchone()

    if row:
        return True
    
    return False

def find_internal_url(db, url_id):
    row = db.execute("""
        SELECT * FROM internal_url
        WHERE url_id = ?
    """,
    (url_id,)
    ).fetchone()

    return row


# same product = similar name + similar brand + close price
# normalizes a string
def normalize_text(value):
    # "Corsair-Vengeance RAM!" -> "corsair vengeance ram!"
    value = (value or '').lower()

    # Replaces anything that is not a lowercase letter or number with a space. also removes extra spaces at the start/end.
    # "corsair-vengeance_8gb!!!" -> "corsair vengeance 8gb"
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()


def normalize_product_code(value):
    return re.sub(r'[^a-z0-9]+', '', (value or '').lower())


def has_meaningful_product_code(value):
    normalized = normalize_text(value)
    return bool(normalized) and normalized not in {
        'na',
        'n a',
        'none',
        'null',
        'not available'
    }

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


def price_candidate_key(value):
    price = normalize_price(value)
    if price is None:
        return None
    return int(price) if price.is_integer() else price


# Checks if two prices are close enough. 0.03 means 3%.
# price_close("₹10,000", "₹10,100")
# Difference is 1%, so returns True.
def price_close(a, b, tolerance=0.02):
    a = normalize_price(a)
    b = normalize_price(b)
    if a is None or b is None:
        return True
    if a == b:
        return True
    if max(a, b) == 0:
        return False
    # does the percentage check:
    return abs(a - b) / max(a, b) <= tolerance


# fuzzy duplicate names/brands/prices.
def find_duplicate_product(db, website_id, product):
    # First try the strongest duplicate signal: product code/SKU.
    # We normalize punctuation so values like "KF432S20IB/32" and
    # "KF432S20IB-32" are treated as the same product code.
    product_code = normalize_product_code(product.get('product_code'))

    if product_code and has_meaningful_product_code(product.get('product_code')):
        row = db.execute("""
            SELECT item_id, product_code
            FROM item
            WHERE website_id = ?
              AND replace(replace(replace(lower(product_code), '/', ''), '-', ''), ' ', '') = ?
            """,
            (website_id, product_code)
        ).fetchone()

        if row:
            return {
                "item_id": row["item_id"],
                "similarity_score": 1.0,
                "reason": "product_code"
            }
        
    # If product code is missing or not useful, fall back to fuzzy matching
    # against products already saved for the same website.
    existing = db.execute(
        """
        SELECT item_id, name, brand, price
        FROM item
        WHERE website_id = ?
        """,
        (website_id,)
    ).fetchall()

    best_duplicate = None

    for item in existing:
        # SequenceMatcher returns a score from 0.0 to 1.0. Higher means the
        # text is more similar after normalization.
        name_score = similarity(product.get('name'), item['name'])
        brand_score = similarity(product.get('brand'), item['brand'])

        if (
            name_score >= 0.88
            and brand_score >= 0.85
            and price_close(product.get('price'), item['price'])
        ):
            # Build one combined score so duplicate_item can store how close
            # this incoming product was to the saved item.
            score = round((name_score * 0.75) + (brand_score * 0.25), 4)

            if best_duplicate is None or score > best_duplicate['similarity_score']:
                best_duplicate = {
                    "item_id": item["item_id"],
                    "similarity_score": score,
                    "reason": "name_brand_price"
                }

    if best_duplicate:
        return best_duplicate

    return None

def save_item(db, product, record, job_id):
    # Save a unique product into item. The record argument is the internal_url
    # row, so it gives us website_id and url_id for source tracking.
    cur = db.execute(
        """
        INSERT INTO item (
            job_id, url_id, website_id, name, description,
            price, brand, product_code, availability
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            record['url_id'],
            record['website_id'],
            product.get('name'),
            product.get('short_description'),
            product.get('price'),
            product.get('brand'),
            product.get('product_code'),
            product.get('availability'),
        )
    )

    item_id = cur.lastrowid

    # Specs are stored in a separate table because a product can have many
    # specification rows.
    specs = product.get('specs') or []

    rows = [
        (item_id, spec.get('category'), spec.get('value'))
        for spec in specs
        if spec.get('category') or spec.get('value')
    ]

    if rows:
        db.executemany(
            """
            INSERT INTO specification (
                item_id, category_name, category_value
            )
            VALUES (?, ?, ?)
            """,
            rows
        )

    return item_id

def save_duplicate_item(db, product, duplicate, record, job_id):
    # Save skipped duplicate products separately. This keeps item clean while
    # still preserving evidence of what the extractor found.
    db.execute(
        """
        INSERT INTO duplicate_item (
            job_id, url_id, website_id, similar_to_item_id,
            name, product_code, price, brand, similarity_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            record['url_id'],
            record['website_id'],
            duplicate['item_id'],
            product.get('name'),
            product.get('product_code'),
            product.get('price'),
            product.get('brand'),
            duplicate['similarity_score'],
        )
    )


def extract_price_candidates(markdown):
    # The LLM is allowed to describe products, but prices should be verified
    # against text that actually appeared in the scraped markdown.
    text = markdown or ''
    pattern = r'(?:₹\s?\d[\d,]*(?:\.\d{1,2})?|Rs\.?\s?\d[\d,]*(?:\.\d{1,2})?|INR\s?\d[\d,]*(?:\.\d{1,2})?)'
    candidates = []
    seen = set()

    for match in re.findall(pattern, text, flags=re.IGNORECASE):
        key = price_candidate_key(match)

        if key is None or key == 0 or key in seen:
            continue

        seen.add(key)
        candidates.append(match.strip())

    return candidates


def extract_product_code_candidates(markdown):
    # This is a lightweight candidate collector. The LLM may still extract the
    # final product_code, but candidates make later validation/debugging easier.
    text = markdown or ''
    patterns = [
        r'(?:sku|model|model no|model number|product code|part no|part number)\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9/_ .-]{2,40})',
    ]
    candidates = []
    seen = set()

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = match.strip().strip('.,;|')
            key = normalize_product_code(value)

            if not key or key in seen:
                continue

            seen.add(key)
            candidates.append(value)

    return candidates


def extract_availability_candidates(markdown):
    # Availability text varies a lot by website, so this intentionally starts
    # with common ecommerce phrases and can be expanded over time.
    text = markdown or ''
    candidates = []

    availability_patterns = [
        r'\bIn Stock\b',
        r'\bOut of Stock\b',
        r'\bAvailable\b',
        r'\bUnavailable\b',
        r'\bSold Out\b',
        r'\bHurry,\s*Only\s+\d+\s+left\b',
    ]

    for pattern in availability_patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = match.strip()
            if value.lower() not in [candidate.lower() for candidate in candidates]:
                candidates.append(value)

    return candidates


def clean_product(product):
    # Normalize the LLM output to the exact shape expected by the database
    # saving functions. This protects the rest of the pipeline from missing
    # keys like "product code" vs "product_code".
    specs = product.get('specs') or []

    return {
        "name": (product.get('name') or '').strip(),
        "short_description": (product.get('short_description') or product.get('description') or '').strip(),
        "price": (product.get('price') or '').strip(),
        "brand": (product.get('brand') or '').strip(),
        "product_code": (product.get('product_code') or product.get('product code') or '').strip(),
        "availability": (product.get('availability') or '').strip(),
        "specs": [
            {
                "category": (spec.get('category') or '').strip(),
                "value": (spec.get('value') or '').strip()
            }
            for spec in specs
            if isinstance(spec, dict) and (spec.get('category') or spec.get('value'))
        ]
    }


def get_openai_model_name():
    # Crawl4AI/litellm style model names can look like "openai/gpt-...".
    # The official OpenAI client expects only the model id after "openai/".
    model = os.environ.get('OPEN_AI_MODEL', '').strip()

    if model.startswith('openai/'):
        return model.split('/', 1)[1]

    return model


def parse_llm_json(content):
    # Be tolerant of model responses wrapped in markdown code fences, then
    # normalize either {"products": [...]}, {"product": {...}}, a single object,
    # or a raw list into one product list.
    content = (content or '').strip()

    if content.startswith('```'):
        content = re.sub(r'^```(?:json)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content)

    data = json.loads(content)

    if isinstance(data, dict):
        if isinstance(data.get('products'), list):
            return data['products']
        if isinstance(data.get('product'), dict):
            return [data['product']]
        return [data]

    if isinstance(data, list):
        return data

    return []


def ask_llm_for_products(markdown):
    # This is the only LLM call in the saved-markdown extraction path.
    # The prompt asks for JSON only and tells the model not to invent exact
    # factual fields such as price, product code, availability, brand, or specs.
    api_key = os.environ.get('OPEN_AI_KEY')
    model = get_openai_model_name()

    if not api_key:
        raise CRAWL_FAILED(log_message="OPEN_AI_KEY is missing.")

    if not model:
        raise CRAWL_FAILED(log_message="OPEN_AI_MODEL is missing.")

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract structured product data from ecommerce markdown. "
                    "Use only the provided markdown. Do not invent prices, product codes, "
                    "availability, brands, or specs. Return valid JSON only."
                )
            },
            {
                "role": "user",
                "content": (
                    "Extract the main product or products from this markdown. "
                    "Return JSON in this exact shape: "
                    "{\"products\":[{\"name\":\"\",\"short_description\":\"\",\"price\":\"\","
                    "\"brand\":\"\",\"product_code\":\"\",\"availability\":\"\","
                    "\"specs\":[{\"category\":\"\",\"value\":\"\"}]}]}. "
                    "If a field is missing, use an empty string. "
                    "short_description must be under 100 words.\n\n"
                    f"MARKDOWN:\n{markdown[:18000]}"
                )
            }
        ]
    )

    content = response.choices[0].message.content
    products = parse_llm_json(content)

    return [
        clean_product(product)
        for product in products
        if isinstance(product, dict) and product.get('name')
    ]


def validate_product(product, candidates):
    # Validation happens after the LLM response. This is where we keep useful
    # descriptive fields but reject high-risk factual values that are unsupported
    # by the scraped markdown.
    product = clean_product(product)

    price = product.get('price')
    price_key = price_candidate_key(price)
    candidate_keys = {
        price_candidate_key(candidate)
        for candidate in candidates.get('prices', [])
    }

    # Prices are high-risk LLM fields. Keep the LLM price only when the same
    # numeric value appears in the saved markdown price candidates.
    if price_key is None or price_key not in candidate_keys:
        product['price'] = ''

    if not has_meaningful_product_code(product.get('product_code')):
        product['product_code'] = ''

    return product


def product_identity_key(product):
    # Used only for de-duping multiple products returned by the same LLM call.
    # Product code is preferred; otherwise fall back to brand + name.
    code = normalize_product_code(product.get('product_code'))

    if code and has_meaningful_product_code(product.get('product_code')):
        return f"code:{code}"

    return f"name:{normalize_text(product.get('brand'))}:{normalize_text(product.get('name'))}"


def product_quality_score(product):
    # If the LLM returns several versions of the same product, keep the most
    # complete one. Price and product code are weighted higher than description.
    score = 0

    if product.get('price'):
        score += 4
    if product.get('product_code'):
        score += 3
    if product.get('availability'):
        score += 2
    if product.get('brand'):
        score += 1

    score += min(len(product.get('specs') or []), 8)

    return score


def pick_best_unique_products(products):
    # Collapse duplicate candidates from the same extraction response before
    # checking against the database. This prevents the first weak candidate from
    # being saved while a later, better candidate gets treated as duplicate.
    best_by_key = {}

    for product in products:
        key = product_identity_key(product)

        if key not in best_by_key or product_quality_score(product) > product_quality_score(best_by_key[key]):
            best_by_key[key] = product

    return list(best_by_key.values())


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

def product_extractor(db, record, job_id):
    # Full extraction pipeline for one saved internal_url row:
    # 1. collect deterministic candidates from markdown
    # 2. ask the LLM for structured product data
    # 3. validate high-risk fields such as price
    # 4. collapse repeated candidates from this one response
    # 5. save unique DB products or duplicate records
    markdown = record['markdown'].strip()

    candidates = {
        "prices": extract_price_candidates(markdown),
        "product_codes": extract_product_code_candidates(markdown),
        "availability": extract_availability_candidates(markdown),
    }

    products = ask_llm_for_products(markdown=markdown)

    products = [
        validate_product(product, candidates)
        for product in products
    ]

    products = pick_best_unique_products(products)

    if not products:
        raise CRAWL_FAILED(log_message="No products extracted from markdown.")

    for product in products:
        duplicate = find_duplicate_product(
            db=db,
            website_id=record['website_id'],
            product=product
        )

        if duplicate:
            save_duplicate_item(db, product, duplicate, record, job_id)
        else:
            save_item(db, product, record, job_id)



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

class CODE_BUG(Exception):
    def __init__(self, error_code='CODE_BUG', error_message='Error in the code. [For developers].', log_message=''):
        super().__init__(f"{log_message} {error_message}") # passing the log message to base Exception class
        self.error_code = error_code
        self.log_message = log_message
        self.error_message = error_message

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
        error = "Badly formatted or improper URL entered. A good URL looks like https://example.com"
    except Exception:
        error = "Misc Error"
    return error
        

def return_bad_input_response(error_message="Bad Input"):
    return jsonify({
        "success": False,
        "error_message": error_message
    }), 400
