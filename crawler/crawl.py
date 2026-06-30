# this file reads input data, validate it, create DB records,
# queue celery tasks and render HTML pages

# complex crawling and background celery task logic not done here

from flask import (
    Blueprint, g, redirect, render_template, request, url_for, jsonify
)
from werkzeug.exceptions import abort

from crawler.auth import login_required
from crawler.db import get_db
from crawler.helper import *
from crawler.task import *

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
            return render_template('crawl/scrape-links.html')
        
        db = get_db()

        try:
            job_id = create_crawl_job(
                db=db,
                job_type=job_type
            )

            website_id = create_website(db, url, job_id)


            db.commit()

            task = scrape_links_task.delay(job_id)

            db.execute(
                """
                UPDATE crawl_job
                SET task_id = ?
                WHERE job_id = ?
                """,
                (task.id, job_id)
            )

            db.commit()
        except Exception as e:
            db.rollback()
            flash_error_alert(str(e))
            return render_template('crawl/scrape-links.html')
        
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
        SELECT j.job_id, j.task_id, j.job_type, j.job_status, j.error_message, j.created, j.started_at, j.finished_at, m.markup_id, m.html, i.url_id, i.url_address, m.job_id AS markup_job_id, i.depth, (strftime('%s', j.finished_at) - strftime('%s', j.started_at)) AS diff_seconds
        FROM crawl_job j
        INNER JOIN internal_url i ON i.job_id = j.job_id
        LEFT JOIN markup m ON m.url_id = i.url_id
        WHERE j.job_id = ?
        """, (job_id,)
    ).fetchall()

    return render_template("crawl/scraped-links-result.html", rows=rows, count=len(rows), job_id=job_id)

@bp.route('/scrape-markup', methods=('GET', 'POST'))
@login_required
def scrape_markup():
    if request.method == 'POST':
        url = request.form['url'].strip()
        url_id = request.form['url-id'].strip()

    
        # data sanity check
        # verify the format of the url before sending it to crawl4ai
        error = data_sanity_checks(
            url=url
        )

        if error:
            flash_error_alert(error)
        
        try:

            db = get_db()

            job_id = create_crawl_job(
                db=db,
                job_type='SCRAPE_MARKUP'
            )

            if url_id == 'NEW':
                url_id = create_url_address(
                    db=db,
                    url=url,
                    job_id=job_id
                )

            markup_id = create_markup(
                db=db,
                url_id=url_id,
                job_id=job_id
            )

            task = scrape_markup_task.delay(job_id)

            db.execute("""
            UPDATE crawl_job
            SET task_id = ?
            WHERE job_id = ?       
            """,
            (task.id, job_id)
            )
            db.commit()
        except Exception as e:
            db.rollback()
            flash_error_alert(str(e))
        else:
            flash_info_alert('Process in Queue...')
            return redirect(url_for('crawl.get_status'))
        
    return render_template('crawl/scrape-markup.html')

@bp.route('/scrape-markup/result/<job_id>', methods=('GET', 'POST'))
@login_required
def view_scraped_markup(job_id):

    db = get_db()

    job = db.execute(
        """
        SELECT *
        FROM crawl_job
        WHERE job_id = ?
        """,
        (job_id,)
    ).fetchone()

    if not job:
        flash_error_alert("Page Not Found. 404")
        return redirect(url_for('home.page_not_found'), code=404)

    rows = []

    if request.method == 'POST':
        markup_id = request.form['markup-id'].strip()
        url_id = request.form['url-id'].strip()
        rows = db.execute(
            """
            SELECT m.markup_id, i.url_address, m.status_code, m.final_crawled_url, m.redirected_status_code, m.crawling_error_message, m.url_id, m.job_id
            FROM markup m
            INNER JOIN internal_url i ON i.url_id = m.url_id
            WHERE m.job_id = ? AND m.markup_id = ? AND m.url_id = ?
            """,
            (job_id, markup_id, url_id)
        ).fetchall()

    elif request.method == 'GET':

        rows = db.execute(
            """
            SELECT m.markup_id, i.url_address, m.status_code, m.final_crawled_url, m.redirected_status_code, m.crawling_error_message, m.url_id, m.job_id
            FROM markup m
            LEFT JOIN internal_url i ON i.url_id = m.url_id
            WHERE m.job_id = ?
            """,
            (job_id,)
        ).fetchall()

    return render_template('crawl/scraped-markup-result.html', rows=rows, count=len(rows))

@bp.route('/scrape-markup/bulk/<job_id>', methods=('POST',))
@login_required
def scrape_markup_bulk(job_id):
    try:
        # job_id -> will be used to extract all the links from the db
        db = get_db()

        row = db.execute(
            """
            SELECT job_id FROM crawl_job
            WHERE job_id = ?
            """,
            (job_id,)
        ).fetchone()

        if not row:
            flash_error_alert("Page Not Found. 404")
            return redirect(url_for("home.page_not_found"), code=404)
        
        _job_id = create_crawl_job(
            db=db,
            job_type='SCRAPE_MARKUP_BULK'
        )

        task = scrape_markup_bulk_task.delay(job_id, _job_id)

        db.execute(
            """
            UPDATE crawl_job
            SET task_id = ?
            WHERE job_id = ?
            """,
            (task.id, _job_id)
        )
        db.commit()

    except Exception as e:
        db.rollback()
        flash_error_alert(str(e))
    else:
        flash_info_alert('Process in Queue...')

    return redirect(url_for('crawl.get_status'))

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

