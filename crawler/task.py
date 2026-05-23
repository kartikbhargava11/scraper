import asyncio
import sqlite3
from bs4 import BeautifulSoup

from crawler import celery_global_instance
from crawler.db import get_db

# importing functions that handle crawling
from crawler.deep_crawling import _get_links_using_bfs, _scrape_content

async def bfs(url):
    # function returns all the internal links & their depth in the given URL 
    dedup_links = await _get_links_using_bfs(url)

    return dedup_links

async def scrape_html(url):
    # function returns the scraped HTML markup
    html = await _scrape_content(url)

    return html

@celery_global_instance.task(ignore_result=False)
def scrape_markup_task(url, url_id, website_id):
    try:
        # Check if an event loop is already assigned to this worker thread
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # Create a new isolated loop if none exists
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    # Run your async function to completion inside the safe loop
    html = loop.run_until_complete(scrape_html(url))
    from crawler import create_app
    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()
        try:
            row = db.execute(
                "SELECT url_address FROM internal_url WHERE url_id = ?", (url_id,)
            ).fetchone()

            if row and row['url_address'] == url:
                
                db.execute(
                    """
                    INSERT OR IGNORE INTO markup (html, url_id, website_id)
                    VALUES (?,?,?)
                    """,
                    (html, url_id, website_id)
                )

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
                    INSERT OR IGNORE INTO title_tag (title, url_id)
                    VALUES (?,?)
                    """,
                    title
                )
                db.executemany(
                    """
                    INSERT OR IGNORE INTO h1_tag (h1, url_id)
                    VALUES (?,?)
                    """,
                    headings1
                )
                db.executemany(
                    """
                    INSERT OR IGNORE INTO h2_tag (h2, url_id)
                    VALUES (?,?)
                    """,
                    headings2
                )
                db.executemany(
                    """
                    INSERT OR IGNORE INTO img_alt_tag (alt_text, img_tag, url_id)
                    VALUES (?,?,?)
                    """,
                    alt
                )
                title.clear()
                headings1.clear()
                headings2.clear()
                alt.clear()
                
        except sqlite3.Error as e:
            db.rollback()
            print(f"Exception {e}")
        else:
            db.commit()
        
            
    return html

@celery_global_instance.task(ignore_result=False)
def scrape_links_task(url):
    try:
        # Check if an event loop is already assigned to this worker thread
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # Create a new isolated loop if none exists
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    # Run your async function to completion inside the safe loop
    dedup_links = loop.run_until_complete(bfs(url))
    data_in_list = []
    from crawler import create_app
    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()
        
        try:
            row = db.execute(
                "SELECT website_id FROM website WHERE website_url = ?", (url,)
            ).fetchone()

            if row:
                website_id = row['website_id']
                
                for _url, depth in dedup_links.items():
                    data_in_list.append((_url, depth, website_id))
                
                db.executemany(
                    """
                    INSERT OR IGNORE INTO internal_url (url_address, depth, website_id)
                    VALUES (?,?,?);
                    """,
                    data_in_list

                )

                db.commit()
        except sqlite3.Error as e:
            db.rollback()
            print(f"Exception {e}")
        
    return data_in_list