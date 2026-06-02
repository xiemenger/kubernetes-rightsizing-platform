#!/usr/bin/env bash
# Verify a right-sizing deployment in a target cluster (demo).
#
# Usage:
#   ./scripts/verify_cluster.sh <cluster_name> <namespace> <kube_context>

set -euo pipefail

CLUSTER_NAME="${1:?cluster_name required}"
NAMESPACE="${2:?namespace required}"
KUBE_CONTEXT="${3:?kube_context required}"

echo "=== Verify right-sizing deployment ==="
echo "cluster:     ${CLUSTER_NAME}"
echo "namespace:   ${NAMESPACE}"
echo "kube_context:${KUBE_CONTEXT}"
echo ""

echo "[demo] Planned verification commands:"
echo "  kubectl config use-context ${KUBE_CONTEXT}"
echo "  kubectl -n ${NAMESPACE} rollout status deployment/right-sizing-api --timeout=120s"
echo "  kubectl -n ${NAMESPACE} get pods -l app=right-sizing"
echo "  kubectl -n ${NAMESPACE} exec deploy/right-sizing-api -- curl -sf http://localhost:5000/api/v1/health"

# kubectl config use-context "${KUBE_CONTEXT}"
# kubectl -n "${NAMESPACE}" rollout status deployment/right-sizing-api --timeout=120s

echo ""
echo "[demo] Verification simulation completed for ${CLUSTER_NAME}"
