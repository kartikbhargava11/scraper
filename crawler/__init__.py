import os
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
        DEBUG=os.environ['DEBUG'],
        SECRET_KEY=os.environ['SECRET_KEY'],
        DATABASE=os.path.join(app.instance_path, 'crawler.sqlite'),
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
