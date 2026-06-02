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
# To transition from the mock collector to a real Prometheus API integration:
#
# 1. Install an HTTP client like `requests` or `httpx`:
#    $ pip install httpx
#
# 2. Query Prometheus HTTP API using PromQL (Prometheus Query Language).
#    Prometheus exposes a REST endpoint: `/api/v1/query` and `/api/v1/query_range`.
#
#    Example query parameters for weekly P95 CPU usage over a 7-day window:
#    - Query: quantile_over_time(0.95, rate(container_cpu_usage_seconds_total{namespace="production", container!=""}[5m])[7d])
#
#    Example query parameters for weekly P95 memory usage over a 7-day window:
#    - Query: quantile_over_time(0.95, container_memory_working_set_bytes{namespace="production", container!=""}[7d])
#
# 3. Implement the BasePrometheusCollector:
#
#    import httpx
#
#    class ProductionPrometheusCollector(BasePrometheusCollector):
#        def __init__(self, prometheus_url: str):
#            self.prometheus_url = prometheus_url.rstrip("/")
#
#        def collect_metrics(self, services: List[ServiceSpecification]) -> List[ServiceMetrics]:
#            metrics = []
#            with httpx.Client() as client:
#                for svc in services:
#                    # 1. Fetch P95 CPU usage over the last 7 days
#                    # We query kube-state-metrics and container metrics aggregated by service namespace and deployment
#                    cpu_query = (
#                        f'sum(quantile_over_time(0.95, rate(container_cpu_usage_seconds_total{{'
#                        f'namespace="{svc.namespace}", pod=~"{svc.service_name}-.*"}}[5m])[7d]))'
#                    )
#                    cpu_val = self._query_single_value(client, cpu_query)
#
#                    # 2. Fetch P95 memory usage over the last 7 days
#                    mem_query = (
#                        f'sum(quantile_over_time(0.95, container_memory_working_set_bytes{{'
#                        f'namespace="{svc.namespace}", pod=~"{svc.service_name}-.*"}}[7d]))'
#                    )
#                    mem_bytes = self._query_single_value(client, mem_query)
#                    mem_mib = mem_bytes / (1024.0 * 1024.0) if mem_bytes else 0.0
#
#                    metrics.append(
#                        ServiceMetrics(
#                            cluster=svc.cluster,
#                            namespace=svc.namespace,
#                            service_name=svc.service_name,
#                            cpu_p95_cores=cpu_val if cpu_val else 0.0,
#                            mem_p95_mib=mem_mib
#                        )
#                    )
#            return metrics
#
#        def _query_single_value(self, client: httpx.Client, query: str) -> float:
#            response = client.get(
#                f"{self.prometheus_url}/api/v1/query",
#                params={"query": query}
#            )
#            if response.status_code != 200:
#                # In production, handle errors or log them
#                return 0.0
#            
#            data = response.json()
#            results = data.get("data", {}).get("result", [])
#            if not results:
#                return 0.0
#            
#            # Result format: {"metric": {}, "value": [timestamp, "value_string"]}
#            try:
#                return float(results[0]["value"][1])
#            except (ValueError, IndexError, KeyError):
#                return 0.0
# ==============================================================================
