#!/usr/bin/env bash
# Validate or trigger the weekly rightsizing CronJob in a target cluster (demo).
# Production runs every Tuesday; operators may ad-hoc trigger from CronJob template.
#
# Usage:
#   ./scripts/trigger_weekly_job.sh <cluster_name> <namespace> <kube_context>

set -euo pipefail

CLUSTER_NAME="${1:?cluster_name required}"
NAMESPACE="${2:?namespace required}"
KUBE_CONTEXT="${3:?kube_context required}"

CRONJOB_NAME="weekly-rightsizing"

echo "=== Weekly rightsizing job (CronJob) ==="
echo "cluster:     ${CLUSTER_NAME}"
echo "namespace:   ${NAMESPACE}"
echo "kube_context:${KUBE_CONTEXT}"
echo "cronjob:     ${CRONJOB_NAME}"
echo ""

echo "[demo] Planned commands:"
echo "  kubectl config use-context ${KUBE_CONTEXT}"
echo "  kubectl -n ${NAMESPACE} get cronjob ${CRONJOB_NAME}"
echo "  kubectl -n ${NAMESPACE} create job weekly-rightsizing-manual-\$(date +%s) \\"
echo "    --from=cronjob/${CRONJOB_NAME}"
echo "  kubectl -n ${NAMESPACE} wait --for=condition=complete job -l job-name --timeout=600s"

# kubectl config use-context "${KUBE_CONTEXT}"
# kubectl -n "${NAMESPACE}" create job "weekly-rightsizing-manual-$(date +%s)" \
#   --from="cronjob/${CRONJOB_NAME}"

echo ""
echo "[demo] Weekly job trigger simulation completed for ${CLUSTER_NAME}"
