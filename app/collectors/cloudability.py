from abc import ABC, abstractmethod
from typing import List
from app.collectors import ServiceSpecification, ServiceCostInfo

class BaseCloudabilityCollector(ABC):
    """
    Abstract Base Class defining the interface for Cloudability cost collection.
    Conforms to Clean Architecture: decoupled from execution context, frameworks, and databases.
    """
    
    @abstractmethod
    def collect_costs(self, services: List[ServiceSpecification]) -> List[ServiceCostInfo]:
        """
        Retrieves weekly cost records for the specified services.
        
        Args:
            services (List[ServiceSpecification]): List of services to fetch costs for.
            
        Returns:
            List[ServiceCostInfo]: Weekly cost details in USD for each service.
        """
        pass


class MockCloudabilityCollector(BaseCloudabilityCollector):
    """
    Mock implementation of BaseCloudabilityCollector.
    Returns realistic weekly cost allocations for testing and local development.
    Preserves missing costs as None to distinguish between free resources (0.0) 
    and missing telemetry data.
    """

    def collect_costs(self, services: List[ServiceSpecification]) -> List[ServiceCostInfo]:
        """
        Simulates querying the Cloudability API for weekly service resource costs.
        Yields mock costs for populated services, and returns None for missing/untracked services.
        """
        costs = []
        for service in services:
            # Map specific services to realistic mock weekly cost records
            if service.service_name == "payment-service":
                weekly_cost = 150.00
            elif service.service_name == "auth-service":
                weekly_cost = 75.00
            elif service.service_name == "frontend":
                weekly_cost = 300.00
            elif service.service_name == "catalog-service":
                weekly_cost = 37.50
            elif service.service_name == "reporting-service":
                weekly_cost = 225.00
            else:
                # Surfacing missing cost explicitly to API/UI as "cost unavailable" (None).
                #
                # Why preserve None instead of fabricating estimated costs?
                # 1. 0.0 cost represents a free resource (e.g. promotional credits or system utility)
                #    whereas None represents missing/unavailable telemetry.
                # 2. Fabricating fallback costs inside the collector layer is a severe anti-pattern
                #    as it conceals data ingestion issues and misleads users into thinking they have 
                #    accurate telemetry.
                # 3. Decoupling: Keeps collectors pure. Cloudability collector does not instantiate
                #    AWS pricing. Surfacing None allows downstream pipelines or UIs to explicitly
                #    render "cost unavailable".
                weekly_cost = None

            costs.append(
                ServiceCostInfo(
                    cluster=service.cluster,
                    namespace=service.namespace,
                    service_name=service.service_name,
                    weekly_cost_usd=round(weekly_cost, 2) if weekly_cost is not None else None
                )
            )
        return costs


# ==============================================================================
# PRODUCTION INTEGRATION NOTES
# ==============================================================================
# To transition from the mock collector to a real Apptio Cloudability API integration:
#
# 1. Obtain your Cloudability API token and set it in your environment:
#    $ export CLOUDABILITY_API_TOKEN="your-api-token"
#
# 2. Use Cloudability's reporting API (v3) which supports queries with metrics, 
#    dimensions, and date ranges.
#    Endpoint: https://api.cloudability.com/v3/reporting/cost/metrics
#
# 3. Implement the BaseCloudabilityCollector using Python's `requests` or `httpx`:
#
import os
import httpx

class ProductionCloudabilityCollector(BaseCloudabilityCollector):
    def __init__(self, api_url: str = "https://api.cloudability.com/v3"):
        self.api_url = api_url.rstrip("/")
        self.api_token = os.environ.get("CLOUDABILITY_API_TOKEN")
        if not self.api_token:
            raise ValueError("CLOUDABILITY_API_TOKEN environment variable is not set")

    def collect_costs(self, services: List[ServiceSpecification]) -> List[ServiceCostInfo]:
        cost_infos = []
        
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json"
        }
        
        # Build a payload/query params for Cloudability Reporting API
        params = {
            "metrics": "unblended_cost",
            "dimensions": "kubernetes_cluster,kubernetes_namespace,kubernetes_label_app",
            "start_date": "7_days_ago",
            "end_date": "yesterday"
        }
        
        with httpx.Client() as client:
            response = client.get(
                f"{self.api_url}/reporting/cost/metrics",
                headers=headers,
                params=params
            )
            
            if response.status_code != 200:
                # If API query fails, surface the telemetry failure explicitly.
                # Do NOT fabricate fallback estimates or default to 0.0 inside the collector.
                return [
                    ServiceCostInfo(s.cluster, s.namespace, s.service_name, None) 
                    for s in services
                ]
            
            raw_data = response.json()
            results = raw_data.get("results", [])
            
            # Map results list to dictionary for O(1) lookup
            cost_map = {}
            for item in results:
                cluster = item.get("kubernetes_cluster")
                namespace = item.get("kubernetes_namespace")
                svc_name = item.get("kubernetes_label_app")
                cost_val = float(item.get("unblended_cost", 0.0))
                
                cost_map[(cluster, namespace, svc_name)] = cost_val
            
            for svc in services:
                # Lookup the cost using the mapping key
                lookup_key = (svc.cluster, svc.namespace, svc.service_name)
                weekly_cost = cost_map.get(lookup_key, None)
                
                # Note: We do NOT use fallback formulas like (CPU * cpu_price + Mem * mem_price)
                # inside the cost collector. 0.0 cost represents a free resource, whereas
                # None indicates missing telemetry or tag mismatches. Surfaces None to allow
                # explicit handling in the API/UI as "cost unavailable".
                
                cost_infos.append(
                    ServiceCostInfo(
                        cluster=svc.cluster,
                        namespace=svc.namespace,
                        service_name=svc.service_name,
                        weekly_cost_usd=round(weekly_cost, 2) if weekly_cost is not None else None
                    )
                )
                
        return cost_infos
# ==============================================================================
