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


# Compact column headers for plain-text email (request → P95 → aggressive/conservative recs).
REPORT_TABLE_HEADERS = [
    ("Namespace", 12),
    ("Workload", 14),
    ("CPU Req", 7),
    ("CPU P95", 7),
    ("Agg CPU", 7),
    ("Cons CPU", 8),
    ("Mem Req", 8),
    ("Mem P95", 8),
    ("Agg Mem", 8),
    ("Cons Mem", 8),
    ("Savings", 8),
]


def format_report_email_body(summary: ReportSummary) -> str:
    """Build a plain-text weekly rightsizing report email body with a data table."""
    headers = REPORT_TABLE_HEADERS
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
        row.workload_name,
        row.current_cpu_request_cores,
        row.cpu_p95_cores,
        row.aggressive_cpu_cores,
        row.conservative_cpu_cores,
        row.current_mem_request_mib,
        row.mem_p95_mib,
        row.aggressive_mem_mib,
        row.conservative_mem_mib,
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
