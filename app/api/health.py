import os
from flask import Blueprint, jsonify
from app.models.schema import db
from redis import Redis

health_bp = Blueprint("health", __name__)

@health_bp.route("/health", methods=["GET"])
@health_bp.route("/api/v1/health", methods=["GET"])
def health():
    """
    Liveness + dependency check.
    Validates connections to PostgreSQL and Redis.
    """
    health_status = {
        "status": "ok",
        "db": "unknown",
        "redis": "unknown"
    }
    
    # Validate DB connection
    try:
        db.session.execute(db.text("SELECT 1"))
        health_status["db"] = "ok"
    except Exception as e:
        health_status["status"] = "error"
        health_status["db"] = f"error: {str(e)}"
        
    # Validate Redis connection
    try:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = Redis.from_url(redis_url, socket_connect_timeout=2)
        r.ping()
        health_status["redis"] = "ok"
    except Exception as e:
        health_status["status"] = "error"
        health_status["redis"] = f"error: {str(e)}"
        
    status_code = 200 if health_status["status"] == "ok" else 500
    return jsonify(health_status), status_code
