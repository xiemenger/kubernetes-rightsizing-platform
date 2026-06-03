#!/usr/bin/env bash
# Manually create a one-off Kubernetes Job from the weekly-rightsizing CronJob template.
#
# This script does NOT call the Flask API. Rightsizing execution runs inside the
# Job container via:
#   python -m app.scheduler.cluster_run
#
# GitLab CI (optional): schedule_weekly_rightsizing may invoke this script to
# trigger the CronJob template in a cluster for operator testing — the Python
# scheduler entrypoint still runs in Kubernetes, not in the GitLab runner.
#
# Usage:
#   ./scripts/trigger_weekly_job.sh <cluster_name> <namespace> <kube_context>

set -euo pipefail

CLUSTER_NAME="${1:?cluster_name required}"
NAMESPACE="${2:?namespace required}"
KUBE_CONTEXT="${3:?kube_context required}"

CRONJOB_NAME="weekly-rightsizing"

echo "=== Manual trigger: weekly-rightsizing CronJob ==="
echo "cluster:      ${CLUSTER_NAME}"
echo "namespace:    ${NAMESPACE}"
echo "kube_context: ${KUBE_CONTEXT}"
echo "cronjob:      ${CRONJOB_NAME}"
echo ""
echo "The spawned Job Pod runs: python -m app.scheduler.cluster_run"
echo ""

echo "[demo] Planned kubectl commands:"
echo "  kubectl config use-context ${KUBE_CONTEXT}"
echo "  kubectl -n ${NAMESPACE} get cronjob ${CRONJOB_NAME}"
echo "  kubectl -n ${NAMESPACE} create job weekly-rightsizing-manual-\$(date +%s) \\"
echo "    --from=cronjob/${CRONJOB_NAME}"
echo "  kubectl -n ${NAMESPACE} wait --for=condition=complete job -l job-name --timeout=3600s"

# kubectl config use-context "${KUBE_CONTEXT}"
# kubectl -n "${NAMESPACE}" create job "weekly-rightsizing-manual-$(date +%s)" \
#   --from="cronjob/${CRONJOB_NAME}"

echo ""
echo "[demo] CronJob manual trigger simulation completed for ${CLUSTER_NAME}"
