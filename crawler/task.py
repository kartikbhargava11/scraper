import asyncio

from crawler import celery_global_instance
from crawler.db import get_db
from crawler.helper import *

@celery_global_instance.task(bind=True, ignore_result=False)
def scrape_markup_bulk_task(self, job_id, _job_id):
    # job_id -> will be used to extract all the URLs extracted by this <job_id>
    # _job_id -> will be used to update the job status
    from crawler import create_app
    flask_app = create_app()

    with flask_app.app_context():
        db = get_db()

        rows = db.execute( # Fetching all the URLs to scrape
            """
            SELECT i.url_address, i.url_id
            FROM crawl_job j
            INNER JOIN internal_url i ON j.job_id = i.job_id
            WHERE j.job_id = ?
            ORDER BY i.url_id
            """,
            (job_id,)
        ).fetchall()

        if not rows: # if no URLs found raise exception
            raise ERROR_CODE_400(
                log_message="No URLs Found"
            )
        
        mark_crawl_job_started(db, self.request.id, _job_id) # set the status of the job as started
        

        try:
            # rows <- list of dicts from the database
            # [
            #	{url_id: 12, url_address: 'https://google.com'},
            #	{url_id: 13, url_address: 'https://apple.com'},
            # ]
            try:
                # Check if an event loop is already assigned to this worker thread
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # Create a new isolated loop if none exists
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            # Run your async function to completion inside the safe loop
            results = loop.run_until_complete(crawl_bulk(rows))

            # results = asyncio.run(crawl_bulk(rows)) # call to crawling engine, returns a dict

            if len(results) < 1:
                raise CRAWL_FAILED(
                    log_message='Crawling Engine did not return the results'
                )


            payload = []

            # save the results for each URL with their corresponding url_id in a list to save them in the database
            for res in results.values():
                payload.append(
                    (res['html'], res['status_code'], res['final_crawled_url'], res['redirected_status_code'], res['crawling_error_message'], res['url_id'], _job_id)
                )
            

            db.executemany( # running SQL command to update the 
                """
                INSERT INTO markup (html, status_code, final_crawled_url, redirected_status_code, crawling_error_message, url_id, job_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                payload
            )
            db.commit()

            for res in results.values():
                if res['success'] and res['html']:
                    save_html_tags(db, res['html'], res['url_id'])

            mark_crawl_job_success(db, _job_id)
            
        except Exception as e:
            db.rollback()
            mark_crawl_job_failure(db, str(e), _job_id)
            raise

@celery_global_instance.task(bind=True, ignore_result=False)
def scrape_markup_task(self, job_id, markup_id, url):
    from crawler import create_app
    flask_app = create_app()

    with flask_app.app_context():
        db = get_db()

        
        mark_crawl_job_started(db, self.request.id, job_id)

        try:
            result = asyncio.run(scrape_html(url))
            
            # try:
            #     # Check if an event loop is already assigned to this worker thread
            #     loop = asyncio.get_event_loop()
            # except RuntimeError:
            #     # Create a new isolated loop if none exists
            #     loop = asyncio.new_event_loop()
            #     asyncio.set_event_loop(loop)
                
            # # Run your async function to completion inside the safe loop
            # html = loop.run_until_complete(scrape_html(job['url_address']))

            db.execute(
                """
                UPDATE markup
                SET html = ?,
                status_code = ?,
                final_crawled_url = ?,
                redirected_status_code = ?,
                crawling_error_message = ?
                WHERE job_id = ? AND markup_id = ?
                """,
                (
                    result['html'],
                    result['status_code'],
                    result['final_crawled_url'],
                    result['redirected_status_code'],
                    result['crawling_error_message'],
                    job_id,
                    markup_id
                )
            )
            db.commit()
            
            if not result['html']:
                raise NO_HTML
            
            save_html_tags(db, result['html'], markup_id)
            
            mark_crawl_job_success(db, job_id)

        except NO_HTML as e:
            mark_crawl_job_failure(db, e.log_message, job_id)
            raise # re-raise the original error so celery also knows the task failed

        except Exception as e:
            db.rollback() # rollback partial DB work
            mark_crawl_job_failure(db, str(e), job_id)
            raise # re-raise the original error so celery also knows the task failed


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

                if job_type == 'DEEP_CRAWLING':
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
                                depth,
                                job_id,
                                website_id
                            ))

                # prefetch mode - quickly discover URLs without full page processing.   
                elif job_type == 'DEEP_CRAWLING_FAST':
                    response = loop.run_until_complete(prefetch_links(url))

                    # if response['success']:
                    #     for link in response['links']:
                    #         rows.append((link['href'], None, job_id, website_id))
                
                # if no URLs were extracted
                if len(rows) == 0:
                    raise CRAWL_FAILED(
                        log_message="No URLs Found, Due to Crawling Failures"
                    )

            db.executemany(
                """
                INSERT INTO internal_url (url_address, page_title, page_description, number_of_images, number_of_internal_links, status_code, redirected_status_code, error_message, depth, job_id, website_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows
            )

            mark_crawl_job_success(db, job_id)

        except Exception as e:
            db.rollback()
            mark_crawl_job_failure(db, str(e), job_id)
            raise


@celery_global_instance.task(bind=True, ignore_result=False)
def extract_computer_hardware_info_task(self, job_id):
    from crawler import create_app

    flask_app = create_app()
    with flask_app.app_context():
        db = get_db()

        mark_crawl_job_started(db, self.request.id, job_id)

        