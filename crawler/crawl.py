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
    scrape_links_task, scrape_markup_task
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
                    'internal_url_job_id', i.job_id,
                    'markdown', i.markdown
                )
            ) AS internal_links_json
        FROM crawl_job j
        LEFT JOIN internal_url i ON i.job_id = j.job_id
        INNER JOIN website w ON w.website_id = i.website_id
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

@bp.route('/scrape-markup/result/<job_id>', methods=('GET',))
@login_required
def get_scraped_markup(job_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT 
            j.job_id,
            w.website_id,
            w.website_url,
            i.url_id,
            i.url_address,
            i.redirected_url_address,
            i.error_message,
            i.status_code,
            i.redirected_status_code,
            i.page_description,
            i.page_title,
            i.markdown,
            i.created,
            i.number_of_internal_links,
            i.number_of_images,
            CASE 
                WHEN j.finished_at IS NOT NULL AND j.started_at IS NOT NULL 
                THEN (strftime('%s', j.finished_at) - strftime('%s', j.started_at)) 
                ELSE 0 
            END AS diff_seconds
        FROM crawl_job j
        LEFT JOIN internal_url i ON i.job_id = j.job_id
        INNER JOIN website w ON w.website_id = i.website_id
        WHERE j.job_id = ?
        """, (job_id,)
    ).fetchall()


    return render_template('crawl/scraped-markup-result.html', rows=rows)


@bp.route('/scrape-markup', methods=('POST', 'GET'))
def scrape_markup():
    if request.method == 'POST':
        try:

            source = request.form.get('source', '').strip()

            if source not in ('bulk', 'external', 'internal'):
                raise CODE_BUG(
                    log_message="Accepted values for source are 'bulk', 'external', or 'internal'."
                )
            
            
            website_id = None
            url = None
            db = get_db()

            if source == "internal" or source == "bulk":

                website_id = request.form.get('website_id', '').strip()

                if not website_id:
                    raise CODE_BUG(log_message="A valid website_id is required for 'bulk' and 'internal' source.")

                exists = find_website(db, website_id=website_id)

                if not exists:
                    raise CODE_BUG(log_message=f"Website ID '{website_id}' does not exist in the database.")

            if source == "internal" or source == "external":

                url = request.form.get('url', '').strip()

                if not url:
                    raise Exception(f"Url is required")

                error_message = check_url(url)

                if error_message:
                    raise Exception(error_message)

            
            job_type = f"SCRAPE_MARKUP_{source}".upper()

        
            job_id = create_crawl_job(db=db, job_type=job_type)

            if source == "external":
                website_id = create_website(db, url, job_id)

            db.commit()

            task = scrape_markup_task.delay(job_id=job_id, website_id=website_id, url_address=url, source=source)

            assign_celery_task_id_to_crawl_job(
                db=db,
                task_id=task.id,
                job_id=job_id
            )
        except CODE_BUG as e:
            flash_error_alert(str(e))
            return redirect(url_for('home.page_not_found'))

        except Exception as e:
            db.rollback()
            flash_error_alert(str(e))
        
        else:
            flash_info_alert('Processing....')
            return redirect(url_for('crawl.get_status'))

    return render_template("crawl/scrape-markup.html")


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
