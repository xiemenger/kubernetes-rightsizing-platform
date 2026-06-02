from flask import Blueprint, jsonify
from app.models.schema import db, Job
from app.tasks.pipeline import run_rightsizing_job

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/v1/jobs")

@jobs_bp.route("", methods=["POST"])
def create_job():
    """
    POST /api/v1/jobs
    Creates a new Job in PostgreSQL database with status 'pending'
    and triggers the Celery worker task asynchronously.
    """
    try:
        # Create and persist a new job row
        job = Job(status="pending")
        db.session.add(job)
        db.session.commit()
        
        # Enqueue the Celery task (passing job_id as string)
        run_rightsizing_job.delay(str(job.id))
        
        # Return HTTP 202 Accepted as task is executing in background
        return jsonify(job.to_dict()), 202
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to schedule job", "details": str(e)}), 500

@jobs_bp.route("/<uuid:job_id>", methods=["GET"])
def get_job(job_id):
    """
    GET /api/v1/jobs/<job_id>
    Polls status, error (if any), and timestamp info of a specific job.
    """
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
        
    return jsonify(job.to_dict()), 200
