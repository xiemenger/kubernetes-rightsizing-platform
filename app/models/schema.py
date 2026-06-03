import uuid
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import UUID

db = SQLAlchemy()

class Job(db.Model): 
    # 一次 right-sizing analysis run
    # 2026-05-28 运行了一次 recommendation job
    # 一旦 job 跑完， status='completed'
    # job 可以重跑

    __tablename__ = "jobs"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status = db.Column(db.String(20), nullable=False, default="pending")
    # Statuses: 'pending' | 'running' | 'completed' | 'failed'
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True), 
        nullable=False, 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    error = db.Column(db.Text, nullable=True)

    # Cluster-level runs: parallel namespace batches share one parent job
    cluster = db.Column(db.String(255), nullable=True)
    total_batches = db.Column(db.Integer, nullable=True)
    completed_batches = db.Column(db.Integer, nullable=False, default=0)

    recommendations = db.relationship("Recommendation", backref="job", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "job_id": str(self.id),
            "status": self.status,
            "cluster": self.cluster,
            "total_batches": self.total_batches,
            "completed_batches": self.completed_batches,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "error": self.error,
        }

class Recommendation(db.Model): 
    # 某个 container 的 recommendation result
    # one job => many recommendations
    # 2026-05-28 运行了一次 recommendation job 123
    # 产出了 3 条 recommendation 记录
    # 它们共享相同的 job_id=123

    __tablename__ = "recommendations"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = db.Column(UUID(as_uuid=True), db.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    cluster = db.Column(db.String(255), nullable=False)
    namespace = db.Column(db.String(255), nullable=False, index=True)
    pod = db.Column(db.String(255), nullable=False)
    container = db.Column(db.String(255), nullable=False)

    # Current state — cpu unit: core, memory unit: mebibyte
    cpu_request_cores = db.Column(db.Numeric(10, 4), nullable=True)
    mem_request_mib = db.Column(db.Numeric(10, 2), nullable=True)
    cpu_p95_cores = db.Column(db.Numeric(10, 4), nullable=True)
    mem_p95_mib = db.Column(db.Numeric(10, 2), nullable=True)

    # Aggressive vs conservative resource targets
    aggressive_cpu_cores = db.Column(db.Numeric(10, 4), nullable=True)
    conservative_cpu_cores = db.Column(db.Numeric(10, 4), nullable=True)
    aggressive_mem_mib = db.Column(db.Numeric(10, 2), nullable=True)
    conservative_mem_mib = db.Column(db.Numeric(10, 2), nullable=True)

    # Legacy single-target columns (nullable; prefer aggressive/conservative fields)
    rec_cpu_request_cores = db.Column(db.Numeric(10, 4), nullable=True)
    rec_mem_request_mib = db.Column(db.Numeric(10, 2), nullable=True)

    # Actual Cloudability cost (None when missing — never fabricated)
    weekly_cost_usd = db.Column(db.Numeric(10, 4), nullable=True)
    cost_status = db.Column(db.String(20), nullable=False, default="missing")
    savings_estimation_source = db.Column(db.String(30), nullable=False, default="unavailable")

    aggressive_estimated_weekly_savings_usd = db.Column(db.Numeric(10, 4), nullable=True)
    conservative_estimated_weekly_savings_usd = db.Column(db.Numeric(10, 4), nullable=True)

    # Legacy savings columns (nullable)
    estimated_weekly_savings_usd = db.Column(db.Numeric(10, 4), nullable=True)
    savings_pct = db.Column(db.Numeric(5, 2), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": str(self.id),
            "job_id": str(self.job_id),
            "cluster": self.cluster,
            "namespace": self.namespace,
            "pod": self.pod,
            "container": self.container,
            "cpu_request_cores": float(self.cpu_request_cores) if self.cpu_request_cores is not None else None,
            "mem_request_mib": float(self.mem_request_mib) if self.mem_request_mib is not None else None,
            "cpu_p95_cores": float(self.cpu_p95_cores) if self.cpu_p95_cores is not None else None,
            "mem_p95_mib": float(self.mem_p95_mib) if self.mem_p95_mib is not None else None,
            "aggressive_cpu_cores": float(self.aggressive_cpu_cores) if self.aggressive_cpu_cores is not None else None,
            "conservative_cpu_cores": float(self.conservative_cpu_cores) if self.conservative_cpu_cores is not None else None,
            "aggressive_mem_mib": float(self.aggressive_mem_mib) if self.aggressive_mem_mib is not None else None,
            "conservative_mem_mib": float(self.conservative_mem_mib) if self.conservative_mem_mib is not None else None,
            "weekly_cost_usd": float(self.weekly_cost_usd) if self.weekly_cost_usd is not None else None,
            "cost_status": self.cost_status,
            "savings_estimation_source": self.savings_estimation_source,
            "aggressive_estimated_weekly_savings_usd": (
                float(self.aggressive_estimated_weekly_savings_usd)
                if self.aggressive_estimated_weekly_savings_usd is not None
                else None
            ),
            "conservative_estimated_weekly_savings_usd": (
                float(self.conservative_estimated_weekly_savings_usd)
                if self.conservative_estimated_weekly_savings_usd is not None
                else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


