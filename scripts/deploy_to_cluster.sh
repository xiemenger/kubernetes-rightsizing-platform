#!/usr/bin/env bash
# Deploy the right-sizing application to a target Kubernetes cluster (demo).
# Production CI calls this script once per cluster for GitLab per-cluster visibility.
#
# Usage:
#   ./scripts/deploy_to_cluster.sh <cluster_name> <env> <namespace> <kube_context> <image_tag>

set -euo pipefail

CLUSTER_NAME="${1:?cluster_name required}"
ENV="${2:?env required}"
NAMESPACE="${3:?namespace required}"
KUBE_CONTEXT="${4:?kube_context required}"
IMAGE_TAG="${5:?image_tag required}"

echo "=== Deploy right-sizing ==="
echo "cluster:     ${CLUSTER_NAME}"
echo "env:         ${ENV}"
echo "namespace:   ${NAMESPACE}"
echo "kube_context:${KUBE_CONTEXT}"
echo "image:       right-sizing:${IMAGE_TAG}"
echo ""

# Demo mode: echo planned kubectl operations. Uncomment in a real environment with kubeconfig.
echo "[demo] Planned kubectl commands:"
echo "  kubectl config use-context ${KUBE_CONTEXT}"
echo "  kubectl get ns ${NAMESPACE} || kubectl create ns ${NAMESPACE}"
echo "  kubectl -n ${NAMESPACE} apply -f deploy/k8s/"
echo "  kubectl -n ${NAMESPACE} set image deployment/right-sizing-api \\"
echo "    api=right-sizing:${IMAGE_TAG} --record"
echo "  kubectl -n ${NAMESPACE} rollout status deployment/right-sizing-api --timeout=120s"

# kubectl config use-context "${KUBE_CONTEXT}"
# kubectl -n "${NAMESPACE}" apply -f deploy/k8s/
# kubectl -n "${NAMESPACE}" set image deployment/right-sizing-api "api=right-sizing:${IMAGE_TAG}"

echo ""
echo "[demo] Deploy simulation completed for ${CLUSTER_NAME}"
