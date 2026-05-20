from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, jsonify
)
from werkzeug.exceptions import abort

from crawler.auth import login_required
from crawler.db import get_db

from crawler import celery_global_instance

from crawler.helper import _flash_success_alert, _flash_error_alert, _flash_info_alert, is_valid_range, is_valid_url, initiate_task

bp = Blueprint('crawl', __name__, url_prefix="/crawl")


@bp.route('/scrape-links', methods=('GET', 'POST',))
@login_required
def scrape_links():
    # form was filled and submit button was pressed
    if request.method == 'POST':
        # variable to use later to show error prompts
        error = None

        # verify the format of the url before sending it to crawl4ai
        url = request.form['url'].strip() if is_valid_url(request.form['url']) else None

        try:
            # performing type conversion
            # by default strings are passed
            raw_max_pages = int(request.form.get('max_pages') or "20")
            raw_max_depth = int(request.form.get('max_depth') or "1")
        except (ValueError, TypeError):
            # couldn't convert the input to an integer
            error = "Max Pages & Max Depth should be numbers between [1,100] and [1,5] respectively"
        else:
            # check for the valid range of max_pages and max_depth
            max_pages = is_valid_range(raw_max_pages, max=100)
            max_depth = is_valid_range(raw_max_depth)

        # simple data sanity checks before moving forward
        if not url:
            error = f"Url {request.form['url']} is invalid"
        elif not max_pages:
            error = "Max Pages is invalid. Valid range is betweem 1 and 100"
        elif not max_depth:
            error = "Max Depth is invalid. Valid range is betweem 1 and 5"
        else: # data sanity checks passed
            # initiate_task helper function
            # -> invokes celery to push a crawling task
            # -> saves task status to the database
            error = initiate_task(url, 'scrape_links_task')
            if error is None:
                # if no error is found, redirect to the page that lists all the tasks
                _flash_info_alert('Processing...')
                return redirect(url_for('crawl.get_status')) 
        # if it runs are some exception has been raised or bad input from the user
        _flash_error_alert(error)
    # return the template for GET request or in the case error from POST request
    return render_template('crawl/scrape-links.html')

@bp.route('/result/<website_id>', methods=('GET',))
@login_required
def get_scraped_links(website_id):
    db = get_db()
    row = db.execute(
        """
        SELECT website_url, website_id
        FROM website
        WHERE website_id = ?
        """, (website_id,)
    ).fetchone()
    rows = db.execute(
        """
        SELECT i.url_id, i.url_address, i.depth, i.website_id, i.created, m.markup_id
        FROM internal_url i
        LEFT JOIN markup m ON i.url_id = m.url_id
        WHERE i.website_id = ?
        """, (website_id,)
    ).fetchall()

    row3 = db.execute(
        """
        SELECT *
        FROM h1_tag
        """
    ).fetchall()

    print(f"OVERALL SIZE {len(row3)}")

    return render_template("crawl/scraped-links-result.html", rows=rows, row=row, count=len(rows))

@bp.route('/scrape-markup', methods=('POST', ))
@login_required
def scrape_markup():
    error = None
    # data sanity check
    # verify the format of the url before sending it to crawl4ai
    url = request.form['url'].strip() if is_valid_url(request.form['url']) else None
    url_id = int(request.form['url_id'])
    website_id = int(request.form['website_id'])
    if not url:
        error = f"URL is invalid"
    else:
        # data sanity check passed
        # initiate_task()
        # -> invokes celery to push a crawling task
        # -> saves task status to the database
        error = initiate_task(url, 'scrape_markup_task', url_id=url_id, website_id=website_id)
        if error is None:
            _flash_info_alert("Process in queue")
            return redirect(url_for('crawl.get_status'))
    _flash_error_alert(error)
    return redirect('crawl.get_status')

@bp.route('/scraped-markup/<url_id>/<markup_id>', methods=('GET',))
@login_required
def view_scraped_content(url_id, markup_id):
    db = get_db()
    error = None


    titles = db.execute(
        """
        SELECT title FROM title_tag
        WHERE url_id = ?
        """, (url_id,)
    ).fetchall()

    h1 = db.execute(
        """
        SELECT h1 FROM h1_tag
        WHERE url_id = ?
        """, (url_id,)
    ).fetchall()

    h2 = db.execute(
        """
        SELECT h2 FROM h2_tag
        WHERE url_id = ?
        """, (url_id,)
    ).fetchall()

    alt = db.execute(
        """
        SELECT alt_text, img_tag FROM img_alt_tag
        WHERE url_id = ?
        """, (url_id,)
    ).fetchall()

    missing_alt = db.execute(
        """
        SELECT count(*) as cnt FROM img_alt_tag
        WHERE url_id = ? AND alt_text IS NULL;
        """, (url_id,)
    ).fetchone()

    return render_template('crawl/scrape-markup.html', alt=alt, h1=h1, h2=h2, titles=titles, missing_alt=missing_alt)

@bp.route('/scrape-markup-bulk', methods=('GET',))
@login_required
def scrape_markup_bulk():
    return render_template('crawl/scrape-markup-bulk.html')

@bp.route('/check-status', methods=('GET',))
@login_required
def get_status():

    db = get_db()

    rows = db.execute(
        """
        SELECT c.status_id, c.task_id, s.name, w.website_url, w.website_id, i.url_id, i.url_address
        FROM check_status c
        INNER JOIN status_type s ON c.status_type_id = s.status_type_id
        INNER JOIN website w ON c.website_id = w.website_id
        LEFT JOIN internal_url i ON c.url_id = i.url_id
        """
    ).fetchall()
    return render_template("crawl/check-status.html", rows=rows)

@bp.route('/check-status/<task_id>', methods=('GET',))
@login_required
def get_task_state(task_id):
    db = get_db()
    res = db.execute(
        """
        SELECT s.name, c.status_type_id
        FROM check_status c
        INNER JOIN status_type s ON c.status_type_id = s.status_type_id
        WHERE c.task_id = ?
        """, (task_id,)
    ).fetchone()

    if res and res['name'] == 'PENDING':
        result = celery_global_instance.AsyncResult(task_id)
        response = db.execute(
            "SELECT status_type_id FROM status_type WHERE name = ?", (result.state,)
        ).fetchone()
        if response:
            db.execute('UPDATE check_status SET status_type_id = ? WHERE task_id = ?', (response['status_type_id'], task_id))
            db.commit()
    
    row = db.execute(
        """
        SELECT c.status_id, c.task_id, s.name, w.website_url, w.website_id, s.status_type_id
        FROM check_status c
        INNER JOIN status_type s ON c.status_type_id = s.status_type_id
        INNER JOIN website w ON c.website_id = w.website_id
        WHERE c.task_id = ?
        """, (task_id,)
    ).fetchone()
    
    return render_template("crawl/check-status-id.html", row=row)


@bp.route('/delete/<website_id>', methods=('POST',))
@login_required
def delete_website_url(website_id):
    db = get_db()
    
    db.execute("DELETE FROM website WHERE website_id = ?", (website_id,))

    db.commit()

    _flash_info_alert("Deleted the results")

    return redirect(url_for("crawl.get_status")) 






