import asyncio

from crawler import celery_global_instance
from crawler.db import get_db
from crawler.helper import (
    mark_crawl_job_started, mark_crawl_job_success, mark_crawl_job_failure, call_firecrawl_map, bfs, CRAWL_FAILED, scrape_html, product_extractor
)


@celery_global_instance.task(bind=True, ignore_result=False)
def scrape_links_task(self, job_id, job_type, url, website_id, max_depth, max_pages):
    from crawler import create_app

    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()
        rows = []
        
        mark_crawl_job_started(db, self.request.id, job_id)

        try:
            if job_type == 'FIRECRAWL_MAP':
                # firecrawl service
                links = call_firecrawl_map(url)
                # for link in links:
                #     if link.get('url'):
                #         rows.append(
                #             (link['url'], None, job_id, website_id)
                #         )
            else:
                # crawl4AI
                # celery tasks run synchronously. We bridge into the async engine using asyncio to host crawl4ai
                try:
                    # Check if an event loop is already assigned to this worker thread
                    loop = asyncio.get_event_loop()
                except RuntimeError as e:
                    print(str(e))
                    # Create a new isolated loop if none exists
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                # Run your async function to completion inside the safe loop
                response = loop.run_until_complete(bfs(url, max_depth, max_pages))
                
                for depth, results in response.items():
                    for result in results:
                        rows.append((
                            result['url'],
                            result['page_title'],
                            result['page_description'],
                            result['number_of_images'],
                            result['number_of_internal_links'],
                            result['status_code'],
                            result['redirected_status_code'],
                            result['error_message'],
                            result['markdown'],
                            depth,
                            job_id,
                            website_id
                        ))

                
                # if no URLs were extracted
                if len(rows) == 0:
                    raise CRAWL_FAILED(
                        log_message="No URLs Found, Due to Crawling Failures"
                    )

            db.executemany(
                """
                INSERT INTO internal_url (url_address, page_title, page_description, number_of_images, number_of_internal_links, status_code, redirected_status_code, error_message, markdown, depth, job_id, website_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows
            )

            mark_crawl_job_success(db, job_id)

        except Exception as e:
            db.rollback()
            mark_crawl_job_failure(db, str(e), job_id)
            raise


@celery_global_instance.task(bind=True, ignore_result=False)
def scrape_markup_task(self, job_id, website_id, url_address=None, source=None):
    from crawler import create_app

    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()

        try:

            mark_crawl_job_started(db, self.request.id, job_id)

            urls = []

            if source == "bulk" and website_id is not None:
                query_result = db.execute("""
                    SELECT url_address FROM internal_url
                    WHERE website_id = ?
                """,
                (website_id,)
                ).fetchall()

                if query_result:
                    urls = [_['url_address'] for _ in query_result]

            elif source in ('external', 'internal') and url_address is not None:
                urls = [url_address]
            
            if not urls: # second layer protection. a bit redundant but okay.
                raise Exception("Bad Input.")


            try:
            # Check if an event loop is already assigned to this worker thread
                loop = asyncio.get_event_loop()
            except RuntimeError as e:
                print(str(e))
                # Create a new isolated loop if none exists
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Run your async function to completion inside the safe loop
            response = loop.run_until_complete(scrape_html(urls))


            if not isinstance(response, dict):
                raise CRAWL_FAILED(
                    log_message="Unknown Error"
                )

            if isinstance(response, dict) and response.get('exception', False):
                raise CRAWL_FAILED(
                    log_message=response.get("error", "Unknown Error")
                )
            
            required_keys = ["url", "status_code", "page_title", "page_description", "error_message", "redirected_status_code", "number_of_images", "number_of_internal_links", "markdown"]

            
            if isinstance(response, dict) and response:
                
                # dynamically build rows to insert into db using a list comprehension and item retrieval
                # This ensures we only grab the inner dictionary values if they exist

                rows = [
                    (website_id, url, *(resp.get(k) for k in required_keys), job_id)
                    for url, resp in response.items()
                    if isinstance(resp, dict)
                ]

                if not rows:
                    raise Exception("Code Error. Error with payload from the crawler")

                db.executemany(
                    """
                    INSERT INTO internal_url (website_id, url_address, redirected_url_address, status_code, page_title, page_description, error_message, redirected_status_code, number_of_images, number_of_internal_links, markdown, job_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows
                )

                db.commit()

                mark_crawl_job_success(db, job_id)

            else:
                raise Exception("Code Error. Error with payload from the crawler")
            
        except Exception as e:
            db.rollback()
            mark_crawl_job_failure(db, str(e), job_id)
            raise

@celery_global_instance.task(bind=True, ignore_result=False)
def extract_products_task(self, job_id, url_id):
    from crawler import create_app

    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()

        # This job is created by the Flask route when the user clicks
        # "Extract Products". Mark it as started before doing any real work so
        # the status page reflects that the Celery worker has picked it up.
        mark_crawl_job_started(db, self.request.id, job_id)

        try:
            # Product extraction is based on already-scraped markdown. We load
            # the internal_url row instead of crawling the URL again.
            row = db.execute(
                """
                SELECT * FROM internal_url
                WHERE url_id = ?
                """,
                (url_id,)
            ).fetchone()

            if not row:
                raise CRAWL_FAILED(log_message="A valid url_id is not found.")
            
            if not row["markdown"]:
                raise CRAWL_FAILED(log_message="Markdown is not found.")
            
            # The helper owns the product pipeline:
            # markdown -> LLM extraction -> validation -> dedupe -> DB insert.
            product_extractor(db=db, record=row, job_id=job_id)

            db.commit()

            # Mark success only after item/duplicate_item inserts have been
            # committed successfully.
            mark_crawl_job_success(db, job_id)

        
        except Exception as e:
            db.rollback()
            mark_crawl_job_failure(db, str(e), job_id)
            raise
