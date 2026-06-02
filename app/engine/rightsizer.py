from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

from app.collectors import (
    ServiceSpecification,
    ServiceMetrics,
    ServiceCostInfo,
    AwsResourcePricing,
)

HOURS_PER_WEEK = 24 * 7


@dataclass(frozen=True)
class RecommendationConfig:
    """
    Tunable policy for rightsizing recommendations.

    Headroom is applied to weekly P95 observed usage (not average usage).
    Aggressive uses lower headroom for cost savings; conservative uses higher
    headroom for stability during traffic spikes.
    """
    aggressive_headroom_pct: float
    conservative_headroom_pct: float
    min_cpu_cores: float
    min_memory_mib: float

    @classmethod
    def defaults(cls) -> "RecommendationConfig":
        return cls(
            aggressive_headroom_pct=20.0, # 适用于 Development，Staging， Cost-sensitive workloads， High-confidence workloads。 因为节省成本优先，接受一定风险 
            conservative_headroom_pct=50.0, # 适用于 Production，High-confidence workloads， Critical services。 因为稳定性优先
            min_cpu_cores=0.1,
            min_memory_mib=128.0,
        )


@dataclass(frozen=True)
class Recommendation:
    """
    Represents a rightsizing recommendation for a Kubernetes service in a cluster.
    """
    cluster: str
    namespace: str
    service_name: str

    # Current state (P95 observed usage from Prometheus)
    cpu_request_cores: float
    cpu_p95_cores: float
    mem_request_mib: float
    mem_p95_mib: float

    # Aggressive vs conservative resource targets
    aggressive_cpu_cores: float
    conservative_cpu_cores: float
    aggressive_mem_mib: float
    conservative_mem_mib: float

    # Actual cost from Cloudability (never fabricated when missing).
    weekly_cost_usd: Optional[float]
    cost_status: str  # "actual" or "missing"

    # Estimated savings and the data source used to compute them.
    # Actual cost and estimated savings are different concepts: savings compare
    # current requests to recommended requests, while weekly_cost_usd is observed spend.
    savings_estimation_source: str  # "cloudability", "aws_node_pricing", or "unavailable"
    aggressive_estimated_weekly_savings_usd: Optional[float]
    conservative_estimated_weekly_savings_usd: Optional[float]


