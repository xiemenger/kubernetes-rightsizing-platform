from typing import List

from app.reports.report_generator import ReportSummary, ReportRow


def _format_cell(value, width: int) -> str:
    if value is None:
        text = "N/A"
    elif isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    return text[:width].ljust(width)


def format_report_email_body(summary: ReportSummary) -> str:
    """Build a plain-text weekly rightsizing report email body with a data table."""
    headers = [
        ("Namespace", 14),
        ("Service", 18),
        ("Current CPU", 12),
        ("Recommended CPU", 16),
        ("Current Memory", 15),
        ("Recommended Memory", 19),
        ("Estimated Savings", 18),
    ]

    header_line = " | ".join(name.ljust(width) for name, width in headers)
    separator = "-+-".join("-" * width for _, width in headers)

    lines = [
        "Rightsizing Weekly Report",
        "",
        f"Job ID:                 {summary.job_id}",
        f"Total Recommendations:  {summary.total_recommendations}",
        f"Total Estimated Savings: ${summary.total_aggressive_estimated_savings_usd:.2f}",
        "",
        header_line,
        separator,
    ]

    for row in summary.report_rows:
        lines.append(_format_report_row_line(row, headers))

    lines.extend(
        [
            "",
            f"Detailed report: {summary.report_url}",
        ]
    )

    return "\n".join(lines)


def _format_report_row_line(row: ReportRow, headers) -> str:
    values = [
        row.namespace,
        row.service_name,
        row.current_cpu_request_cores,
        row.aggressive_cpu_cores,
        row.current_mem_request_mib,
        row.aggressive_mem_mib,
        row.aggressive_estimated_weekly_savings_usd,
    ]
    cells = [
        _format_cell(value, width) for value, (_, width) in zip(values, headers)
    ]
    return " | ".join(cells)


class MockEmailSender:
    """
    Demo email sender that records outbound report messages instead of using SMTP.
    Production would integrate with SES, SendGrid, or an internal notification service.
    """

    def __init__(self) -> None:
        self.sent_messages: List[dict] = []

    def send_report(self, recipients: List[str], summary: ReportSummary) -> None:
        body = format_report_email_body(summary)
        message = {
            "recipients": recipients,
            "subject": f"Rightsizing Weekly Report — Job {summary.job_id}",
            "body": body,
        }
        self.sent_messages.append(message)
