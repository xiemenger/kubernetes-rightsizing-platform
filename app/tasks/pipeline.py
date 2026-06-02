import os
import uuid
from celery import Celery

from app.config import Config

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery(
    "right_sizing",
    broker=redis_url, # broker 是任务队列，Flask 把任务放进去。 Broker ≈ Message Queue + Message Router
    backend=redis_url # backend 是记录结果的地方。
)

celery_app.conf.update(
    task_acks_late=Config.CELERY.get("task_acks_late", True),  # 把job执行成功在ack
    worker_prefetch_multiplier=Config.CELERY.get("worker_prefetch_multiplier", 1), # 一次只拿一个任务，适合内存小的情况， Worker1 → Task1
) # right_sizing job 可能是cluster A, 2分钟， cluster b 30秒等。 时耗差异很大，如果取太多，某个worker可能囤积大量任务。


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


@celery_app.task(bind=True, max_retries=3) # 把普通 Python 函数注册成 Celery task。bind=True 让函数里可以用 self，以后可以调用：
def run_rightsizing_job(self, job_id: str): # Celery task 的参数 job_id 是 job.id， 即一个 UUID。
    """
    Asynchronous Celery task that executes the rightsizing analysis.
    Updates the jobs table lifecycle states (pending -> running -> completed/failed).
    """
    from app import create_app
    from app.collectors import (
        MockAwsPricingCollector,
        MockCloudabilityCollector,
        MockKubernetesCollector,
        MockPrometheusCollector,
    )
    from app.engine.rightsizer import RecommendationConfig, RightsizerEngine
    from app.models.schema import db, Job

    app = create_app()
    with app.app_context():
        job = db.session.get(Job, job_id)
        if not job:
            return f"Job {job_id} not found"

        try:
            job.status = "running"
            job.error = None
            db.session.commit()

            kubernetes_collector = MockKubernetesCollector()
            prometheus_collector = MockPrometheusCollector()
            cloudability_collector = MockCloudabilityCollector()
            aws_pricing_collector = MockAwsPricingCollector()

            services = kubernetes_collector.collect_services()
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
                _persist_recommendation(job.id, rec)

            job.status = "completed"
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            job = db.session.get(Job, job_id)
            if job:
                job.status = "failed"
                job.error = str(e)
                db.session.commit()
            raise
