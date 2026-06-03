import uuid

from app.reports.email_sender import (
    MockEmailSender,
    REPORT_TABLE_HEADERS,
    format_report_email_body,
)
from app.reports.report_generator import ReportRow, ReportSummary


def _sample_summary() -> ReportSummary:
    return ReportSummary(
        job_id=str(uuid.uuid4()),
        total_recommendations=2,
        total_aggressive_estimated_savings_usd=150.0,
        report_rows=[
            ReportRow(
                namespace="payments",
                workload_name="checkout-api",
                current_cpu_request_cores=4.0,
                cpu_p95_cores=1.2,
                aggressive_cpu_cores=1.2,
                conservative_cpu_cores=1.5,
                current_mem_request_mib=8192.0,
                mem_p95_mib=4096.0,
                aggressive_mem_mib=4096.0,
                conservative_mem_mib=5120.0,
                aggressive_estimated_weekly_savings_usd=100.0,
            ),
            ReportRow(
                namespace="frontend",
                workload_name="web-ui",
                current_cpu_request_cores=2.0,
                cpu_p95_cores=1.8,
                aggressive_cpu_cores=1.0,
                conservative_cpu_cores=1.2,
                current_mem_request_mib=2048.0,
                mem_p95_mib=1800.0,
                aggressive_mem_mib=1024.0,
                conservative_mem_mib=1536.0,
                aggressive_estimated_weekly_savings_usd=50.0,
            ),
        ],
        report_url="https://app.example.com/reports?job_id=abc",
    )


class TestFormatReportEmailBody:
    def test_includes_summary_and_expanded_table_headers(self):
        summary = _sample_summary()
        body = format_report_email_body(summary)

        assert "Rightsizing Weekly Report" in body
        assert f"Job ID:                 {summary.job_id}" in body
        assert "Total Recommendations:  2" in body
        assert "Total Estimated Savings: $150.00" in body

        header_names = [name for name, _ in REPORT_TABLE_HEADERS]
        assert header_names == [
            "Namespace",
            "Workload",
            "CPU Req",
            "CPU P95",
            "Agg CPU",
            "Cons CPU",
            "Mem Req",
            "Mem P95",
            "Agg Mem",
            "Cons Mem",
            "Savings",
        ]
        for name in header_names:
            assert name in body

    def test_renders_request_p95_and_both_policy_recommendations(self):
        summary = _sample_summary()
        body = format_report_email_body(summary)

        assert "checkout-api" in body
        assert "web-ui" in body
        # payments row: CPU req 4.00, P95 1.20, agg/cons CPU, mem values
        assert "4.00" in body
        assert "1.50" in body
        assert "5120.00" in body
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
        assert "Agg CPU" in message["body"]
        assert "Cons Mem" in message["body"]
        assert "checkout-api" in message["body"]
        assert summary.report_url in message["body"]
