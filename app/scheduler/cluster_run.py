import os
from typing import List, Optional

from app.collectors.kubernetes import MockKubernetesCollector
from app.scheduler.batching import chunk_namespaces
from app.scheduler.namespace_selector import select_namespaces


def discover_namespaces(cluster: str) -> List[str]:
    """Return namespaces present in the cluster (mock discovery for demo)."""
    collector = MockKubernetesCollector(cluster_name=cluster)
    return collector.list_namespaces()


def schedule_cluster_rightsizing_run(
    cluster: str,
    whitelist: Optional[List[str]] = None,
    blacklist: Optional[List[str]] = None,
    batch_size: int = 50,
) -> str:
    """
    Orchestrate a cluster-level rightsizing run with namespace-batch parallelism.

    Creates one parent Job, discovers and filters namespaces, splits into batches,
    and enqueues one Celery task per batch. All recommendations share the parent job_id.
    Report generation and notification remain cluster-level (after all batches complete).

    Returns:
        Parent job_id as a string.
    """
    from app.models.schema import Job, db
    from app.tasks.pipeline import run_rightsizing_batch_job

    job = Job(status="pending", cluster=cluster)
    db.session.add(job)
    db.session.flush()

    all_namespaces = discover_namespaces(cluster)
    namespaces = select_namespaces(all_namespaces, whitelist=whitelist, blacklist=blacklist)
    batches = chunk_namespaces(namespaces, batch_size=batch_size)

    job.total_batches = len(batches)
    job.completed_batches = 0

    if not batches:
        job.status = "completed"
        db.session.commit()
        return str(job.id)

    job.status = "running"
    db.session.commit()

    for batch in batches:
        run_rightsizing_batch_job.delay(str(job.id), cluster, batch)

    return str(job.id)


def _parse_csv_env(name: str) -> Optional[List[str]]:
    """Parse a comma-separated environment variable into a list of strings."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or None


def main() -> None:
    """
    Kubernetes CronJob / Job entrypoint.

    Reads scheduler configuration from environment variables and starts a
    cluster-level rightsizing run via schedule_cluster_rightsizing_run().
    """
    cluster = os.environ.get("CLUSTER_NAME", "prod-us-east-1")
    whitelist = _parse_csv_env("NAMESPACE_WHITELIST")
    blacklist = _parse_csv_env("NAMESPACE_BLACKLIST")
    if blacklist is None:
        blacklist = ["kube-system"]

    batch_size = int(os.environ.get("BATCH_SIZE", "50"))

    from app import create_app

    app = create_app()
    with app.app_context():
        job_id = schedule_cluster_rightsizing_run(
            cluster=cluster,
            whitelist=whitelist,
            blacklist=blacklist,
            batch_size=batch_size,
        )

    print("=== Cluster rightsizing scheduled ===")
    print(f"cluster:    {cluster}")
    print(f"whitelist:  {whitelist if whitelist is not None else '(none)'}")
    print(f"blacklist:  {blacklist}")
    print(f"batch_size: {batch_size}")
    print(f"job_id:     {job_id}")


if __name__ == "__main__":
    main()
