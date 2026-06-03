import uuid

from flask import Blueprint, jsonify, request
from app.models.schema import db, Job
from app.scheduler.cluster_run import schedule_cluster_rightsizing_run
from app.tasks.pipeline import run_rightsizing_job

jobs_bp = Blueprint("jobs", __name__, url_prefix="/api/v1/jobs")

@jobs_bp.route("", methods=["POST"])
def create_job():
    """
    POST /api/v1/jobs

    Cluster-level run (production-style):
      {"cluster": "prod-us-east-1", "whitelist": [...], "blacklist": [...], "batch_size": 50}
      → one parent job, one Celery task per namespace batch

    Legacy demo run (no body):
      → single Celery task processes all mock services
    """
    try:
        data = request.get_json(silent=True) or {}
        cluster = data.get("cluster")

        if cluster:
            job_id = schedule_cluster_rightsizing_run(
                cluster=cluster,
                whitelist=data.get("whitelist"),
                blacklist=data.get("blacklist"),
                batch_size=data.get("batch_size", 50),
            )
            job = db.session.get(Job, uuid.UUID(job_id))
            return jsonify(job.to_dict()), 202

        job = Job(status="pending")
        db.session.add(job)
        db.session.commit()

        run_rightsizing_job.delay(str(job.id))

        return jsonify(job.to_dict()), 202

    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
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
