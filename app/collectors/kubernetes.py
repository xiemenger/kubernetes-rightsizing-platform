from abc import ABC, abstractmethod
from typing import List, Optional
from app.collectors import ServiceSpecification

# Demo cluster namespace inventory (production would call K8s API list_namespace).
_MOCK_CLUSTER_NAMESPACES = [
    "payments",
    "checkout",
    "catalog",
    "orders",
    "analytics",
    "monitoring",
    "platform",
    "production",
    "staging",
    "kube-system",
]


class BaseKubernetesCollector(ABC):
    """
    Abstract Base Class defining the interface for Kubernetes metadata collection.
    Conforms to Clean Architecture: decoupled from execution context, frameworks, and databases.
    """

    @abstractmethod
    def list_namespaces(self) -> List[str]:
        """Discover namespace names in the cluster."""
        pass

    @abstractmethod
    def collect_services(
        self, namespaces: Optional[List[str]] = None
    ) -> List[ServiceSpecification]:
        """
        Retrieves current configured service resource requirements (CPU and Memory requests).

        Args:
            namespaces: When provided, only return services in these namespaces.
        """
        pass


class MockKubernetesCollector(BaseKubernetesCollector):
    """
    Mock implementation of BaseKubernetesCollector.
    Returns realistic static data representing cluster services and namespace inventory.
    """

    def __init__(self, cluster_name: str = "prod-us-east-1"):
        self.cluster_name = cluster_name

    def list_namespaces(self) -> List[str]:
        """Return realistic namespace names for demo scheduling."""
        return list(_MOCK_CLUSTER_NAMESPACES)

    def collect_services(
        self, namespaces: Optional[List[str]] = None
    ) -> List[ServiceSpecification]:
        """
        Returns mock service specifications, optionally filtered to namespace batches.
        """
        all_services = self._all_mock_services()
        if namespaces is None:
            return all_services

        allowed = set(namespaces)
        return [s for s in all_services if s.namespace in allowed]

    def _all_mock_services(self) -> List[ServiceSpecification]:
        """Build the full mock service catalog across namespaces."""
        services: List[ServiceSpecification] = [
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="payment-service",
                cpu_request_cores=4.0,
                mem_request_mib=8192.0,
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="auth-service",
                cpu_request_cores=2.0,
                mem_request_mib=4096.0,
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="frontend",
                cpu_request_cores=8.0,
                mem_request_mib=16384.0,
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="staging",
                service_name="catalog-service",
                cpu_request_cores=1.0,
                mem_request_mib=2048.0,
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="reporting-service",
                cpu_request_cores=6.0,
                mem_request_mib=12288.0,
            ),
        ]

        namespace_defaults = {
            "payments": (2.0, 4096.0),
            "checkout": (2.5, 5120.0),
            "catalog": (1.5, 3072.0),
            "orders": (3.0, 6144.0),
            "analytics": (4.0, 8192.0),
            "monitoring": (1.0, 2048.0),
            "platform": (2.0, 4096.0),
            "kube-system": (0.5, 512.0),
        }
        for namespace, (cpu, mem) in namespace_defaults.items():
            if any(s.namespace == namespace for s in services):
                continue
            services.append(
                ServiceSpecification(
                    cluster=self.cluster_name,
                    namespace=namespace,
                    service_name=f"{namespace}-api",
                    cpu_request_cores=cpu,
                    mem_request_mib=mem,
                )
            )

        return services


# ==============================================================================
# PRODUCTION INTEGRATION NOTES
# ==============================================================================
# To transition from the mock collector to a real Kubernetes API integration:
#
# 1. Install the official Kubernetes Python client (not required for the demo):
#    $ pip install kubernetes
#
# 2. Wire ProductionKubernetesCollector in the Celery pipeline / CronJob worker
#    instead of MockKubernetesCollector. Apply whitelist / blacklist via
#    app.scheduler.namespace_selector before passing namespaces into collect_services().
#
# 3. Production caveats:
#    - RBAC: ServiceAccount needs permissions to list namespaces and list/get
#      deployments (and any other workload types you include).
#    - Missing container.resources.requests should be treated as zero or skipped
#      explicitly — do not assume defaults silently without policy.
#    - Deployments alone may be incomplete; many clusters also rightsize StatefulSets,
#      DaemonSets, CronJobs, Jobs, and standalone Pods.
#    - Multi-container pods: aggregate CPU/memory requests across all containers,
#      then multiply by replica count for the logical service row.
#    - Namespace filtering (whitelist / blacklist) should happen in the scheduler
#      before collection so batch workers only query approved namespaces.
#
# 4. Example production collector skeleton (illustrative — keep commented):
#
from kubernetes import client, config

class ProductionKubernetesCollector(BaseKubernetesCollector):
    """
    Production collector using the Kubernetes API.
    Run in-cluster (CronJob / worker Pod) or locally with kubeconfig.
    """

    def __init__(self, cluster_name: str = None, in_cluster: bool = True):
        self.cluster_name = cluster_name or "unknown-cluster"
        if in_cluster:
            config.load_incluster_config()
        else:
            config.load_kube_config()
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def list_namespaces(self) -> List[str]:
        response = self.core_v1.list_namespace()
        return [item.metadata.name for item in response.items]

    def collect_services(
        self, namespaces: Optional[List[str]] = None
    ) -> List[ServiceSpecification]:
        if namespaces is None:
            namespaces = self.list_namespaces()

        services: List[ServiceSpecification] = []
        for namespace in namespaces:
            deployments = self.apps_v1.list_namespaced_deployment(namespace=namespace)
            for deployment in deployments.items:
                service_name = deployment.metadata.name
                replicas = deployment.spec.replicas or 1
                pod_template = deployment.spec.template.spec
                containers = pod_template.containers or []

                total_cpu_request = 0.0
                total_mem_request_mib = 0.0
                for container in containers:
                    resources = container.resources
                    if not resources or not resources.requests:
                        continue
                    requests = resources.requests
                    cpu_req = requests.get("cpu")
                    mem_req = requests.get("memory")
                    if cpu_req:
                        total_cpu_request += self._parse_cpu_to_cores(cpu_req)
                    if mem_req:
                        total_mem_request_mib += self._parse_memory_to_mib(mem_req)

                services.append(
                    ServiceSpecification(
                        cluster=self.cluster_name,
                        namespace=namespace,
                        service_name=service_name,
                        cpu_request_cores=total_cpu_request * replicas,
                        mem_request_mib=total_mem_request_mib * replicas,
                    )
                )
        return services

    @staticmethod
    def _parse_cpu_to_cores(cpu: str) -> float:
        """Parse Kubernetes CPU request strings to cores. E.g. '500m' -> 0.5, '2' -> 2.0."""
        cpu = cpu.strip()
        if cpu.endswith("m"):
            return float(cpu[:-1]) / 1000.0
        return float(cpu)

    @staticmethod
    def _parse_memory_to_mib(memory: str) -> float:
        """Parse Kubernetes memory request strings to MiB. E.g. '512Mi' -> 512, '1Gi' -> 1024."""
        memory = memory.strip()
        if memory.endswith("Gi"):
            return float(memory[:-2]) * 1024.0
        if memory.endswith("Mi"):
            return float(memory[:-2])
        if memory.endswith("G"):
            return float(memory[:-1]) * 1000.0 / 1.048576  # approximate GB → MiB
        if memory.endswith("M"):
            return float(memory[:-1]) * 0.953674  # approximate MB → MiB
        # Bare integer is bytes in Kubernetes
        return float(memory) / (1024.0 * 1024.0)
# ==============================================================================
