import uuid

from app.reports.email_sender import MockEmailSender, format_report_email_body
from app.reports.report_generator import ReportRow, ReportSummary


def _sample_summary() -> ReportSummary:
    return ReportSummary(
        job_id=str(uuid.uuid4()),
        total_recommendations=2,
        total_aggressive_estimated_savings_usd=150.0,
        report_rows=[
            ReportRow(
                namespace="payments",
                service_name="checkout-api",
                current_cpu_request_cores=4.0,
                aggressive_cpu_cores=1.2,
                current_mem_request_mib=8192.0,
                aggressive_mem_mib=4096.0,
                aggressive_estimated_weekly_savings_usd=100.0,
            ),
            ReportRow(
                namespace="frontend",
                service_name="web-ui",
                current_cpu_request_cores=2.0,
                aggressive_cpu_cores=1.0,
                current_mem_request_mib=2048.0,
                aggressive_mem_mib=1024.0,
                aggressive_estimated_weekly_savings_usd=50.0,
            ),
        ],
        report_url="https://app.example.com/reports?job_id=abc",
    )


class TestFormatReportEmailBody:
    def test_includes_summary_and_table(self):
        summary = _sample_summary()
        body = format_report_email_body(summary)

        assert "Rightsizing Weekly Report" in body
        assert f"Job ID:                 {summary.job_id}" in body
        assert "Total Recommendations:  2" in body
        assert "Total Estimated Savings: $150.00" in body
        assert "Namespace" in body
        assert "Service" in body
        assert "Current CPU" in body
        assert "Recommended CPU" in body
        assert "checkout-api" in body
        assert "web-ui" in body
        assert "Detailed report: https://app.example.com/reports?job_id=abc" in body


class TestMockEmailSender:
    def test_records_plain_text_report_message(self):
        summary = _sample_summary()
        sender = MockEmailSender()

        sender.send_report(["ops@example.com", "finops@example.com"], summary)

        assert len(sender.sent_messages) == 1
        message = sender.sent_messages[0]
        assert message["recipients"] == ["ops@example.com", "finops@example.com"]
        assert summary.job_id in message["subject"]
        assert "Rightsizing Weekly Report" in message["body"]
        assert "checkout-api" in message["body"]
        assert summary.report_url in message["body"]
