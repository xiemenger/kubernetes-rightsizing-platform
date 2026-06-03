#!/usr/bin/env bash
# Create a one-off Kubernetes Job for weekly rightsizing execution.
#
# Primary trigger: GitLab Pipeline Schedule → schedule_weekly_rightsizing
# (see .gitlab-ci.yml). This script does NOT run Python on the GitLab runner;
# the Job Pod runs: python -m app.scheduler.cluster_run
#
# Usage:
#   ./scripts/trigger_weekly_job.sh <cluster_name> <namespace> <kube_context> [image_tag]

set -euo pipefail

CLUSTER_NAME="${1:?cluster_name required}"
NAMESPACE="${2:?namespace required}"
KUBE_CONTEXT="${3:?kube_context required}"
IMAGE_TAG="${4:-REPLACE_ME}"

JOB_NAME="rightsizing-$(date +%s)"
TEMPLATE="${CI_PROJECT_DIR:-.}/deploy/k8s/job-template.yaml"
RENDERED="/tmp/${JOB_NAME}.yaml"

echo "=== Weekly rightsizing: create Kubernetes Job ==="
echo "cluster:      ${CLUSTER_NAME}"
echo "namespace:    ${NAMESPACE}"
echo "kube_context: ${KUBE_CONTEXT}"
echo "job_name:     ${JOB_NAME}"
echo "template:     ${TEMPLATE}"
echo ""
echo "Pod command:  python -m app.scheduler.cluster_run"
echo "The Job Pod schedules namespace-batch Celery tasks and exits (not long-running)."
echo ""

sed -e "s/rightsizing-REPLACE_ME/${JOB_NAME}/g" \
    -e "s/right-sizing:REPLACE_ME/right-sizing:${IMAGE_TAG}/g" \
    -e "s/value: \"prod-us-east-1\"/value: \"${CLUSTER_NAME}\"/" \
    "${TEMPLATE}" > "${RENDERED}"

echo "[demo] Planned kubectl commands:"
echo "  kubectl config use-context ${KUBE_CONTEXT}"
echo "  kubectl -n ${NAMESPACE} apply -f ${RENDERED}"
echo "  kubectl -n ${NAMESPACE} wait --for=condition=complete \"job/${JOB_NAME}\" --timeout=3600s"
echo "  kubectl -n ${NAMESPACE} get job ${JOB_NAME}"

# kubectl config use-context "${KUBE_CONTEXT}"
# kubectl -n "${NAMESPACE}" apply -f "${RENDERED}"
# kubectl -n "${NAMESPACE}" wait --for=condition=complete "job/${JOB_NAME}" --timeout=3600s

echo ""
echo "[demo] Kubernetes Job trigger simulation completed for ${CLUSTER_NAME}"
