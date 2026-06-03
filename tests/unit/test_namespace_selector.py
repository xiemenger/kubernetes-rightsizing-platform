import pytest

from app.scheduler.namespace_selector import select_namespaces


ALL = ["payments", "checkout", "catalog", "orders", "kube-system", "monitoring"]


class TestWhitelist:
    def test_only_includes_whitelisted_namespaces(self):
        result = select_namespaces(ALL, whitelist=["payments", "checkout"])
        assert result == ["payments", "checkout"]

    def test_preserves_source_order(self):
        result = select_namespaces(
            ["orders", "payments", "checkout"],
            whitelist=["payments", "checkout", "orders"],
        )
        assert result == ["orders", "payments", "checkout"]

    def test_empty_when_no_overlap(self):
        assert select_namespaces(ALL, whitelist=["nonexistent"]) == []


class TestBlacklist:
    def test_removes_blacklisted_namespaces(self):
        result = select_namespaces(ALL, blacklist=["kube-system", "monitoring"])
        assert "kube-system" not in result
        assert "monitoring" not in result
        assert len(result) == 4


class TestWhitelistAndBlacklist:
    def test_whitelist_then_blacklist(self):
        result = select_namespaces(
            ALL,
            whitelist=["payments", "checkout", "kube-system"],
            blacklist=["kube-system"],
        )
        assert result == ["payments", "checkout"]

    def test_no_filters_returns_copy_of_input_order(self):
        assert select_namespaces(ALL) == ALL


class TestEdgeCases:
    def test_empty_input(self):
        assert select_namespaces([], whitelist=["a"]) == []

    def test_none_whitelist_and_blacklist(self):
        assert select_namespaces(["a", "b"]) == ["a", "b"]
