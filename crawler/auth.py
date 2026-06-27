import functools

from flask import (
    Blueprint, g, redirect, render_template, request, session, url_for
)

from werkzeug.security import check_password_hash, generate_password_hash
from crawler.db import get_db
from crawler.helper import flash_success_alert, flash_error_alert


bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == "POST":
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        db = get_db()
        error = None

        if not username:
            error = "Username is required"
        elif not password:
            password = "Password is required"

        if error is None:
            try:
                db.execute(
                    "INSERT INTO user (username, password) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                db.commit()
            except db.IntegrityError:
                error = f"User {username} already registered"
            else:
                flash_success_alert('Registered Successfully. Please LOG IN!')
                return redirect(url_for("auth.login"))
        
        flash_error_alert(error)

    return render_template('auth/register.html')


@bp.route("/login", methods=('GET', "POST"))
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()

        db = get_db()
        error = None

        user = db.execute(
            'SELECT * FROM user WHERE username = ?', (username, )
        ).fetchone()

        if user is None:
            error = 'Username not found'
        elif not check_password_hash(user['password'], password):
            error = 'Incorrect password'

        if error is None:
            session.clear()
            session['user_id'] = user['user_id']
            next = request.args.get('next') or url_for('index')

            flash_success_alert('Login Successful')
            return redirect(next)
        flash_error_alert(error)

    return render_template('auth/login.html')

@bp.route('/logut')
def logout():
    session.clear()
    flash_success_alert('Logged out Successfully')
    return redirect(url_for('index'))

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')

    if user_id is None:
        g.user = None

    else:
        g.user = get_db().execute(
            'SELECT * FROM user WHERE user_id = ?', (user_id,)
        ).fetchone()

    
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login', next=request.full_path))
        return view(**kwargs)
    
    return wrapped_view
    


