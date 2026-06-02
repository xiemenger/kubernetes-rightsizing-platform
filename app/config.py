import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/rightsizer"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Celery configuration
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    CELERY = {
        "broker_url": REDIS_URL,
        "result_backend": REDIS_URL,
        "task_acks_late": True,
        "worker_prefetch_multiplier": 1,
    }
