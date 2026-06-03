from typing import List


def chunk_namespaces(namespaces: List[str], batch_size: int = 50) -> List[List[str]]:
    """
    Split a namespace list into fixed-size batches for parallel Celery workers.

    Returns an empty list when namespaces is empty.
    Raises ValueError when batch_size is not positive.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    if not namespaces:
        return []

    batches: List[List[str]] = []
    for start in range(0, len(namespaces), batch_size):
        batches.append(namespaces[start : start + batch_size])
    return batches
