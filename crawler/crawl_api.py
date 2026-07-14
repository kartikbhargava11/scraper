import json

from flask import (
    Blueprint, g, jsonify, request
)

from crawler.db import get_db
from crawler.helper import (
    data_sanity_checks, create_crawl_job, create_website, assign_celery_task_id_to_crawl_job, check_url, find_website
)
from crawler.task import (
    scrape_links_task, extract_hardware_info_task, scrape_markup_in_bulk_task
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

    error = data_sanity_checks(
        url=url,
        max_pages=max_pages,
        max_depth=max_depth)
    
    if error:
        return jsonify({
            "success": False,
            "error_message": error
        }), 400
    else:
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

        else:
            return jsonify({
                "success": True,
                "message": "Request is valid. [ACCEPTED]",
            }), 202

@bp.route('/scrape-markup/bulk', methods=('POST',))
def scrape_markup_in_bulk():
    if not request.is_json:
        return jsonify({
            "success": False,
            "error_message": "Content-Type must be application/json"
        }), 400
    
    data = request.get_json()

    website_id = data.get('website-id')

    if not website_id:
        return jsonify({
            "success": False,
            "error_message": f"website_id is required."
        }), 400
    
    try:
        db = get_db()
        exists = find_website(db, website_id=website_id)

        if not exists:
            return jsonify({
                "success": False,
                "error_message": f"Website ID '{website_id}' does not exist in the database."
            }), 400

        job_id = create_crawl_job(db=db, job_type="SCRAPE_BULK")

        task = scrape_markup_in_bulk_task.delay(job_id, website_id)

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

@bp.route('/scrape-products', methods=('POST',))
def scrape_products():
    if not request.is_json:
        return jsonify({
            "success": False,
            "error_message": "Content-Type must be application/json"
        }), 400
    
    data = request.get_json()

    url = data.get('url', None)

    website_id = None
    url_id = None

    error = check_url(url)

    if error:
        return jsonify({
            "success": False,
            "error_message": error
        }), 400
    
    try:
        db = get_db()

        job_id = create_crawl_job(
            db=db,
            job_type='EXTRACT')

        website_id = create_website(
            db,
            url=url,
            job_id=job_id)
        
        db.commit()

        task = extract_hardware_info_task.delay(job_id, website_id, url_id, url)

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

@bp.route('/scrape-links/result/<job_id>', methods=('GET',))
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

@bp.route('/scrape-products/result/<job_id>', methods=('GET',))
def get_scraped_products(job_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT
            i.website_id,
            i.url_id,
            i.item_id,
            i.name,
            i.description,
            i.price,
            i.brand,
            i.product_code,
            i.availability,
            COALESCE(u.url_id, w.website_id) AS source_id,
            COALESCE(u.url_address, w.website_url) AS source_url,
            -- SQLite builds a valid JSON array of objects for all internal links
            json_group_array(
                json_object(
                    'specification_id', s.specification_id,
                    'category_name', s.category_name,
                    'category_value', s.category_value
                )
            ) AS specs
        FROM item i
        LEFT JOIN website w ON w.website_id = i.website_id
        LEFT JOIN internal_url u ON u.url_id = i.url_id
        LEFT JOIN specification s ON s.item_id = i.item_id
        WHERE i.job_id = ?
        GROUP BY i.item_id
        """, (job_id,)
    ).fetchall()

    processed_products = []
    

    for row in rows:
        specs = json.loads(row['specs'])

        # clean up empty artifacts 
        if specs and specs[0]['specification_id'] is None:
            specs = []
        

        processed_products.append({
            'source_id': row['source_id'],
            'source_url': row['source_url'],
            'website_id': row['website_id'],
            'url_id': row['url_id'],
            'item_id': row['item_id'],
            'name': row['name'],
            'description': row['description'],
            'price': row['price'],
            'brand': row['brand'],
            'product_code': row['product_code'],
            'availability': row['availability'],
            'specs': specs
        })

    total_count = len(processed_products)

    return jsonify({
        "success": True,
        "total_products_found": total_count,
        "results": processed_products
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

