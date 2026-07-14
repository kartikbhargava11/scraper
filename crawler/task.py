import asyncio

from crawler import celery_global_instance
from crawler.db import get_db
from crawler.helper import (
    mark_crawl_job_started, mark_crawl_job_success, mark_crawl_job_failure, call_firecrawl_map, bfs, scrape_product, CRAWL_FAILED, scrape_html
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
def extract_hardware_info_task(self, job_id, website_id, url_id, url):
    from crawler import create_app

    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()

        mark_crawl_job_started(db, self.request.id, job_id)

        try:
            try:
            # Check if an event loop is already assigned to this worker thread
                loop = asyncio.get_event_loop()
            except RuntimeError as e:
                print(str(e))
                # Create a new isolated loop if none exists
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Run your async function to completion inside the safe loop
            response = loop.run_until_complete(scrape_product(url))

            if isinstance(response, dict) and response['result']:

                for resp in response['result']:
                    row = (resp['name'], resp['short_description'], resp['price'], resp['brand'], resp['product_code'], resp['availability'], job_id, url_id, website_id)

                    curr = db.execute("""
                        INSERT INTO item (name, description, price, brand, product_code, availability, job_id, url_id, website_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, row)
                    
                    item_id = curr.lastrowid

                    if resp.get('specs', []):

                        _rows = []
                        for spec in resp['specs']:
                            _rows.append((item_id, spec['category'], spec['value']))

                        db.executemany("""
                            INSERT INTO specification (item_id, category_name, category_value)
                            VALUES (?, ?, ?)
                        """,
                        _rows)
                
                mark_crawl_job_success(db, job_id)

            else:
                raise CRAWL_FAILED(log_message="No Response. Crawler thrown an error")
            
        except Exception as e:
            db.rollback()
            mark_crawl_job_failure(db, str(e), job_id)
            raise
        

@celery_global_instance.task(bind=True, ignore_result=False)
def scrape_markup_in_bulk_task(self, job_id, website_id):
    from crawler import create_app

    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()

        try:

            mark_crawl_job_started(db, self.request.id, job_id)

            urls = db.execute("""
            SELECT url_address FROM internal_url
            WHERE website_id = ?
            """,
            (website_id,)
            ).fetchall()


            if not urls:
                raise Exception(f"No URLs Found for the website_id={website_id}")

            _urls = [url['url_address'] for url in urls]

            try:
            # Check if an event loop is already assigned to this worker thread
                loop = asyncio.get_event_loop()
            except RuntimeError as e:
                print(str(e))
                # Create a new isolated loop if none exists
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Run your async function to completion inside the safe loop
            response = loop.run_until_complete(scrape_html(_urls))


            if isinstance(response, dict) and response.get('exception', False):
                raise CRAWL_FAILED(
                    log_message=response.get("error", "Unknown error")
                )
            
            rows = []

            for url, resp in response.items():
                rows.append((website_id, url, resp['url'], resp['status_code'], resp['page_title'], resp['page_description'], resp['error_message'], resp['redirected_status_code'], resp['number_of_images'], resp['number_of_internal_links'], resp['markdown'], job_id))

            db.executemany(
                """
                INSERT INTO internal_url (website_id, url_address, redirected_url_address, status_code, page_title, page_description, error_message, redirected_status_code, number_of_images, number_of_internal_links, markdown, job_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows
            )
            db.commit()

            mark_crawl_job_success(db, job_id)
            
        except Exception as e:
            db.rollback()
            mark_crawl_job_failure(db, str(e), job_id)
            raise



                

                    

                    










        