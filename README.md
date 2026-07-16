# Web Crawler and Product Scraper

A Flask-based web application for crawling websites, storing internal links and page markup, and extracting computer-hardware product data from product pages.

The app uses SQLite for local storage, Redis as the Celery broker, Celery workers for background jobs, and Crawl4AI/Firecrawl helpers for crawling and scraping.

## Project Goal

The goal of this project is to build a practical crawler that can:

1. Discover internal links from a target website.
2. Scrape page metadata and markdown from selected URLs.
3. Extract structured product information such as name, description, price, brand, product code, availability, and specifications.
4. Store crawl jobs, websites, URLs, markup, products, specifications, and duplicate-product records in a database.
5. Run long-running crawl and scrape operations in the background instead of blocking the Flask web app.

The project is currently focused on e-commerce/computer-hardware websites, where product pages can contain noisy markup, repeated sections, missing fields, or duplicate extracted products.

## Tech Stack

- Python 3.13
- Flask
- SQLite
- Celery
- Redis
- Crawl4AI
- Firecrawl API helpers
- Docker and Docker Compose
- Jinja templates

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/kartikbhargava11/scraper.git
cd scraper
```

### 2. Create an Environment File

Create a `.env` file in the project root.

Example:

```bash
SECRET_KEY=dev-secret-key
DEBUG=True
TIMEZONE=Asia/Kolkata

BROKER_URL=redis://redis:6379/0
RESULT_BACKEND=redis://redis:6379/0

OPEN_AI_MODEL=
OPEN_AI_KEY=

FIRECRAWL_TOKEN=
FIRECRAWL_MAP_API=https://api.firecrawl.dev/v2/map
FIRECRAWL_SCRAPE_API=https://api.firecrawl.dev/v2/scrape

COUNTRY=IN
LOACALE=en-IN
TIMEOUT=6000

CODE_STARTED=STARTED
CODE_SUCCESS=SUCCESS
CODE_FAILURE=FAILURE
```

Fill in the OpenAI/Firecrawl values only if you are using those extraction or crawling paths.

### 3. Build the Containers

```bash
docker-compose build --no-cache
```

### 4. Start the App

```bash
docker-compose up
```

The Flask app runs at:

```text
http://localhost:5001
```

### 5. Stop the App

```bash
docker-compose down
```

## Database Setup

The Docker web service currently runs:

```bash
flask init-db
```

when the container starts. This initializes the SQLite database from:

```text
crawler/schema.sql
```

The database file is stored in:

```text
instance/crawler.sqlite
```

Important: `flask init-db` rebuilds the schema. If you change `schema.sql`, existing local data may be reset depending on how the schema is written. For long-term use, add migrations instead of repeatedly deleting and recreating tables.

## How the Code Works

### 1. Flask App Startup

`crawler/__init__.py` creates the Flask app, loads environment variables, configures SQLite, registers blueprints, and connects Celery to the Flask app context.

Registered blueprints include:

- `home`
- `auth`
- `crawl`
- `crawl_api`

### 2. User Starts a Crawl

The web routes in `crawler/crawl.py` handle form submissions for:

- scraping internal links
- scraping markup for one URL
- scraping markup in bulk from stored internal URLs
- checking job status
- viewing crawl results

When the user submits a crawl request, the app:

1. validates the input URL and crawl settings
2. creates a `crawl_job`
3. creates or reuses a `website`
4. queues a Celery task
5. redirects the user to the job-status page

### 3. Celery Runs Background Tasks

`crawler/task.py` contains the long-running background jobs.

Main tasks:

- `scrape_links_task`
  - crawls a website and stores internal links in `internal_url`

- `scrape_markup_task`
  - scrapes markdown and page metadata for external, internal, or bulk URLs

- `extract_hardware_info_task`
  - extracts product data from a product URL and stores products/specifications

Celery uses Redis as the broker/backend, configured through:

```text
BROKER_URL
RESULT_BACKEND
```

### 4. Crawling and Extraction Helpers

`crawler/deep_crawling.py` and `crawler/crawl_config.py` contain the Crawl4AI configuration and scraping logic.

They define browser settings, crawling filters, extraction strategies, and async scraping functions.

`crawler/helper.py` contains shared helper functions for:

- URL validation
- job creation and status updates
- website lookup
- Firecrawl map calls
- product duplicate detection
- text, price, and product-code normalization

### 5. Database Storage

`crawler/schema.sql` defines the SQLite tables:

- `user`
- `crawl_job`
- `website`
- `internal_url`
- `item`
- `duplicate_item`
- `specification`

Product data is stored in `item`, while detailed product attributes are stored in `specification`.

The `duplicate_item` table is intended for products that are detected as duplicates of an already saved item.

## Project Structure

```text
.
├── README.md
├── docker-compose.yml
├── dockerfile
├── requirements.txt
├── instance/
│   └── crawler.sqlite
└── crawler/
    ├── __init__.py
    ├── auth.py
    ├── crawl.py
    ├── crawl_api.py
    ├── crawl_config.py
    ├── db.py
    ├── deep_crawling.py
    ├── helper.py
    ├── home.py
    ├── schema.sql
    ├── task.py
    ├── static/
    │   └── style.css
    └── templates/
        ├── base.html
        ├── foot.html
        ├── nav.html
        ├── not-found.html
        ├── auth/
        │   ├── login.html
        │   └── register.html
        ├── crawl/
        │   ├── check-status.html
        │   ├── scrape-links.html
        │   ├── scrape-markup.html
        │   ├── scraped-links-result.html
        │   ├── scraped-product-result.html
        │   └── scraped-markup-result.html
        └── home/
            └── index.html
```

## Useful Commands

Start the full stack:

```bash
docker-compose up
```

Rebuild containers:

```bash
docker-compose build --no-cache
```

Initialize/reset the database inside the web container:

```bash
docker compose exec web flask init-db
```

Stop containers:

```bash
docker-compose down
```

## Current Notes

- Product extraction can return duplicate products when the LLM sees repeated or chunked product information.
- Exact fields such as price and product code should be validated against the scraped page markdown/HTML where possible.
- The app currently uses SQLite, which is convenient for local development. PostgreSQL may be a better fit later if the crawler needs heavier concurrent writes, multiple workers, or production-scale data.
