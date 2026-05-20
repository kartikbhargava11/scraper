import re
from functools import partial
from flask import flash
from crawler.db import get_db


from crawler.task import scrape_links_task, scrape_markup_task

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
            task = scrape_markup_task.delay(url, url_id, website_id)
        elif mode == 'scrape_links_task':
            task = scrape_links_task.delay(url)
            # use the passed URL to extract its primary key from the database
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


        # extract the status_type_id of the 'PENDING' status to use it in saving the status of the newly added celery task in the database
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
                # if url_id is not present, it ok for fresh websites (as they don't have internal_urls in the beginning)
                db.execute(
                    "INSERT INTO check_status (status_type_id, website_id, task_id) VALUES (?,?,?)",
                    (status_type_id['status_type_id'], website_id, task.id)
                )
        else:
            db.rollback()
            raise db.Error
    # in the case of integrity exception, stop the processing
    except (db.DatabaseError, db.Error, db.IntegrityError):
        error = "Database Error"
    else:
        # no exceptions raised
        db.commit()
    return error


_flash_success_alert = partial(flash, category='success')

_flash_info_alert = partial(flash, category='info')

_flash_error_alert = partial(flash, category='error')

