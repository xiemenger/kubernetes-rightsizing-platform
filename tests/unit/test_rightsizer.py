import pytest
from typing import Optional

from app.collectors import (
    AwsResourcePricing,
    ServiceCostInfo,
    ServiceMetrics,
    ServiceSpecification,
)
from app.engine.rightsizer import Recommendation, RecommendationConfig, RightsizerEngine

CLUSTER = "prod-us-east"
NAMESPACE = "payments"
SERVICE = "checkout-api"

AWS_PRICING_FALLBACK = AwsResourcePricing(
    region="us-east-1",
    cpu_cost_per_core_hour=0.04,
    mem_cost_per_mib_hour=0.000004,
)


@pytest.fixture
def default_config() -> RecommendationConfig:
    return RecommendationConfig(
        aggressive_headroom_pct=20.0,
        conservative_headroom_pct=50.0,
        min_cpu_cores=0.1,
        min_memory_mib=128.0,
    )


@pytest.fixture
def engine(default_config: RecommendationConfig) -> RightsizerEngine:
    return RightsizerEngine(default_config)


def run_engine(
    engine: RightsizerEngine,
    *,
    cpu_request: float,
    mem_request: float,
    cpu_p95_cores: float,
    mem_p95_mib: float,
    weekly_cost: Optional[float] = 100.0,
    pricing: Optional[AwsResourcePricing] = None,
) -> Recommendation:
    """Build collector inputs and return the single recommendation."""
    spec = ServiceSpecification(
        CLUSTER, NAMESPACE, SERVICE, cpu_request, mem_request
    )
    metrics = [
        ServiceMetrics(CLUSTER, NAMESPACE, SERVICE, cpu_p95_cores, mem_p95_mib)
    ]
    costs = (
        []
        if weekly_cost is None
        else [ServiceCostInfo(CLUSTER, NAMESPACE, SERVICE, weekly_cost)]
    )

    recommendations = engine.generate_recommendations(
        [spec], metrics, costs, pricing=pricing
    )
    assert len(recommendations) == 1
    return recommendations[0]


class TestAggressiveVsConservative:
    def test_aggressive_is_smaller_than_conservative(self, engine):
        rec = run_engine(
            engine,
            cpu_request=2.0,
            mem_request=2048.0,
            cpu_p95_cores=1.0,
            mem_p95_mib=1024.0,
        )

        assert rec.aggressive_cpu_cores < rec.conservative_cpu_cores
        assert rec.aggressive_mem_mib < rec.conservative_mem_mib
        assert rec.aggressive_cpu_cores == pytest.approx(1.2)
        assert rec.conservative_cpu_cores == pytest.approx(1.5)
        assert rec.aggressive_mem_mib == pytest.approx(1228.8)
        assert rec.conservative_mem_mib == pytest.approx(1536.0)


class TestCloudabilityActualCost:
    def test_actual_cost_uses_cloudability_for_savings(self, engine):
        rec = run_engine(
            engine,
            cpu_request=2.0,
            mem_request=2048.0,
            cpu_p95_cores=1.0,
            mem_p95_mib=1024.0,
            weekly_cost=100.0,
        )

        assert rec.weekly_cost_usd == 100.0
        assert rec.cost_status == "actual"
        assert rec.savings_estimation_source == "cloudability"


class TestMissingActualCost:
    def test_savings_unavailable_without_aws_pricing_fallback(self, engine):
        rec = run_engine(
            engine,
            cpu_request=2.0,
            mem_request=2048.0,
            cpu_p95_cores=1.0,
            mem_p95_mib=1024.0,
            weekly_cost=None,
        )

        assert rec.weekly_cost_usd is None
        assert rec.cost_status == "missing"
        assert rec.savings_estimation_source == "unavailable"
        assert rec.aggressive_estimated_weekly_savings_usd is None
        assert rec.conservative_estimated_weekly_savings_usd is None

    def test_savings_use_aws_pricing_when_cloudability_cost_missing(self, engine):
        rec = run_engine(
            engine,
            cpu_request=2.0,
            mem_request=2048.0,
            cpu_p95_cores=1.0,
            mem_p95_mib=1024.0,
            weekly_cost=None,
            pricing=AWS_PRICING_FALLBACK,
        )

        assert rec.weekly_cost_usd is None
        assert rec.cost_status == "missing"
        assert rec.savings_estimation_source == "aws_node_pricing"
        assert rec.aggressive_estimated_weekly_savings_usd is not None
        assert rec.conservative_estimated_weekly_savings_usd is not None


class TestOverProvisionedWorkload:
    def test_recommendations_reduce_resources_with_positive_savings(self, engine):
        rec = run_engine(
            engine,
            cpu_request=4.0,
            mem_request=8192.0,
            cpu_p95_cores=1.0,
            mem_p95_mib=2048.0,
            weekly_cost=200.0,
        )

        assert rec.aggressive_cpu_cores < rec.cpu_request_cores
        assert rec.conservative_cpu_cores < rec.cpu_request_cores
        assert rec.aggressive_estimated_weekly_savings_usd > 0
        assert rec.conservative_estimated_weekly_savings_usd > 0
        assert (
            rec.aggressive_estimated_weekly_savings_usd
            > rec.conservative_estimated_weekly_savings_usd
        )


class TestUnderProvisionedWorkload:
    def test_recommendations_increase_resources_with_negative_savings(self, engine):
        rec = run_engine(
            engine,
            cpu_request=1.0,
            mem_request=1024.0,
            cpu_p95_cores=2.0,
            mem_p95_mib=2048.0,
            weekly_cost=100.0,
        )

        assert rec.aggressive_cpu_cores > rec.cpu_request_cores
        assert rec.conservative_cpu_cores > rec.cpu_request_cores
        assert rec.aggressive_estimated_weekly_savings_usd < 0
        assert rec.conservative_estimated_weekly_savings_usd < 0


class TestCustomRecommendationConfig:
    @pytest.fixture
    def custom_engine(self) -> RightsizerEngine:
        config = RecommendationConfig(
            aggressive_headroom_pct=10.0,
            conservative_headroom_pct=100.0,
            min_cpu_cores=0.1,
            min_memory_mib=128.0,
        )
        return RightsizerEngine(config)

    def test_custom_config_drives_recommendations(self, custom_engine):
        rec = run_engine(
            custom_engine,
            cpu_request=2.0,
            mem_request=2048.0,
            cpu_p95_cores=1.0,
            mem_p95_mib=1024.0,
        )

        assert rec.aggressive_cpu_cores == pytest.approx(1.1)
        assert rec.conservative_cpu_cores == pytest.approx(2.0)
        assert rec.aggressive_mem_mib == pytest.approx(1126.4)
        assert rec.conservative_mem_mib == pytest.approx(2048.0)
