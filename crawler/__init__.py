import os
from zoneinfo import ZoneInfo
from datetime import timezone
from dotenv import load_dotenv

from flask import Flask
# It's a task queue and task scheduler
from celery import Celery, Task

# load variables from .env into system environment variables
load_dotenv()

# global object, tasks will be attched to his global object
celery_global_instance = Celery("tasks", broker=os.environ['BROKER_URL'], backend=os.environ['RESULT_BACKEND'])

# Tell Celery to scan 'task.py' for @shared_task tags immediately
celery_global_instance.autodiscover_tasks(['crawler.task'], force=True)

def create_app(test_config=None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        DEBUG=os.environ.get('DEBUG', False),
        SECRET_KEY=os.environ.get('SECRET_KEY', 'local-secret-key-for-flask-backend'),
        DATABASE=os.path.join(app.instance_path, 'crawler.sqlite'),
        TIMEZONE=os.environ.get('TIMEZONE', 'Asia/Kolkata'),
        DATETIME_FORMAT="%d %b %Y, %-I:%M %p"
    )

    # tie celery into flask app context 
    class FlaskTask(Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    
    # celery_global_instance.conf.update(
        
    # )
    # celery_global_instance.config_from_envvar('CELERY_CONFIG_MODULE')
    # celery_global_instance.config_from_object(app.config['CELERY'])
    celery_global_instance.Task =  FlaskTask
    
    
   
    if test_config is None:
        app.config.from_pyfile('config.py', silent=True)
    else:
        app.config.from_mapping(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    @app.route('/health-check')
    def hello():
        return 'Health Check [OK]'
    
    @app.template_filter('local_datetime')
    def local_datetime(value):
        if value is None:
            return ''
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        local_value = value.astimezone(ZoneInfo(app.config['TIMEZONE']))
        return local_value.strftime(app.config['DATETIME_FORMAT'])
    
    from . import db
    db.init_app(app)

    from . import home
    app.register_blueprint(home.bp)

    from . import auth
    app.register_blueprint(auth.bp)

    from . import crawl
    app.register_blueprint(crawl.bp)

    app.add_url_rule('/', endpoint='index')

    
    return app



    