class RightsizerEngine:
    """
    Core Recommendation Engine.
    Corresponds to the domain layer in Clean Architecture: contains pure business logic,
    completely independent of web frameworks (Flask) and database drivers (SQLAlchemy/Postgres).

    Recommendations are calculated as weekly P95 observed usage plus configurable headroom:
    - Aggressive: lower headroom (e.g. 20%) for maximum cost savings.
    - Conservative: higher headroom (e.g. 50%) for stability during usage spikes.
    """

    def __init__(self, config: RecommendationConfig) -> None:
        self._config = config

    def _recommend_cpu(self, cpu_p95_cores: float, headroom_pct: float) -> float:
        """P95 CPU usage over a rolling observation window + headroom."""
        multiplier = 1.0 + headroom_pct / 100.0
        return round(max(cpu_p95_cores * multiplier, self._config.min_cpu_cores), 3)

    def _recommend_memory(self, mem_p95_mib: float, headroom_pct: float) -> float:
        """P95 memory usage over a rolling observation window + headroom."""
        multiplier = 1.0 + headroom_pct / 100.0
        return round(max(mem_p95_mib * multiplier, self._config.min_memory_mib), 1)

    def _weekly_cost_from_pricing(
        self,
        cpu_request_cores: float,
        mem_request_mib: float,
        pricing: AwsResourcePricing,
    ) -> float:
        hourly_cost = (
            cpu_request_cores * pricing.cpu_cost_per_core_hour
            + mem_request_mib * pricing.mem_cost_per_mib_hour
        )
        return hourly_cost * HOURS_PER_WEEK

    def _resolve_savings_context(
        self,
        actual_weekly_cost_usd: Optional[float],
        cpu_request_cores: float,
        mem_request_mib: float,
        pricing: Optional[AwsResourcePricing],
    ) -> Tuple[Optional[float], str, str]:
        """
        Determine cost status, savings source, and the base cost for savings math.

        Missing actual cost is never copied into weekly_cost_usd. When Cloudability
        data is absent, AWS normalized node pricing is used only as a fallback
        savings estimation source—not as a substitute for observed spend.
        """
        if actual_weekly_cost_usd is not None:
            return actual_weekly_cost_usd, "actual", "cloudability"

        if pricing is not None:
            base_cost = self._weekly_cost_from_pricing(
                cpu_request_cores, mem_request_mib, pricing
            )
            return base_cost, "missing", "aws_node_pricing"

        return None, "missing", "unavailable"

    def _estimate_savings(
        self,
        recommended_cpu: float,
        recommended_mem: float,
        cpu_request_cores: float,
        mem_request_mib: float,
        base_cost_for_savings: Optional[float],
    ) -> Optional[float]:
        if base_cost_for_savings is None:
            return None

        cpu_ratio = (
            recommended_cpu / cpu_request_cores if cpu_request_cores > 0 else 1.0
        )
        mem_ratio = (
            recommended_mem / mem_request_mib if mem_request_mib > 0 else 1.0
        )
        reduction_ratio = 1.0 - (0.5 * cpu_ratio + 0.5 * mem_ratio)
        return round(base_cost_for_savings * reduction_ratio, 2)

    def generate_recommendations(
        self,
        specifications: List[ServiceSpecification], # from kubernetes
        metrics: List[ServiceMetrics], # from prometheus
        costs: List[ServiceCostInfo], # from cloudability
        pricing: Optional[AwsResourcePricing] = None, # from aws
    ) -> List[Recommendation]:
        """
        Correlates K8s specifications, Prometheus P95 usage, and Cloudability costs to
        generate aggressive and conservative right-sizing recommendations side by side.

        Each recommendation is derived from weekly P95 observed usage plus headroom.
        Aggressive applies lower headroom for cost savings; conservative applies higher
        headroom for stability.

        Args:
            specifications: List of current service resource requests.
            metrics: List of P95 usage metrics (cpu_p95_cores, mem_p95_mib).
            costs: List of current weekly service costs from Cloudability.
            pricing: Optional AWS normalized node pricing used only when actual cost
                     is missing, to estimate potential savings without fabricating spend.

        Returns:
            List[Recommendation]: Derived rightsizing recommendations.
        """
        metrics_map: Dict[Tuple[str, str, str], ServiceMetrics] = {
            (m.cluster, m.namespace, m.service_name): m for m in metrics
        }
        costs_map: Dict[Tuple[str, str, str], ServiceCostInfo] = {
            (c.cluster, c.namespace, c.service_name): c for c in costs
        }

        recommendations: List[Recommendation] = []

        for spec in specifications:
            key = (spec.cluster, spec.namespace, spec.service_name)

            metric = metrics_map.get(key)
            cost_info = costs_map.get(key)

            cpu_p95_cores = metric.cpu_p95_cores if metric else 0.0
            mem_p95_mib = metric.mem_p95_mib if metric else 0.0
            actual_weekly_cost = cost_info.weekly_cost_usd if cost_info else None

            base_cost_for_savings, cost_status, savings_source = (
                self._resolve_savings_context(
                    actual_weekly_cost,
                    spec.cpu_request_cores,
                    spec.mem_request_mib,
                    pricing,
                )
            )

            agg_cpu = self._recommend_cpu(
                cpu_p95_cores, self._config.aggressive_headroom_pct
            )
            con_cpu = self._recommend_cpu(
                cpu_p95_cores, self._config.conservative_headroom_pct
            )
            agg_mem = self._recommend_memory(
                mem_p95_mib, self._config.aggressive_headroom_pct
            )
            con_mem = self._recommend_memory(
                mem_p95_mib, self._config.conservative_headroom_pct
            )

            recommendations.append(
                Recommendation(
                    cluster=spec.cluster,
                    namespace=spec.namespace,
                    service_name=spec.service_name,
                    cpu_request_cores=spec.cpu_request_cores,
                    cpu_p95_cores=cpu_p95_cores,
                    mem_request_mib=spec.mem_request_mib,
                    mem_p95_mib=mem_p95_mib,
                    aggressive_cpu_cores=agg_cpu,
                    conservative_cpu_cores=con_cpu,
                    aggressive_mem_mib=agg_mem,
                    conservative_mem_mib=con_mem,
                    weekly_cost_usd=actual_weekly_cost,
                    cost_status=cost_status,
                    savings_estimation_source=savings_source,
                    aggressive_estimated_weekly_savings_usd=self._estimate_savings(
                        agg_cpu,
                        agg_mem,
                        spec.cpu_request_cores,
                        spec.mem_request_mib,
                        base_cost_for_savings,
                    ),
                    conservative_estimated_weekly_savings_usd=self._estimate_savings(
                        con_cpu,
                        con_mem,
                        spec.cpu_request_cores,
                        spec.mem_request_mib,
                        base_cost_for_savings,
                    ),
                )
            )

        return recommendations


# ==============================================================================
# PRODUCTION RECOMMENDATION ENGINE IMPROVEMENTS
# ==============================================================================
# To transition this demo engine to an enterprise-grade production system,
# we would implement the following critical improvements:
#
# 1. Extended Percentile Windows (P99 / longer lookback)
#    - Current: Recommendations use weekly P95 usage from Prometheus.
#    - Problem: P95 may still miss extreme spikes for latency-sensitive workloads.
#    - Solution: Support P99 or rolling 14-day/30-day windows for high-variability services.
#
# 2. Time-Aware Recommendations
#    - Problem: Recommendation requirements change over time (e.g. seasonal traffic spikes,
#      black Friday, weekly cron jobs). Static recommendations can become stale.
#    - Solution: Calculate recommendations over multiple time horizons (e.g., 7d, 30d, 90d).
#      If a workload shows high variability, recommend using a larger lookback window.
#
# 3. Workload Profiling (Business Hours vs Off-Hours)
#    - Problem: Non-production environments (staging/dev) or batch workloads are highly
#      active during working hours but sit idle at night and on weekends.
#    - Solution: Profile workloads into distinct scheduling classes. Introduce
#      time-of-day policies (e.g., scale down staging at 7 PM and scale back up at 8 AM,
#      or suggest HPA (Horizontal Pod Autoscaling) configuration).
#
# 4. Recommendation Confidence Score
#    - Problem: Recommending a resource reduction on a volatile or newly deployed service
#      with only 2 hours of metrics historical data is extremely risky.
#    - Solution: Compute a confidence score (0.0 to 1.0) based on:
#        a) Data Completeness: How many days of metrics were successfully fetched.
#        b) Workload Volatility: The standard deviation of the CPU usage over time.
#        c) Service Criticality: Non-prod environments automatically get higher confidence /
#           lower thresholds for downsizing compared to production payment systems.
# ==============================================================================
