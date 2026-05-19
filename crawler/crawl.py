import re

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, jsonify
)
from werkzeug.exceptions import abort

from crawler.auth import login_required
from crawler.db import get_db
from crawler.task import scrape_links_task, scrape_markup_task
from crawler import celery_global_instance

bp = Blueprint('crawl', __name__, url_prefix="/crawl")

# Helper function to check the validity of the URL, using regular expression
def is_valid_url(url):
    # Regex for a valid URL
    # ^ start anchor
    # https?:// means either http or https
    # (www\.)? means www. is optional 
    # [a-zA-Z0-9.-]+ means accept english letters, numbers, dots and hyphens. Atleast one character should be present
    # \.[a-zA-Z]{2,} means a atleast 2 letters followed by . (ex: .com, .org, .au, .uk, .in)
    # (/.*)? includes sub-directories 
    # $ ending point. no characters or spaces allowed after this point.
    regex = r"^https?://(www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/.*)?$"
    # if the inputted url passed the reg ex, .match() returns the URL if not returns None
    return re.match(regex, url) is not None

# helper function to check the valid range of max_pages and max_depth
def is_valid_range(num, max=5):
    if 1 <= num <= max:
        return num
    return None

def initiate_task(url, mode, **kwargs):
    # variable to use later to show error prompts
    error = None
    task = None
    # get the global sqlite database instance from db.py
    # global instance is saved in flask's global object
    db = get_db()
    url_id = kwargs.get('url_id', None)
    website_id = kwargs.get('website_id', None)

    try:
        if mode == 'scrape_markup_task':
            task = scrape_markup_task.delay(url, url_id)
        elif mode == 'scrape_links_task':
            task = scrape_links_task.delay(url)
            # use the verified URL to extract its primary key from the database
            website_id = db.execute(
                'SELECT website_id FROM website WHERE website_url = ?', (url, )
            ).fetchone()

            # if the primary key of the URL has not been found. it means, it was a new URL
            if website_id is None:

                # save the new url to the database using INSERT sql query
                cur = db.execute(
                    "INSERT INTO website (website_url) VALUES (?)",
                    (url,),
                )
                # extract the newly saved ID using lastrowid [smart]
                website_id = cur.lastrowid
            else:
                # if the primary key of the URL has been found
                print("Seen URL, Fetched it from the database")
                # extract the website id from the tuple extracted from the database
                website_id = website_id['website_id'] # extracting value from index 0 ex: (4,)


        # extract the status_type_id of the 'PENDING' status to use it in saving the status of the celery task in the database
        status_type_id = db.execute(
            'SELECT status_type_id FROM status_type WHERE name = ?', ('PENDING', )
        ).fetchone()

        # a check to make sure a valid status_type_id is retrived
        if status_type_id:
            # save the status of the new task as 'PENDING' in the database
            if url_id:
                # if url_id is present, save it too
                db.execute(
                    "INSERT INTO check_status (status_type_id, website_id, task_id, url_id) VALUES (?,?,?,?)",
                    (status_type_id['status_type_id'], website_id, task.id, url_id)
                )
            else:
                # if url_id is not present, it ok
                db.execute(
                    "INSERT INTO check_status (status_type_id, website_id, task_id) VALUES (?,?,?)",
                    (status_type_id['status_type_id'], website_id, task.id)
                )
    # in the case of integrity exception, stop the processing
    except db.IntegrityError:
        error = f"Website {url} already exist in the database"
    except (db.DatabaseError, db.Error):
        error = "Database Error"
    else:
        # no exceptions raised
        db.commit()
    return error
        
# GET -> returns the HTML page to accept url, max_pages, max_depth
# POST ->
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
            # initiate_task() 
            # -> invokes celery to push a crawling task
            # -> saves task status to the database
            error = initiate_task(url, 'scrape_links_task')
            if error is None:
                # if no error is found, redirect to the page that lists all the tasks
                return redirect(url_for('crawl.get_status')) 
        # if it runs are some exception has been raised or bad input from the user
        flash(error, category='error')
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
        SELECT i.url_id, i.url_address, i.depth, i.website_id, i.created, c.content_id
        FROM internal_url i
        LEFT JOIN content c ON i.url_id = c.url_id
        WHERE i.website_id = ?
        """, (website_id,)
    ).fetchall()

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
        error = initiate_task(url, 'scrape_html_task', url_id=url_id, website_id=website_id)
        if error is None:
            flash("Process in queue", category='info')
            return redirect(url_for('crawl.get_status'))
    flash(error, category='error')
    return redirect('crawl.get_status')

@bp.route('/scraped-markup/<content_id>', methods=('GET',))
@login_required
def view_scraped_content(content_id):
    db = get_db()
    error = None
    row = db.execute(
        """
        SELECT c.content_id, c.html, c.created, c.url_id, i.url_address
        FROM content c
        LEFT JOIN internal_url i ON c.url_id = i.url_id
        WHERE content_id = ?
        """, (content_id,)
    ).fetchone()

    if not row:
        error = 'Not Found'
        flash(error, category='error')
    return render_template('crawl/scrape-markup.html', row=row)

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
    db.execute(
        """
        DELETE FROM website
        WHERE website_id = ?
        """, (website_id,)
    )
    db.execute(
        """
        DELETE FROM internal_url
        WHERE website_id = ?
        """, (website_id,)
    )
    db.execute(
        """
        DELETE FROM check_status
        WHERE website_id = ?
        """, (website_id,)
    )
    db.commit()
    flash("Deleted the results", category='info')
    return redirect(url_for("crawl.get_status")) 


    






