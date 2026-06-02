from abc import ABC, abstractmethod
from app.collectors import AwsResourcePricing

class BaseAwsPricingCollector(ABC):
    """
    Abstract Base Class defining the interface for AWS pricing metadata collection.
    Conforms to Clean Architecture: decoupled from execution context, frameworks, and databases.
    """
    
    @abstractmethod
    def get_pricing(self, region: str) -> AwsResourcePricing:
        """
        Retrieves the AWS resource pricing per core hour and per MiB hour for a given region.
        
        Args:
            region (str): AWS region name (e.g. 'us-east-1').
            
        Returns:
            AwsResourcePricing: Pricing information for vCPU and memory.
        """
        pass


from dataclasses import dataclass

@dataclass(frozen=True)
class NodeType:
    """
    Represents an AWS EC2 instance type with its physical specifications
    and on-demand hourly pricing.
    """
    name: str
    vcpu: int
    mem_gib: float
    price_per_hour: float


class MockAwsPricingCollector(BaseAwsPricingCollector):
    """
    Mock implementation of BaseAwsPricingCollector.
    Uses a median-style normalized pricing strategy to estimate resource costs
    across a heterogeneous cluster of node types.
    
    Why normalized estimation?
    In production Kubernetes clusters, pods can reside on or move across different 
    instance families (heterogeneous node types). Since container costs depend on the
    node they are scheduled on, we estimate a median unit price for the cluster.
    This provides a stable, interview-friendly abstraction.
    """
    
    def __init__(self, node_types: list[NodeType] = None):
        # Default node types representing a typical Kubernetes heterogeneous cluster
        self.node_types = node_types or [
            NodeType("m5.large", 2, 8.0, 0.096),
            NodeType("c5.2xlarge", 8, 16.0, 0.34),
            NodeType("m5.2xlarge", 8, 32.0, 0.384),
            NodeType("r5.4xlarge", 16, 128.0, 1.008),
        ]

    def get_pricing(self, region: str) -> AwsResourcePricing:
        """
        Calculates normalized compute and memory prices using a median node strategy.
        
        Algorithm:
        1. Sort node types by hourly price.
        2. If number of node types is odd, use the middle node type's price and specs.
        3. If even, average the price and specs of the two middle node types.
        4. Derive core and MiB hourly costs using a 50/50 cost allocation model.
        """
        region_clean = region.lower().strip()
        
        # Sort node types by hourly price
        sorted_nodes = sorted(self.node_types, key=lambda n: n.price_per_hour)
        n = len(sorted_nodes)
        
        if n == 0:
            # Fallback to standard rates if empty
            return AwsResourcePricing(
                region=region_clean,
                cpu_cost_per_core_hour=0.0405,
                mem_cost_per_mib_hour=0.00000434
            )
            
        if n % 2 == 1:
            # Odd: use the exact middle node type
            median_node = sorted_nodes[n // 2]
            normalized_price = median_node.price_per_hour
            normalized_vcpu = float(median_node.vcpu)
            normalized_mem_gib = median_node.mem_gib
        else:
            # Even: average the prices and specs of the two middle node types
            node1 = sorted_nodes[(n // 2) - 1]
            node2 = sorted_nodes[n // 2]
            normalized_price = (node1.price_per_hour + node2.price_per_hour) / 2.0
            normalized_vcpu = (node1.vcpu + node2.vcpu) / 2.0
            normalized_mem_gib = (node1.mem_gib + node2.mem_gib) / 2.0

        # Adjust pricing slightly based on the region coefficient to add realism
        region_multiplier = 1.0
        if region_clean == "us-west-2":
            region_multiplier = 1.1
        elif region_clean == "eu-central-1":
            region_multiplier = 1.2
            
        normalized_price *= region_multiplier

        # Derive core & memory costs: 50% of node cost allocated to CPU, 50% to memory
        # core cost: (normalized_price * 0.5) / vcpu count
        cpu_cost_per_core_hour = (normalized_price * 0.5) / normalized_vcpu
        
        # memory cost per GiB: (normalized_price * 0.5) / memory GiB count
        mem_cost_per_gib_hour = (normalized_price * 0.5) / normalized_mem_gib
        
        # Convert GiB hour cost to MiB hour cost
        mem_cost_per_mib_hour = mem_cost_per_gib_hour / 1024.0

        return AwsResourcePricing(
            region=region_clean,
            cpu_cost_per_core_hour=round(cpu_cost_per_core_hour, 6),
            mem_cost_per_mib_hour=round(mem_cost_per_mib_hour, 10)
        )


# ==============================================================================
# PRODUCTION INTEGRATION NOTES
# ==============================================================================
# To transition from the mock collector to a real AWS Pricing integration:
#
# 1. Install `boto3` library:
#    $ pip install boto3
#
# 2. AWS Price List API provides two ways: `pricing` client (only available in `us-east-1` 
#    endpoint), or parsing the public pricing JSON files directly.
#
#    Here is how you would use the `boto3` client to query the AWS Price List API for EC2:
#
#    import boto3
#    import json
#
#    class ProductionAwsPricingCollector(BaseAwsPricingCollector):
#        def __init__(self, node_types: list[NodeType] = None):
#            self.node_types = node_types or [
#                NodeType("m5.large", 2, 8.0, 0.096),
#                NodeType("c5.2xlarge", 8, 16.0, 0.34),
#                NodeType("m5.2xlarge", 8, 32.0, 0.384),
#                NodeType("r5.4xlarge", 16, 128.0, 1.008),
#            ]
#            # Note: AWS Pricing API endpoint is exclusively in us-east-1
#            self.pricing_client = boto3.client('pricing', region_name='us-east-1')
#
#        def get_pricing(self, region: str) -> AwsResourcePricing:
#            # 1. Map region code to Region Name string (e.g., 'us-east-1' -> 'US East (N. Virginia)')
#            region_name_map = {
#                'us-east-1': 'US East (N. Virginia)',
#                'us-west-2': 'US West (Oregon)',
#                'eu-central-1': 'EU (Frankfurt)'
#            }
#            full_region_name = region_name_map.get(region, 'US East (N. Virginia)')
#
#            fetched_nodes = []
#            
#            # Query each node type's price dynamically
#            for node in self.node_types:
#                try:
#                    response = self.pricing_client.get_products(
#                        ServiceCode='AmazonEC2',
#                        Filters=[
#                            {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': full_region_name},
#                            {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': node.name},
#                            {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
#                            {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
#                            {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'},
#                            {'Type': 'TERM_MATCH', 'Field': 'capacitystatus', 'Value': 'Used'},
#                        ]
#                    )
#                    
#                    price_per_hour = 0.0
#                    for price_str in response.get('PriceList', []):
#                        price_data = json.loads(price_str)
#                        terms = price_data.get('terms', {}).get('OnDemand', {})
#                        for term_val in terms.values():
#                            price_dimensions = term_val.get('priceDimensions', {})
#                            for dim_val in price_dimensions.values():
#                                price_per_hour = float(dim_val.get('pricePerUnit', {}).get('USD', 0.0))
#                                break
#                    
#                    # Update the node description with the retrieved price
#                    fetched_nodes.append(
#                        NodeType(
#                            name=node.name,
#                            vcpu=node.vcpu,
#                            mem_gib=node.mem_gib,
#                            price_per_hour=price_per_hour if price_per_hour > 0 else node.price_per_hour
#                        )
#                    )
#                except Exception:
#                    # Safe fallback to static default if network/API limits are hit
#                    fetched_nodes.append(node)
#            
#            # 2. Sort node types by hourly price
#            sorted_nodes = sorted(fetched_nodes, key=lambda n: n.price_per_hour)
#            n = len(sorted_nodes)
#            
#            if n == 0:
#                return AwsResourcePricing(region, 0.0405, 0.00000434)
#                
#            if n % 2 == 1:
#                median_node = sorted_nodes[n // 2]
#                normalized_price = median_node.price_per_hour
#                normalized_vcpu = float(median_node.vcpu)
#                normalized_mem_gib = median_node.mem_gib
#            else:
#                node1 = sorted_nodes[(n // 2) - 1]
#                node2 = sorted_nodes[n // 2]
#                normalized_price = (node1.price_per_hour + node2.price_per_hour) / 2.0
#                normalized_vcpu = (node1.vcpu + node2.vcpu) / 2.0
#                normalized_mem_gib = (node1.mem_gib + node2.mem_gib) / 2.0
#
#            # 3. Derive core and MiB hourly costs using a 50/50 allocation model
#            cpu_cost_per_core_hour = (normalized_price * 0.5) / normalized_vcpu
#            mem_cost_per_mib_hour = ((normalized_price * 0.5) / normalized_mem_gib) / 1024.0
#            
#            return AwsResourcePricing(
#                region=region,
#                cpu_cost_per_core_hour=round(cpu_cost_per_core_hour, 6),
#                mem_cost_per_mib_hour=round(mem_cost_per_mib_hour, 10)
#            )
# ==============================================================================
