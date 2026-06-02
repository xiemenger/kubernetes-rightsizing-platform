import uuid
from typing import Optional

from app.models.schema import Recommendation
from app.reports.report_generator import (
    ReportRow,
    generate_report_summary,
    recommendation_to_report_row,
)


def _make_recommendation(
    job_id: uuid.UUID,
    *,
    namespace: str,
    service_name: str,
    cpu_request: float = 2.0,
    aggressive_cpu: float = 1.2,
    mem_request: float = 2048.0,
    aggressive_mem: float = 1228.8,
    savings: Optional[float] = 50.0,
) -> Recommendation:
    return Recommendation(
        job_id=job_id,
        cluster="prod-us-east",
        namespace=namespace,
        pod=service_name,
        container=service_name,
        cpu_request_cores=cpu_request,
        mem_request_mib=mem_request,
        cpu_p95_cores=1.0,
        mem_p95_mib=1024.0,
        aggressive_cpu_cores=aggressive_cpu,
        conservative_cpu_cores=1.5,
        aggressive_mem_mib=aggressive_mem,
        conservative_mem_mib=1536.0,
        weekly_cost_usd=100.0,
        cost_status="actual",
        savings_estimation_source="cloudability",
        aggressive_estimated_weekly_savings_usd=savings,
        conservative_estimated_weekly_savings_usd=(
            savings * 0.75 if savings is not None else None
        ),
    )


class TestRecommendationToReportRow:
    def test_maps_orm_fields_to_report_row(self):
        job_id = uuid.uuid4()
        rec = _make_recommendation(job_id, namespace="payments", service_name="checkout-api")

        row = recommendation_to_report_row(rec)

        assert row == ReportRow(
            namespace="payments",
            service_name="checkout-api",
            current_cpu_request_cores=2.0,
            aggressive_cpu_cores=1.2,
            current_mem_request_mib=2048.0,
            aggressive_mem_mib=1228.8,
            aggressive_estimated_weekly_savings_usd=50.0,
        )


class TestGenerateReportSummary:
    def test_builds_summary_sorted_by_savings_descending(self):
        job_id = uuid.uuid4()
        recommendations = [
            _make_recommendation(job_id, namespace="a", service_name="low", savings=25.0),
            _make_recommendation(job_id, namespace="b", service_name="high", savings=200.0),
            _make_recommendation(job_id, namespace="c", service_name="mid", savings=100.0),
        ]

        summary = generate_report_summary(
            job_id,
            recommendations,
            report_base_url="https://app.example.com/reports",
        )

        assert summary.job_id == str(job_id)
        assert summary.total_recommendations == 3
        assert summary.total_aggressive_estimated_savings_usd == 325.0
        assert summary.report_url == f"https://app.example.com/reports?job_id={job_id}"
        assert [row.service_name for row in summary.report_rows] == [
            "high",
            "mid",
            "low",
        ]

    def test_rows_without_savings_sort_last(self):
        job_id = uuid.uuid4()
        recommendations = [
            _make_recommendation(
                job_id,
                namespace="ns-a",
                service_name="with-savings",
                savings=50.0,
            ),
            _make_recommendation(
                job_id,
                namespace="ns-b",
                service_name="no-savings",
                savings=None,
            ),
        ]

        summary = generate_report_summary(job_id, recommendations)

        assert summary.total_aggressive_estimated_savings_usd == 50.0
        assert summary.report_rows[0].service_name == "with-savings"
        assert summary.report_rows[-1].service_name == "no-savings"
        assert summary.report_rows[-1].aggressive_estimated_weekly_savings_usd is None
