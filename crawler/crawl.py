# this file reads input data, validate it, create DB records,
# queue celery tasks and render HTML pages

# complex crawling and background celery task logic not done here

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, jsonify
)
from werkzeug.exceptions import abort

from crawler.auth import login_required
from crawler.db import get_db
from crawler import celery_global_instance
import crawler.helper as h
import crawler.task as t

bp = Blueprint('crawl', __name__, url_prefix="/crawl")

@bp.route('/scrape-links', methods=('GET', 'POST'))
@login_required
def scrape_links():
    if request.method == 'POST':
        url = request.form['url'].strip()
        max_pages = request.form['max-pages'].strip()
        max_depth = request.form['max-depth'].strip()
        job_type = request.form['job-type'].strip()

        error = h.data_sanity_checks(
            url=url,
            max_pages=max_pages,
            max_depth=max_depth,
        )
        if error:
            h._flash_error_alert(error)
            return render_template('crawl/scrape-links.html')
        
        db = get_db()

        try:
            job_id = h.create_crawl_job(
                db=db,
                job_type=job_type
            )

            website_id = h.create_website(db, url, job_id)


            db.commit()

            task = t.scrape_links_task.delay(job_id)

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
            h._flash_error_alert(str(e))
            return render_template('crawl/scrape-links.html')
        
        h._flash_info_alert('Processing....')
        return redirect(url_for('crawl.get_status'))

    # return the template for GET request
    return render_template('crawl/scrape-links.html')
    

@bp.route('/scrape-links/result/<job_id>', methods=('GET',))
@login_required
def get_scraped_links(job_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT j.job_id, j.task_id, j.job_type, j.job_status, j.error_message, j.created, j.started_at, j.finished_at, m.markup_id, m.html, i.url_id, i.url_address, m.job_id AS markup_job_id, i.depth
        FROM crawl_job j
        INNER JOIN internal_url i ON i.job_id = j.job_id
        LEFT JOIN markup m ON m.url_id = i.url_id
        WHERE j.job_id = ?
        """, (job_id,)
    ).fetchall()

    return render_template("crawl/scraped-links-result.html", rows=rows, count=len(rows), job_id=job_id)

@bp.route('/scrape-markup', methods=('POST', ))
@login_required
def scrape_markup():
    url = request.form['url'].strip()
    url_id = request.form['url-id'].strip()
 
    # data sanity check
    # verify the format of the url before sending it to crawl4ai
    error = h.data_sanity_checks(
        url=url
    )

    if error:
        h._flash_error_alert(error)
    
    try:

        db = get_db()

        job_id = h.create_crawl_job(
            db=db,
            job_type='scrape-markup'
        )

        markup_id = h.create_markup(
            db=db,
            url_id=url_id,
            job_id=job_id
        )

        task = t.scrape_markup_task.delay(job_id)

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
        h._flash_error_alert(str(e))

        return redirect(url_for('crawl.get_status'))
    
    h._flash_info_alert('Process in Queue...')
    return redirect(url_for('crawl.get_status'))
    

@bp.route('/scrape-markup/result/<job_id>', methods=('GET',))
@login_required
def view_scraped_content(job_id):
    db = get_db()

    row = db.execute(
        """
        SELECT url_id
        FROM markup
        WHERE job_id = ?
        """, (job_id,)
    ).fetchone()

    if not row:
        h._flash_error_alert("Page Not Found. 404")
        return render_template('not-found.html')

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

    html = db.execute(
        """
        SELECT html FROM markup
        WHERE url_id = ?;
        """, (row['url_id'],)
    ).fetchone()

    return render_template('crawl/scrape-markup.html', alt=alt, h1=h1, h2=h2, titles=titles, missing_alt=missing_alt, html=html)

@bp.route('/scrape-markup-bulk/<website_id>', methods=('GET',))
@login_required
def scrape_markup_bulk(website_id):
    db = get_db()
    # # 
    # rows = db.execute("""
    #     SELECT i.url_id, i.url_address, i.depth, i.website_id, m.markup_id
    #     FROM internal_url i
    #     LEFT JOIN markup m ON i.url_id = m.url_id
    #     WHERE m.markup_id is NULL and i.website_id = ?
    # """, (website_id,)
    # ).fetchall()

    # df = pd.DataFrame([dict(row) for row in rows])

    # excel_path = os.path.join(os.getcwd(), "static", f"output_.xlsx")
    # df.to_excel(excel_path, index=False)


    return render_template('crawl/scrape-markup-bulk.html')

@bp.route('/check-status', methods=('GET',))
@login_required
def get_status():
    db = get_db()
    rows = db.execute(
        """
        SELECT *
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

    h._flash_info_alert("Deleted the results")

    return redirect(url_for("crawl.get_status")) 






