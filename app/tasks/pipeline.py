import os
import uuid
from typing import List, Optional

from celery import Celery

from app.config import Config

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery(
    "right_sizing",
    broker=redis_url,
    backend=redis_url,
)

celery_app.conf.update(
    task_acks_late=Config.CELERY.get("task_acks_late", True),
    worker_prefetch_multiplier=Config.CELERY.get("worker_prefetch_multiplier", 1),
)

DEMO_REPORT_RECIPIENTS = ["ops@example.com", "finops@example.com"]
DEMO_REPORT_BASE_URL = "/api/v1/recommendations"


def _persist_recommendation(job_id: uuid.UUID, rec) -> None:
    """Map an engine Recommendation to a database row."""
    from app.models.schema import db, Recommendation as RecommendationRecord

    db.session.add(
        RecommendationRecord(
            job_id=job_id,
            cluster=rec.cluster,
            namespace=rec.namespace,
            pod=rec.service_name,
            container=rec.service_name,
            cpu_request_cores=rec.cpu_request_cores,
            mem_request_mib=rec.mem_request_mib,
            cpu_p95_cores=rec.cpu_p95_cores,
            mem_p95_mib=rec.mem_p95_mib,
            aggressive_cpu_cores=rec.aggressive_cpu_cores,
            conservative_cpu_cores=rec.conservative_cpu_cores,
            aggressive_mem_mib=rec.aggressive_mem_mib,
            conservative_mem_mib=rec.conservative_mem_mib,
            weekly_cost_usd=rec.weekly_cost_usd,
            cost_status=rec.cost_status,
            savings_estimation_source=rec.savings_estimation_source,
            aggressive_estimated_weekly_savings_usd=rec.aggressive_estimated_weekly_savings_usd,
            conservative_estimated_weekly_savings_usd=rec.conservative_estimated_weekly_savings_usd,
        )
    )


def _execute_rightsizing_for_namespaces(
    job_id: uuid.UUID,
    cluster: str,
    namespaces: Optional[List[str]],
) -> int:
    """
    Run collectors and RightsizerEngine for a namespace scope.

    Returns the number of recommendations persisted.
    """
    from app.collectors import (
        MockAwsPricingCollector,
        MockCloudabilityCollector,
        MockKubernetesCollector,
        MockPrometheusCollector,
    )
    from app.engine.rightsizer import RecommendationConfig, RightsizerEngine

    kubernetes_collector = MockKubernetesCollector(cluster_name=cluster)
    prometheus_collector = MockPrometheusCollector()
    cloudability_collector = MockCloudabilityCollector()
    aws_pricing_collector = MockAwsPricingCollector()

    services = kubernetes_collector.collect_services(namespaces=namespaces)
    if not services:
        return 0

    metrics = prometheus_collector.collect_metrics(services)
    costs = cloudability_collector.collect_costs(services)
    pricing = aws_pricing_collector.get_pricing("us-east-1")

    engine = RightsizerEngine(RecommendationConfig.defaults())
    recommendations = engine.generate_recommendations(
        services,
        metrics,
        costs,
        pricing=pricing,
    )

    for rec in recommendations:
        _persist_recommendation(job_id, rec)

    return len(recommendations)


def _send_completion_report(job_id: str) -> None:
    """Generate cluster-level report summary and send demo notification email."""
    from app.models.schema import Recommendation, db
    from app.reports.email_sender import MockEmailSender
    from app.reports.report_generator import generate_report_summary

    recommendations = Recommendation.query.filter_by(
        job_id=uuid.UUID(job_id)
    ).all()
    summary = generate_report_summary(
        job_id,
        recommendations,
        report_base_url=DEMO_REPORT_BASE_URL,
    )
    MockEmailSender().send_report(DEMO_REPORT_RECIPIENTS, summary)


def _mark_batch_completed(job_id: str) -> None:
    """Increment batch counter; mark parent job completed when all batches finish."""
    from app.models.schema import Job, db

    job = db.session.get(Job, uuid.UUID(job_id))
    if not job:
        return

    if job.status == "completed":
        return

    job.completed_batches = (job.completed_batches or 0) + 1
    all_batches_done = (
        job.total_batches and job.completed_batches >= job.total_batches
    )

    if all_batches_done:
        job.status = "completed"
        job.error = None
        db.session.commit()
        _send_completion_report(job_id)
    else:
        db.session.commit()


def _mark_job_failed(job_id: str, error: str) -> None:
    from app.models.schema import Job, db

    job = db.session.get(Job, uuid.UUID(job_id))
    if job:
        job.status = "failed"
        job.error = error
        db.session.commit()


@celery_app.task(bind=True, max_retries=3)
def run_rightsizing_batch_job(
    self, job_id: str, cluster: str, namespaces: List[str]
):
    """
    Process one namespace batch for a cluster-level parent job.

    Collects services only in the supplied namespaces, runs the engine,
    and persists recommendations under the shared parent job_id.
    """
    from app import create_app
    from app.models.schema import db

    app = create_app()
    with app.app_context():
        try:
            _execute_rightsizing_for_namespaces(
                uuid.UUID(job_id),
                cluster,
                namespaces,
            )
            db.session.commit()
            _mark_batch_completed(job_id)
        except Exception as e:
            db.session.rollback()
            _mark_job_failed(job_id, str(e))
            raise


@celery_app.task(bind=True, max_retries=3)
def run_rightsizing_job(self, job_id: str):
    """
    Legacy single-task rightsizing run (entire cluster in one worker).

    Prefer schedule_cluster_rightsizing_run() for production-style namespace-batch parallelism.
    """
    from app import create_app
    from app.collectors import MockKubernetesCollector
    from app.models.schema import Job, db

    app = create_app()
    with app.app_context():
        job = db.session.get(Job, uuid.UUID(job_id))
        if not job:
            return f"Job {job_id} not found"

        cluster = job.cluster or MockKubernetesCollector().cluster_name

        try:
            job.status = "running"
            job.error = None
            db.session.commit()

            _execute_rightsizing_for_namespaces(
                job.id,
                cluster,
                namespaces=None,
            )

            job = db.session.get(Job, uuid.UUID(job_id))
            if job and job.status != "completed":
                job.status = "completed"
                db.session.commit()
                _send_completion_report(job_id)

        except Exception as e:
            db.session.rollback()
            _mark_job_failed(job_id, str(e))
            raise
