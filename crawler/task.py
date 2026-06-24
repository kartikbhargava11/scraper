import asyncio
import sqlite3

from bs4 import BeautifulSoup

from crawler import celery_global_instance
from crawler.db import get_db
from crawler.helper import call_firecrawl_map, scrape_html, bfs


@celery_global_instance.task(bind=True, ignore_result=False)
def scrape_markup_task(self, job_id):
    from crawler import create_app
    flask_app = create_app()

    with flask_app.app_context():
        db = get_db()

        job = db.execute(
            """
            SELECT m.job_id, m.url_id, i.url_address
            FROM markup m
            INNER JOIN internal_url i ON i.url_id = m.url_id
            WHERE m.job_id = ?
            """,
            (job_id,)
        ).fetchone()

        if not job:
            return None
        
        db.execute(
            """
            UPDATE crawl_job
            SET job_status = ?, task_id = ?, started_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
            """,
            ("STARTED", self.request.id, job_id)
        )
        db.commit()

        try:
            html = asyncio.run(scrape_html(job['url_address']))
            
            # try:
            #     # Check if an event loop is already assigned to this worker thread
            #     loop = asyncio.get_event_loop()
            # except RuntimeError:
            #     # Create a new isolated loop if none exists
            #     loop = asyncio.new_event_loop()
            #     asyncio.set_event_loop(loop)
                
            # # Run your async function to completion inside the safe loop
            # html = loop.run_until_complete(scrape_html(job['url_address']))

            soup = BeautifulSoup(html, 'html.parser')

            title = []
            headings1 = []
            headings2 = []
            alt = []


            for tag in soup.find_all(['title', 'h1', 'h2', 'img']):
                if tag.name == 'title':
                    title.append((str(tag), job['url_id']))
                elif tag.name == 'h1':
                    headings1.append((str(tag), job['url_id']))
                elif tag.name == 'h2':
                    headings2.append((str(tag), job['url_id']))
                elif tag.name == 'img':
                    if tag.has_attr('alt'):
                        alt.append((tag['alt'], str(tag), job['url_id']))
                    else:
                        alt.append((None, str(tag), job['url_id']))
            
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

            db.execute(
                """
                UPDATE crawl_job
                SET job_status = ?, finished_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                ("SUCCESS", job_id)
            )
            db.commit()

        except Exception as e:
            db.rollback()
            db.execute(
                """
                UPDATE crawl_job
                SET job_status = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                ("FAILURE", str(e), job_id)
            )
            db.commit()
            raise



@celery_global_instance.task(bind=True, ignore_result=False)
def scrape_links_task(self, job_id):
    from crawler import create_app

    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()
        rows = []

        job = db.execute(
            """
            SELECT j.job_id, j.job_type, w.website_id, w.website_url
            FROM crawl_job j
            INNER JOIN website w ON w.job_id = j.job_id
            WHERE j.job_id = ?
            """,
            (job_id,)
        ).fetchone()

        if not job:
            return []

        
        db.execute(
            """
            UPDATE crawl_job
            SET job_status = ?, task_id = ?, started_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
            """,
            ("STARTED", self.request.id, job_id)
        )
        db.commit()
        try:
            if job['job_type'] == 'firecrawl-map':
                # firecrawl service
                links = call_firecrawl_map(job['website_url'])
                for link in links:
                    if link.get('url'):
                        rows.append(
                            (link['url'], None, job['job_id'])
                        )
            else:
                # crawl4AI
                links = asyncio.run(bfs(job['website_url']))

                for link, depth in links.items():
                    rows.append((link, depth, job['job_id']))

            db.executemany(
                """
                INSERT INTO internal_url (url_address, depth, job_id)
                VALUES (?, ?, ?)
                """,
                rows
            )

            db.execute(
                """
                UPDATE crawl_job
                SET job_status = ?, finished_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                ("SUCCESS", job_id)
            )
            db.commit()

            return rows
        except Exception as e:
            db.rollback()
            db.execute(
                """
                UPDATE crawl_job
                SET job_status = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
                """,
                ("FAILURE", str(e), job_id)
            )
            db.commit()
            raise

