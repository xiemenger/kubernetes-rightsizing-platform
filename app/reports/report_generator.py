import uuid
from dataclasses import dataclass
from typing import List, Optional, Union

from app.models.schema import Recommendation


@dataclass(frozen=True)
class ReportRow:
    """One workload line in the weekly rightsizing report."""
    namespace: str
    workload_name: str
    current_cpu_request_cores: Optional[float]
    cpu_p95_cores: Optional[float]
    aggressive_cpu_cores: Optional[float]
    conservative_cpu_cores: Optional[float]
    current_mem_request_mib: Optional[float]
    mem_p95_mib: Optional[float]
    aggressive_mem_mib: Optional[float]
    conservative_mem_mib: Optional[float]
    aggressive_estimated_weekly_savings_usd: Optional[float]


@dataclass(frozen=True)
class ReportSummary:
    """Weekly rightsizing report summary for email and web delivery."""
    job_id: str
    total_recommendations: int
    total_aggressive_estimated_savings_usd: float
    report_rows: List[ReportRow]
    report_url: str


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def recommendation_to_report_row(rec: Recommendation) -> ReportRow:
    """Map a persisted Recommendation ORM record to a report table row."""
    return ReportRow(
        namespace=rec.namespace,
        workload_name=rec.workload_name,
        current_cpu_request_cores=_to_float(rec.cpu_request_cores),
        cpu_p95_cores=_to_float(rec.cpu_p95_cores),
        aggressive_cpu_cores=_to_float(rec.aggressive_cpu_cores),
        conservative_cpu_cores=_to_float(rec.conservative_cpu_cores),
        current_mem_request_mib=_to_float(rec.mem_request_mib),
        mem_p95_mib=_to_float(rec.mem_p95_mib),
        aggressive_mem_mib=_to_float(rec.aggressive_mem_mib),
        conservative_mem_mib=_to_float(rec.conservative_mem_mib),
        aggressive_estimated_weekly_savings_usd=_to_float(
            rec.aggressive_estimated_weekly_savings_usd
        ),
    )


def _savings_sort_key(row: ReportRow):
    savings = row.aggressive_estimated_weekly_savings_usd
    if savings is None:
        return (1, 0.0)
    return (0, -savings)


def generate_report_summary(
    job_id: Union[uuid.UUID, str],
    recommendations: List[Recommendation],
    report_base_url: str = "https://rightsizing.example.com/reports",
) -> ReportSummary:
    """
    Build a report summary from Recommendation records.

    Rows are sorted by aggressive_estimated_weekly_savings_usd descending
    (highest savings first). Rows with no savings estimate appear last.
    """
    job_id_str = str(job_id)
    report_rows = sorted(
        [recommendation_to_report_row(rec) for rec in recommendations],
        key=_savings_sort_key,
    )

    total_savings = sum(
        row.aggressive_estimated_weekly_savings_usd or 0.0
        for row in report_rows
        if row.aggressive_estimated_weekly_savings_usd is not None
    )

    report_url = f"{report_base_url.rstrip('/')}?job_id={job_id_str}"

    return ReportSummary(
        job_id=job_id_str,
        total_recommendations=len(report_rows),
        total_aggressive_estimated_savings_usd=round(total_savings, 2),
        report_rows=report_rows,
        report_url=report_url,
    )
