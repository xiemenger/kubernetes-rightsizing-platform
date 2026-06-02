from abc import ABC, abstractmethod
from typing import List
from app.collectors import ServiceSpecification

class BaseKubernetesCollector(ABC):
    """
    Abstract Base Class defining the interface for Kubernetes metadata collection.
    Conforms to Clean Architecture: decoupled from execution context, frameworks, and databases.
    """
    
    @abstractmethod
    def collect_services(self) -> List[ServiceSpecification]:
        """
        Retrieves current configured service resource requirements (CPU and Memory requests).
        
        Returns:
            List[ServiceSpecification]: A list of Kubernetes service specifications.
        """
        pass


class MockKubernetesCollector(BaseKubernetesCollector):
    """
    Mock implementation of BaseKubernetesCollector.
    Returns realistic static data representing cluster services and their weekly configured capacities.
    """
    
    def __init__(self, cluster_name: str = "prod-us-east-1"):
        self.cluster_name = cluster_name

    def collect_services(self) -> List[ServiceSpecification]:
        """
        Returns hardcoded mock service specifications for testing and local development.
        The CPU and Memory requests represent configured limits/requests in the cluster.
        """
        return [
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="payment-service",
                cpu_request_cores=4.0,
                mem_request_mib=8192.0
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="auth-service",
                cpu_request_cores=2.0,
                mem_request_mib=4096.0
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="frontend",
                cpu_request_cores=8.0,
                mem_request_mib=16384.0
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="staging",
                service_name="catalog-service",
                cpu_request_cores=1.0,
                mem_request_mib=2048.0
            ),
            ServiceSpecification(
                cluster=self.cluster_name,
                namespace="production",
                service_name="reporting-service",
                cpu_request_cores=6.0,
                mem_request_mib=12288.0
            )
        ]


# ==============================================================================
# PRODUCTION INTEGRATION NOTES
# ==============================================================================
# To transition from the mock collector to a real Kubernetes API integration:
#
# 1. Install the Kubernetes official Python client library:
#    $ pip install kubernetes
#
# 2. Implement the BaseKubernetesCollector using the API client. For example:
#
#    from kubernetes import client, config
#
#    class ProductionKubernetesCollector(BaseKubernetesCollector):
#        def __init__(self, cluster_name: str, kubeconfig_path: str = None):
#            self.cluster_name = cluster_name
#            # Load Kubeconfig. If running in-cluster, use config.load_incluster_config()
#            if kubeconfig_path:
#                config.load_kube_config(config_file=kubeconfig_path)
#            else:
#                config.load_incluster_config()
#            self.v1 = client.CoreV1Api()
#            self.apps_v1 = client.AppsV1Api()
#
#        def collect_services(self) -> List[ServiceSpecification]:
#            services = []
#            # In Kubernetes, resource requests are defined on Pod templates inside Deployments / StatefulSets.
#            # To get service-level resource specs, we can list Deployments and map them to logical services.
#            deployments = self.apps_v1.list_deployment_for_all_namespaces()
#            
#            for dep in deployments.items:
#                namespace = dep.metadata.namespace
#                name = dep.metadata.name  # Assuming deployment name aligns with logical service
#                
#                # Initialize default resources
#                total_cpu_request = 0.0
#                total_mem_request = 0.0
#                
#                # A Deployment has a replica count and container specs
#                replicas = dep.spec.replicas or 1
#                containers = dep.spec.template.spec.containers
#                
#                for container in containers:
#                    resources = container.resources
#                    if not resources or not resources.requests:
#                        continue
#                    
#                    # Parse CPU requests (could be e.g., '100m' or '1')
#                    cpu_req = resources.requests.get("cpu", "0")
#                    total_cpu_request += self._parse_cpu(cpu_req)
#                    
#                    # Parse Memory requests (could be e.g., '256Mi', '1Gi')
#                    mem_req = resources.requests.get("memory", "0")
#                    total_mem_request += self._parse_memory(mem_req)
#                
#                # Multiply by replica count to get the aggregate service request
#                services.append(ServiceSpecification(
#                    cluster=self.cluster_name,
#                    namespace=namespace,
#                    service_name=name,
#                    cpu_request_cores=total_cpu_request * replicas,
#                    mem_request_mib=total_mem_request * replicas
#                ))
#            return services
#
#        def _parse_cpu(self, cpu_str: str) -> float:
#            # Parses CPU strings like "500m" (0.5 cores) or "2" (2.0 cores)
#            if cpu_str.endswith("m"):
#                return float(cpu_str[:-1]) / 1000.0
#            return float(cpu_str)
#
#        def _parse_memory(self, mem_str: str) -> float:
#            # Parses Memory strings and converts to MiB
#            if mem_str.endswith("Gi"):
#                return float(mem_str[:-2]) * 1024.0
#            if mem_str.endswith("Mi"):
#                return float(mem_str[:-2])
#            if mem_str.endswith("M"):
#                return float(mem_str[:-1]) * 0.953674  # MB to MiB approx
#            return float(mem_str) / (1024.0 * 1024.0)  # bytes to MiB
# ==============================================================================
