import uuid

import pytest
from flask import Flask

from app.api import health_bp, jobs_bp, recommendations_bp
from app.config import Config
from app.models.schema import Job, Recommendation, db


@pytest.fixture
def app():
    """Flask app backed by an in-memory SQLite database for integration tests."""
    flask_app = Flask(__name__)
    flask_app.config.from_object(Config)
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )

    db.init_app(flask_app)
    flask_app.register_blueprint(health_bp)
    flask_app.register_blueprint(jobs_bp)
    flask_app.register_blueprint(recommendations_bp)

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client() # 创建一个测试客户端，用于发送 HTTP 请求到 Flask 应用。


@pytest.fixture
def sample_job(app):
    with app.app_context():
        job = Job(status="completed")
        db.session.add(job)
        db.session.commit()
        yield job


def make_recommendation(
    job_id: uuid.UUID,
    *,  # 后面的参数必须使用关键字参数(keyword argument)， 不能使用位置参数(positional argument)， def func(a, *, b, c):func(1, b=2, c=3)
    namespace: str = "payments",
    workload_name: str = "checkout-api",
    workload_type: str = "Deployment",
    aggressive_estimated_weekly_savings_usd: float = 100.0,
    **overrides, # 接收任意数量的额外 keyword arguments，并放到一个 dict ， 例如func(**kwargs):
) -> Recommendation:
    """Build a Recommendation ORM row with sensible defaults."""
    values = {
        "job_id": job_id,
        "cluster": "prod-us-east",
        "namespace": namespace,
        "workload_name": workload_name,
        "workload_type": workload_type,
        "cpu_request_cores": 2.0,
        "mem_request_mib": 2048.0,
        "cpu_p95_cores": 1.0,
        "mem_p95_mib": 1024.0,
        "aggressive_cpu_cores": 1.2,
        "conservative_cpu_cores": 1.5,
        "aggressive_mem_mib": 1228.8,
        "conservative_mem_mib": 1536.0,
        "weekly_cost_usd": 100.0,
        "cost_status": "actual",
        "savings_estimation_source": "cloudability",
        "aggressive_estimated_weekly_savings_usd": aggressive_estimated_weekly_savings_usd,
        "conservative_estimated_weekly_savings_usd": aggressive_estimated_weekly_savings_usd * 0.75,
    }
    values.update(overrides)
    return Recommendation(**values)


@pytest.fixture
def sample_recommendations(app, sample_job):
    """Two recommendation rows attached to sample_job."""
    with app.app_context():
        rows = [
            make_recommendation(sample_job.id, workload_name="checkout-api"),
            make_recommendation(sample_job.id, workload_name="billing-api", namespace="payments"),
        ]
        db.session.add_all(rows)
        db.session.commit()
        yield rows
