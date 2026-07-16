import json

from flask import (
    Blueprint, g, jsonify, request
)

from crawler.db import get_db
from crawler.helper import (
    data_sanity_checks, create_crawl_job, create_website, assign_celery_task_id_to_crawl_job, check_url, find_website, return_bad_input_response
)
from crawler.task import (
    scrape_links_task, scrape_markup_task
)

bp = Blueprint('crawl_api', __name__, url_prefix='/api/v1/crawl')

@bp.route('/scrape-links', methods=('POST',))
def scrape_links():
    if not request.is_json:
        return jsonify({
            "success": False,
            "error_message": "Content-Type must be application/json"
        }), 400
    
    data = request.get_json()

    url = data.get('url').strip()
    max_pages = data.get('max-pages')
    max_depth = data.get('max-depth')
    job_type = data.get('job-type').strip()
    
    if not job_type:
        return jsonify({
            "success": False,
            "error_message": "job_type is required. Accepted values are 'MAP', 'DEEP_CRAWLING'"
        }), 400

    error = data_sanity_checks(
        url=url,
        max_pages=max_pages,
        max_depth=max_depth)
    
    if error:
        return jsonify({
            "success": False,
            "error_message": error
        }), 400

    try:
        db = get_db()

        job_id = create_crawl_job(
            db=db,
            job_type=job_type)
        
        website_id = create_website(db, url, job_id, max_depth=max_depth, max_pages=max_pages)

        db.commit()

        task = scrape_links_task.delay(job_id, job_type, url, website_id, int(max_depth), int(max_pages))

        assign_celery_task_id_to_crawl_job(
            db=db,
            task_id=task.id,
            job_id=job_id)

    except Exception as e:
        db.rollback()
        return jsonify({
            "success": False,
            "error_message": str(e)
        }), 500

    
    return jsonify({
        "success": True,
        "message": "Request is valid. [ACCEPTED]",
    }), 202

@bp.route('/scrape-markup/<source>', methods=('POST',))
def scrape_markup(source):
    if not request.is_json:
        return return_bad_input_response("Content-Type must be application/json")

    if source not in ('bulk', 'external', 'internal'):
        return return_bad_input_response("Accepted values are '/bulk', '/external', or '/internal'")
    
    db = get_db()

    job_type = f"SCRAPE_MARKUP_{source}".upper()

    data = request.get_json()

    website_id=None
    url=None

    if source == "bulk" or source == "internal":
        website_id = data.get('website_id', '')
        if not website_id:
            return return_bad_input_response(error_message="A valid website_id is required for '/bulk' and '/internal'")
            
        exists = find_website(db, website_id=website_id)

        if not exists:
            return return_bad_input_response(error_message=f"Website ID '{website_id}' does not exist in the database.")
        

    if source == "internal" or source == "external":

        url = data.get('url', '')

        if not url:
            return return_bad_input_response(error_message="A valid url is required for '/external' and '/internal'")
            
        error_message = check_url(url)

        if error_message:
            return return_bad_input_response(error_message=error_message)
        
    try:
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

    except Exception as e:
        db.rollback()
        return jsonify({
            "success": False,
            "error_message": str(e)
        }), 500

    return jsonify({
        "success": True,
        "message": "Request is valid. [ACCEPTED]",
    }), 202
    
@bp.route('/check-status/', defaults={'status_type': None}, methods=('GET',))
@bp.route('/check-status/<status_type>', methods=('GET',))
def get_status_of_jobs(status_type):
    rows = []

    base_query = """
        SELECT *, (strftime('%s', finished_at) - strftime('%s', started_at)) AS diff_seconds
        FROM crawl_job
    """

    db = get_db()
    if status_type is None:
        rows = db.execute(
            f"{base_query} ORDER BY created DESC"
        ).fetchall()
    elif status_type == 'active':
        rows = db.execute(
            f"{base_query} WHERE job_status = 'STARTED' OR job_status = 'PENDING' ORDER BY created DESC"
        ).fetchall()
    elif status_type == 'failed':
        rows = db.execute(
            f"{base_query} WHERE job_status = 'FAILURE' ORDER BY created DESC"
        ).fetchall()
    elif status_type == 'success':
        rows = db.execute(
            f"{base_query} WHERE job_status = 'SUCCESS' ORDER BY created DESC"
        ).fetchall()
    else:
        return jsonify({
            "success": False,
            "error_message": "Use 'active', 'failed', 'success' or leave blank in the URL to get all the statuses"
        }), 400
    
    return jsonify({
        "success": True,
        "results": [dict(row) for row in rows]
    }), 200

@bp.route('/scrape-links/result/<job_id>', methods=('GET',))
def get_scraped_links(job_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT 
            w.website_id, 
            w.website_url,
            j.job_id,
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
                    'markdown', i.markdown,
                    'created', i.created
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

    if not rows:
        return jsonify({
            "error_message": "No Data Found",
            "success": False
        }), 400

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

    return jsonify({
        "results": processed_websites,
        "total_urls_crawled": total_count,
        "success": True,
    }), 200

@bp.route('/delete/<job_id>', methods=('DELETE',))
def delete_job(job_id):
    db = get_db()

    row = db.execute("SELECT * FROM crawl_job WHERE job_id = ?", (job_id,)).fetchone()

    if not row:
        return jsonify({
            "success": False,
            "error_message": "No job found to delete. [FAILURE]"
        }), 400

    db.execute("DELETE FROM crawl_job WHERE job_id = ?", (job_id,))
    db.commit()

    return jsonify({
        "success": True,
        "message": f"job_id={row['job_id']}. [DELETED]",
        "result": dict(row)
    }), 204

