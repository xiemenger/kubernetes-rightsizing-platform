import uuid
from unittest.mock import patch

from app.models.schema import Job, db
from app.tasks.pipeline import _mark_batch_completed, _send_completion_report


class TestSendCompletionReport:
    @patch("app.reports.email_sender.MockEmailSender")
    def test_sends_report_with_demo_recipients_and_url(self, mock_sender_cls, app):
        with app.app_context():
            job = Job(status="running", cluster="prod-us-east-1")
            db.session.add(job)
            db.session.commit()

            _send_completion_report(str(job.id))

        mock_sender_cls.return_value.send_report.assert_called_once()
        recipients, summary = mock_sender_cls.return_value.send_report.call_args[0]
        assert recipients == ["ops@example.com", "finops@example.com"]
        assert summary.job_id == str(job.id)
        assert summary.report_url == f"/api/v1/recommendations?job_id={job.id}"


class TestMarkBatchCompleted:
    @patch("app.tasks.pipeline._send_completion_report")
    def test_does_not_send_report_until_final_batch(self, mock_send, app):
        with app.app_context():
            job = Job(
                status="running",
                cluster="prod-us-east-1",
                total_batches=2,
                completed_batches=0,
            )
            db.session.add(job)
            db.session.commit()
            job_id = str(job.id)

            _mark_batch_completed(job_id)

            refreshed = db.session.get(Job, uuid.UUID(job_id))
            assert refreshed.completed_batches == 1
            assert refreshed.status == "running"
            mock_send.assert_not_called()

            _mark_batch_completed(job_id)

            refreshed = db.session.get(Job, uuid.UUID(job_id))
            assert refreshed.completed_batches == 2
            assert refreshed.status == "completed"
            mock_send.assert_called_once_with(job_id)

    @patch("app.tasks.pipeline._send_completion_report")
    def test_does_not_send_duplicate_when_already_completed(self, mock_send, app):
        with app.app_context():
            job = Job(
                status="completed",
                cluster="prod-us-east-1",
                total_batches=2,
                completed_batches=2,
            )
            db.session.add(job)
            db.session.commit()
            job_id = str(job.id)

            _mark_batch_completed(job_id)

            refreshed = db.session.get(Job, uuid.UUID(job_id))
            assert refreshed.completed_batches == 2
            mock_send.assert_not_called()
