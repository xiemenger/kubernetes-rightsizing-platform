from typing import List, Optional


def select_namespaces(
    all_namespaces: List[str],
    whitelist: Optional[List[str]] = None,
    blacklist: Optional[List[str]] = None,
) -> List[str]:
    """
    Filter cluster namespaces for a rightsizing run.

    - If whitelist is provided, only namespaces in the whitelist are considered.
    - Namespaces in blacklist are always removed (applied after whitelist).
    - Preserves the order of all_namespaces for namespaces that remain.
    """
    if whitelist is not None:
        allowed = set(whitelist)
        namespaces = [ns for ns in all_namespaces if ns in allowed]
    else:
        namespaces = list(all_namespaces)

    if blacklist:
        blocked = set(blacklist)
        namespaces = [ns for ns in namespaces if ns not in blocked]

    return namespaces
