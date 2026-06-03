from app.collectors.kubernetes import MockKubernetesCollector


class TestMockKubernetesCollector:
    def test_list_namespaces_returns_inventory(self):
        collector = MockKubernetesCollector(cluster_name="prod-us-east-1")
        namespaces = collector.list_namespaces()
        assert "payments" in namespaces
        assert "platform" in namespaces

    def test_collect_services_filters_by_namespace_batch(self):
        collector = MockKubernetesCollector(cluster_name="prod-us-east-1")
        services = collector.collect_services(namespaces=["payments", "checkout"])
        namespaces = {s.namespace for s in services}
        assert namespaces == {"payments", "checkout"}

    def test_collect_services_without_filter_returns_all(self):
        collector = MockKubernetesCollector(cluster_name="prod-us-east-1")
        all_services = collector.collect_services()
        filtered = collector.collect_services(namespaces=["production"])
        assert len(all_services) >= len(filtered)
        assert all(s.namespace == "production" for s in filtered)
