from abc import ABC, abstractmethod
from typing import List
from app.collectors import ServiceSpecification, ServiceMetrics

class BasePrometheusCollector(ABC):
    """
    Abstract Base Class defining the interface for Prometheus metrics collection.
    Conforms to Clean Architecture: decoupled from execution context, frameworks, and databases.
    """
    
    @abstractmethod
    def collect_metrics(self, services: List[ServiceSpecification]) -> List[ServiceMetrics]:
        """
        Retrieves P95 CPU and memory usage for the requested services.

        Production collectors query Prometheus for P95 over a rolling observation window.

        Args:
            services (List[ServiceSpecification]): List of services to collect metrics for.

        Returns:
            List[ServiceMetrics]: P95 usage metrics for each target service.
        """
        pass


class MockPrometheusCollector(BasePrometheusCollector):
    """
    Mock implementation of BasePrometheusCollector.
    Returns static metrics that simulate P95 usage over a rolling observation window.
    """
    
    def collect_metrics(self, services: List[ServiceSpecification]) -> List[ServiceMetrics]:
        """
        Simulates querying Prometheus for P95 CPU and memory over a rolling observation window.
        Provides a mix of over-provisioned, under-provisioned, and correctly-provisioned patterns.
        """
        metrics = []
        for service in services:
            # Map specific services to realistic mock P95 values
            if service.service_name == "payment-service":
                # Configured: 4.0 Cores, 8192 MiB. Heavily over-provisioned!
                cpu_p95_cores = 1.2
                mem_p95_mib = 4096.0
            elif service.service_name == "auth-service":
                # Configured: 2.0 Cores, 4096 MiB. Well utilized.
                cpu_p95_cores = 1.8
                mem_p95_mib = 3800.0
            elif service.service_name == "frontend":
                # Configured: 8.0 Cores, 16384 MiB. Significantly over-provisioned.
                cpu_p95_cores = 2.1
                mem_p95_mib = 6144.0
            elif service.service_name == "catalog-service":
                # Configured: 1.0 Cores, 2048 MiB. Idle/lightly used.
                cpu_p95_cores = 0.15
                mem_p95_mib = 512.0
            elif service.service_name == "reporting-service":
                # Configured: 6.0 Cores, 12288 MiB. Heavily utilized/saturated.
                cpu_p95_cores = 5.8
                mem_p95_mib = 11800.0
            else:
                # Default case: P95 at 50% of configured requests
                cpu_p95_cores = service.cpu_request_cores * 0.5
                mem_p95_mib = service.mem_request_mib * 0.5

            metrics.append(
                ServiceMetrics(
                    cluster=service.cluster,
                    namespace=service.namespace,
                    service_name=service.service_name,
                    cpu_p95_cores=cpu_p95_cores,
                    mem_p95_mib=mem_p95_mib
                )
            )
        return metrics


# ==============================================================================
# PRODUCTION INTEGRATION NOTES
# ==============================================================================
# To transition from the mock collector to a real Prometheus HTTP API integration:
#
# 1. Install an HTTP client (not required for the demo):
#    $ pip install httpx
#
# 2. Wire ProductionPrometheusCollector in the Celery batch worker instead of
#    MockPrometheusCollector. Namespace whitelist / blacklist should be applied
#    in app.scheduler before services are collected when possible.
#
# 3. Production caveats:
#    - Prometheus label conventions vary by cluster (pod, app, workload, etc.).
#    - Workload-to-pod matching may require Deployment / ReplicaSet ownership
#      mapping rather than a simple pod=~"<service>.*" regex.
#    - Prefer recording rules for expensive long-window P95 queries at scale.
#    - Query windows should be configurable (e.g. 7d, 14d, 30d) via env or config.
#    - Handle missing metrics gracefully (return 0.0 or skip with explicit policy).
#    - Apply namespace whitelist / blacklist before querying to reduce load.
#
# 4. Example PromQL (substitute <namespace> and <service> per workload):
#
# CPU P95:
# quantile_over_time(
#   0.95,
#   sum(rate(container_cpu_usage_seconds_total{
#     namespace="<namespace>",
#     container!="",
#     image!="",
#     pod=~"<service>.*"
#   }[5m]))[7d:]
# )
#
# Memory P95 (bytes; divide by 1024 * 1024 for MiB):
# quantile_over_time(
#   0.95,
#   max(container_memory_working_set_bytes{
#     namespace="<namespace>",
#     container!="",
#     image!="",
#     pod=~"<service>.*"
#   })[7d:]
# )
#
# 5. Example production collector skeleton (illustrative — keep commented):
#
import httpx

class ProductionPrometheusCollector(BasePrometheusCollector):
    """
    Production collector querying Prometheus instant query API for P95 usage.
    """

    def __init__(self, prometheus_url: str, timeout_seconds: int = 10):
        self.prometheus_url = prometheus_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        # Optional: self.observation_window = "7d"  # or 14d / 30d from config

    def collect_metrics(self, services: List[ServiceSpecification]) -> List[ServiceMetrics]:
        metrics: List[ServiceMetrics] = []
        for service in services:
            namespace = service.namespace
            workload = service.service_name
            window = "7d"  # configurable in production

            cpu_query = (
                f'quantile_over_time(0.95, sum(rate(container_cpu_usage_seconds_total{{'
                f'namespace="{namespace}", container!="", image!="", '
                f'pod=~"{workload}.*"}}[5m]))[{window}:])'
            )
            mem_query = (
                f'quantile_over_time(0.95, max(container_memory_working_set_bytes{{'
                f'namespace="{namespace}", container!="", image!="", '
                f'pod=~"{workload}.*"}})[{window}:])'
            )

            cpu_p95_cores = self._query_prometheus(cpu_query)
            mem_p95_bytes = self._query_prometheus(mem_query)
            mem_p95_mib = mem_p95_bytes / (1024.0 * 1024.0)

            metrics.append(
                ServiceMetrics(
                    cluster=service.cluster,
                    namespace=namespace,
                    service_name=workload,
                    cpu_p95_cores=cpu_p95_cores,
                    mem_p95_mib=mem_p95_mib,
                )
            )
        return metrics

    def _query_prometheus(self, query: str) -> float:
        """
        Execute an instant query against Prometheus and return the scalar value.
        Returns 0.0 when no data is returned or the response is invalid.
        """
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(
                f"{self.prometheus_url}/api/v1/query",
                params={"query": query},
            )
            if response.status_code != 200:
                return 0.0
            payload = response.json()
            if payload.get("status") != "success":
                return 0.0
            results = payload.get("data", {}).get("result", [])
            if not results:
                return 0.0
            try:
                return float(results[0]["value"][1])
            except (IndexError, KeyError, TypeError, ValueError):
                return 0.0
# ==============================================================================
