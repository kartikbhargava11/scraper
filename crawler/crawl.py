# this file reads input data, validate it, create DB records,
# queue celery tasks and render HTML pages

# complex crawling and background celery task logic not done here
import json
from flask import (
    Blueprint, g, redirect, render_template, request, url_for, jsonify
)
from werkzeug.exceptions import abort

from crawler.auth import login_required
from crawler.db import get_db
from crawler.helper import *
from crawler.task import (
    extract_hardware_info_task, scrape_links_task
)

bp = Blueprint('crawl', __name__, url_prefix="/crawl")

@bp.route('/scrape-links', methods=('GET', 'POST'))
@login_required
def scrape_links():
    if request.method == 'POST':
        url = request.form['url'].strip()
        max_pages = request.form['max-pages'].strip()
        max_depth = request.form['max-depth'].strip()
        job_type = request.form['job-type'].strip()

        error = data_sanity_checks(
            url=url,
            max_pages=max_pages,
            max_depth=max_depth,
        )
        if error:
            flash_error_alert(error)
        else:
            try:
                db = get_db()
                job_id = create_crawl_job(
                    db=db,
                    job_type=job_type
                )

                website_id = create_website(db, url, job_id, max_depth=max_depth, max_pages=max_pages)

                db.commit()

                task = scrape_links_task.delay(job_id, job_type, url, website_id, int(max_depth), int(max_pages))

                assign_celery_task_id_to_crawl_job(
                    db=db,
                    task_id=task.id,
                    job_id=job_id
                )

            except Exception as e:
                db.rollback()
                flash_error_alert(str(e))

            else:
                flash_info_alert('Processing....')
                return redirect(url_for('crawl.get_status'))
            
    # return the template for GET request
    return render_template('crawl/scrape-links.html')
    
@bp.route('/scrape-links/result/<job_id>', methods=('GET',))
@login_required
def get_scraped_links(job_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT 
            w.website_id, 
            w.website_url,
            j.job_id,
            i.url_id,
            w.max_depth,
            w.max_pages,
            CASE 
                WHEN j.finished_at IS NOT NULL AND j.started_at IS NOT NULL 
                THEN (strftime('%s', j.finished_at) - strftime('%s', j.started_at)) 
                ELSE 0 
            END AS diff_seconds,
            -- SQLite builds a valid JSON array of objects for all internal links
            json_group_array(
                json_object(
                    'url_id', i.url_id,
                    'url_address', i.url_address,
                    'depth', i.depth,
                    'page_title', i.page_title,
                    'page_description', i.page_description,
                    'status_code', i.status_code,
                    'redirected_status_code', i.redirected_status_code,
                    'number_of_images', i.number_of_images,
                    'number_of_internal_links', i.number_of_internal_links,
                    'error_message', i.error_message,
                    'internal_url_job_id', i.job_id
                )
            ) AS internal_links_json
        FROM crawl_job j
        INNER JOIN website w ON w.job_id = j.job_id
        -- LEFT JOIN ensures websites with 0 internal links still appear
        LEFT JOIN internal_url i ON i.job_id = j.job_id AND i.website_id = w.website_id
        WHERE j.job_id = ?
        -- Grouping by website_id collapses all related links into the JSON array above
        GROUP BY w.website_id
        """, (job_id,)
    ).fetchall()

    processed_websites = []
    total_count = 0

    for row in rows:
        links = json.loads(row['internal_links_json'])

        # clean up empty artifacts 
        if links and links[0]['url_id'] is None:
            links = []

        total_count += len(links)

        processed_websites.append({
            'website_id': row['website_id'],
            'website_url': row['website_url'],
            'job_id': row['job_id'],
            'max_depth': row['max_depth'],
            'max_pages': row['max_pages'],
            'diff_seconds': row['diff_seconds'],
            'links': links
        })

    return render_template("crawl/scraped-links-result.html", rows=processed_websites, count=total_count, job_id=job_id)

@bp.route('/scrape-computer-hardware', methods=('GET', 'POST'))
@login_required
def scrape_hardware_info():
    if request.method == 'POST':
        url = request.form['url'].strip()

        error = check_url(url)

        if error:
            flash_error_alert(error)
        else:
            try:
                db = get_db()

                job_id = create_crawl_job(
                    db=db,
                    job_type='EXTRACT'
                )

                website_id = create_website(db, url, job_id)

                db.commit()

                task = extract_hardware_info_task.delay(job_id, website_id, url)


                assign_celery_task_id_to_crawl_job(
                    db=db,
                    task_id=task.id,
                    job_id=job_id
                )

            except Exception as e:
                db.rollback()
                flash_error_alert(str(e))

            else:
                flash_info_alert('Processing....')
                return redirect(url_for('crawl.get_status'))
        
    return render_template('crawl/scrape-hardware.html')

@bp.route('/check-status', methods=('GET',))
@login_required
def get_status():
    db = get_db()
    rows = db.execute(
        """
        SELECT *, (strftime('%s', finished_at) - strftime('%s', started_at)) AS diff_seconds
        FROM crawl_job
        ORDER BY created DESC
        """
    ).fetchall()
    return render_template("crawl/check-status.html", rows=rows)

@bp.route('/delete/<job_id>', methods=('POST',))
@login_required
def delete_job(job_id):
    db = get_db()
    db.execute("DELETE FROM crawl_job WHERE job_id = ?", (job_id,))
    db.commit()
    flash_info_alert("Deleted the results")
    return redirect(url_for("crawl.get_status")) 

