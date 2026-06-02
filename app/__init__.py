from flask import Flask
from app.config import Config
from app.models.schema import db
from app.api import health_bp, jobs_bp, recommendations_bp

def create_app(config_class=Config) -> Flask:
    """
    Flask Application Factory.
    Loads config, initializes SQLAlchemy, registers blueprints, and ensures schema exists.
    """
    app = Flask(__name__)    # API layer 创建 Flask application 实例， 当前 Python module 的名字， 这里是app
    app.config.from_object(config_class)   # 加载配置。
    
    # Initialize DB
    db.init_app(app) # 把 SQLAlchemy 绑定到 Flask app。
    
    # Register Blueprints
    app.register_blueprint(health_bp) 
    app.register_blueprint(jobs_bp) 
    app.register_blueprint(recommendations_bp)
    
    # Create tables automatically for interview / setup convenience
    with app.app_context(): # 进入 Flask app environment
        db.create_all()
        #create_all() 会自动生成：
        # CREATE TABLE jobs ...
        # CREATE TABLE recommendations ... 
        # 这在生产环境不推荐，但适合演示。
        
    return app
