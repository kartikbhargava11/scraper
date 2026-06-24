import sqlite3
from datetime import datetime

import click
from flask import current_app, g
# g is a special object that is unique to each request. It is used to store data that might be
# accessed by multiple functions during the request

# current_app is another special object that points to the Flask app handling the request

def get_db():
    if 'db' not in g:
        # the database connection is stored and reused instead of creating a new connection if get_db() is called
        # a second time in the same request

        g.db = sqlite3.connect( #  establishes a connection
            current_app.config['DATABASE'],  # connection is established to the file path pointed here. This file won't have to exist yet and won't until database is initailized
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False
        )

        g.db.row_factory = sqlite3.Row # tells the connection to return rows to behave like Python dictionary. This allows us to access columns by names

    return g.db # return the connection

def close_db(e=None):
    # if the connection to databases exists, this function terminates it
    # we have configured in the app to invoke close_db() after each request
    db = g.pop('db', None)

    if db is not None:
        db.close()

    
def init_db():
    db = get_db()

    with current_app.open_resource('schema.sql') as f: # opens a file to execute sql queries (create tables)
        db.executescript(f.read().decode('utf8'))

@click.command('init-db') # defines a command line command called 'init-db' to initialize the db & run the sql queries
def init_db_command():
    init_db()
    click.echo("Initialized the database")

sqlite3.register_converter(
    "timestamp", lambda v: datetime.fromisoformat(v.decode())
)

def init_app(app):
    app.teardown_appcontext(close_db) # tells the flask to call close_db function after returning the response. [clean-up]
    app.cli.add_command(init_db_command) # add a custom commmand that can be called with the flask command