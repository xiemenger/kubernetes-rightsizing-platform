from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True) # 轻量级数据对象,创建后不可修改
class ServiceSpecification:
    """
    Represents the configured resource requests for a Kubernetes service in a cluster.
    """
    cluster: str
    namespace: str
    service_name: str
    cpu_request_cores: float
    mem_request_mib: float


@dataclass(frozen=True)  
class ServiceMetrics:
    """
    Represents observed P95 resource usage for a Kubernetes service.

    Values are sourced from Prometheus as P95 over a rolling observation window
    (e.g. 7 days)—not averages—so recommendations account for peak load.
    """
    cluster: str
    namespace: str
    service_name: str
    cpu_p95_cores: float  # P95 CPU usage over a rolling observation window (cores)
    mem_p95_mib: float    # P95 memory usage over a rolling observation window (MiB)


@dataclass(frozen=True)
class ServiceCostInfo:
    """
    Represents cost metrics (e.g. from Cloudability) for a service over a weekly period.
    """
    cluster: str
    namespace: str
    service_name: str
    weekly_cost_usd: Optional[float]



@dataclass(frozen=True)
class AwsResourcePricing:
    """
    Represents hourly pricing for raw compute and memory resources in an AWS region.
    """
    region: str
    cpu_cost_per_core_hour: float
    mem_cost_per_mib_hour: float


# Late imports of interfaces and mocks to provide clean, unified module imports.
# This makes it easy for other services (e.g., the recommendation engines or pipelines)
# to interact with collectors via `from app.collectors import MockKubernetesCollector` etc.
try:
    from app.collectors.kubernetes import BaseKubernetesCollector, MockKubernetesCollector
    from app.collectors.prometheus import BasePrometheusCollector, MockPrometheusCollector
    from app.collectors.cloudability import BaseCloudabilityCollector, MockCloudabilityCollector
    from app.collectors.aws_pricing import BaseAwsPricingCollector, MockAwsPricingCollector
except ImportError:
    # Handle bootstrapping/import cases during file creation
    pass
