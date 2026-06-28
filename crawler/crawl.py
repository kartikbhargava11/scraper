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


@bp.route('/scrape-markup-bulk/result/<job_id>', methods=('GET',))
@login_required
def view_scraped_content_for_bulk_scrape(job_id):
    db = get_db()

    rows = db.execute(
        """
        SELECT *
        FROM markup m
        LEFT JOIN internal_url i ON m.url_id = i.url_id
        WHERE m.job_id = ?
        """,
        (job_id,)
    ).fetchall()

    return render_template('crawl/scrape-markup-bulk.html', rows=rows)


@bp.route('/scrape-markup/result/<job_id>', methods=('GET', 'POST'))
@login_required
def view_scraped_content(job_id):
    db = get_db()
    if request.method == 'POST':
        markup_id = request.form.get('markup-id')
        url_id = request.form.get('url-id')
        row = db.execute(
            """
            SELECT *
            FROM markup m
            INNER JOIN internal_url i ON m.url_id = i.url_id
            WHERE m.job_id = ? AND m.markup_id = ? AND m.url_id = ?
            """,
            (job_id, markup_id, url_id)
        ).fetchone()

    else:
        row = db.execute(
            """
            SELECT *
            FROM markup m
            INNER JOIN internal_url i ON m.url_id = i.url_id
            WHERE m.job_id = ?
            """,
            (job_id,)
        ).fetchone()

    if not row:
        flash_error_alert("Page Not Found. 404")
        return render_template('not-found.html')
    

    if row['crawling_error_message']:
        return render_template('crawl/scraped-markup-results.html', row=row)

    titles = db.execute(
        """
        SELECT title FROM title_tag
        WHERE url_id = ?
        """, (row['url_id'],)
    ).fetchall()

    h1 = db.execute(
        """
        SELECT h1 FROM h1_tag
        WHERE url_id = ?
        """, (row['url_id'],)
    ).fetchall()

    h2 = db.execute(
        """
        SELECT h2 FROM h2_tag
        WHERE url_id = ?
        """, (row['url_id'],)
    ).fetchall()

    alt = db.execute(
        """
        SELECT alt_text, img_tag FROM img_alt_tag
        WHERE url_id = ?
        """, (row['url_id'],)
    ).fetchall()

    missing_alt = db.execute(
        """
        SELECT count(*) as cnt FROM img_alt_tag
        WHERE url_id = ? AND alt_text IS NULL;
        """, (row['url_id'],)
    ).fetchone()

    return render_template('crawl/scraped-markup-result.html', alt=alt, h1=h1, h2=h2, titles=titles, missing_alt=missing_alt, row=row)

@bp.route('/scrape-markup-bulk/<job_id>', methods=('POST',))
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
            return render_template("not-found.html")
        
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






