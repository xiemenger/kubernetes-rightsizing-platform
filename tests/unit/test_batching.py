import pytest

from app.scheduler.batching import chunk_namespaces


class TestChunkNamespaces:
    def test_splits_into_batches_of_fifty(self):
        namespaces = [f"ns-{i}" for i in range(120)]
        batches = chunk_namespaces(namespaces, batch_size=50)
        assert len(batches) == 3
        assert len(batches[0]) == 50
        assert len(batches[1]) == 50
        assert len(batches[2]) == 20
        assert batches[0][0] == "ns-0"
        assert batches[2][-1] == "ns-119"

    def test_single_batch_when_under_batch_size(self):
        namespaces = ["payments", "checkout", "catalog"]
        assert chunk_namespaces(namespaces, batch_size=50) == [namespaces]

    def test_batch_size_one(self):
        assert chunk_namespaces(["a", "b", "c"], batch_size=1) == [["a"], ["b"], ["c"]]

    def test_exact_multiple_of_batch_size(self):
        namespaces = [f"ns-{i}" for i in range(100)]
        batches = chunk_namespaces(namespaces, batch_size=50)
        assert len(batches) == 2
        assert all(len(batch) == 50 for batch in batches)

    def test_empty_list_returns_empty(self):
        assert chunk_namespaces([]) == []

    def test_invalid_batch_size_raises(self):
        with pytest.raises(ValueError, match="batch_size"):
            chunk_namespaces(["a"], batch_size=0)
