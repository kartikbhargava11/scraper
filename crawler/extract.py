from flask import (
    Blueprint, g, redirect, render_template, request, url_for
)
from crawler.auth import login_required
from crawler.helper import check_url, flash_error_alert, flash_info_alert, create_crawl_job
from crawler.db import get_db
from crawler.task import extract_computer_hardware_info_task

bp = Blueprint('extract', __name__, url_prefix='/extract')

@bp.route('/computer-hardware', methods=('GET', 'POST'))
@login_required
def computer_hardware():
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

                db.commit()

                task = extract_computer_hardware_info_task.delay(job_id)

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

            else:
                flash_info_alert('Processing....')
                return redirect(url_for('crawl.get_status'))
        
    return render_template('extract/computer-hardware.html')