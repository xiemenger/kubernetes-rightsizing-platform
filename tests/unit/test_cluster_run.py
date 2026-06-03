import uuid
from unittest.mock import patch

import pytest

from app.models.schema import Job, db
from app.scheduler.batching import chunk_namespaces
from app.scheduler.cluster_run import (
    _parse_csv_env,
    discover_namespaces,
    schedule_cluster_rightsizing_run,
)
from app.scheduler.namespace_selector import select_namespaces


class TestParseCsvEnv:
    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("TEST_CSV", raising=False)
        assert _parse_csv_env("TEST_CSV") is None

    def test_parses_comma_separated_values(self, monkeypatch):
        monkeypatch.setenv("TEST_CSV", " payments, checkout ,catalog ")
        assert _parse_csv_env("TEST_CSV") == ["payments", "checkout", "catalog"]


class TestDiscoverNamespaces:
    def test_returns_mock_cluster_inventory(self):
        namespaces = discover_namespaces("prod-us-east-1")
        assert "payments" in namespaces
        assert "checkout" in namespaces
        assert "kube-system" in namespaces


class TestScheduleClusterRightsizingRun:
    @patch("app.tasks.pipeline.run_rightsizing_batch_job.delay")
    def test_creates_parent_job_and_enqueues_batches(self, mock_delay, app):
        with app.app_context():
            job_id = schedule_cluster_rightsizing_run(
                cluster="prod-us-east-1",
                blacklist=["kube-system"],
                batch_size=3,
            )
            job = db.session.get(Job, uuid.UUID(job_id))

        assert job is not None
        assert job.cluster == "prod-us-east-1"
        assert job.status == "running"
        assert job.total_batches == mock_delay.call_count
        assert job.total_batches >= 1
        assert mock_delay.call_count == job.total_batches

        first_call = mock_delay.call_args_list[0]
        assert first_call[0][0] == job_id
        assert first_call[0][1] == "prod-us-east-1"
        assert isinstance(first_call[0][2], list)
        assert len(first_call[0][2]) <= 3

    @patch("app.tasks.pipeline.run_rightsizing_batch_job.delay")
    def test_completes_immediately_when_no_namespaces_after_filter(self, mock_delay, app):
        with app.app_context():
            job_id = schedule_cluster_rightsizing_run(
                cluster="prod-us-east-1",
                whitelist=["nonexistent-namespace"],
            )
            job = db.session.get(Job, uuid.UUID(job_id))

        assert job.status == "completed"
        assert job.total_batches == 0
        mock_delay.assert_not_called()

    def test_filter_and_batch_helpers_align(self):
        all_ns = discover_namespaces("prod-us-east-1")
        selected = select_namespaces(all_ns, blacklist=["kube-system"])
        batches = chunk_namespaces(selected, batch_size=50)
        assert sum(len(batch) for batch in batches) == len(selected)
