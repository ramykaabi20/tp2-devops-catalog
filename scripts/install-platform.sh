#!/usr/bin/env bash
# Installe la plateforme du TP sur le cluster courant :
# OPA Gatekeeper, ArgoCD, Prometheus/Alertmanager/Grafana, Loki, Tempo, OTel Collector.
set -euo pipefail
cd "$(dirname "$0")/.."
V=observability

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null
helm repo add gatekeeper https://open-policy-agent.github.io/gatekeeper/charts >/dev/null
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo update >/dev/null

install() { # release chart namespace values
  echo "==> $1"
  helm upgrade --install "$1" "$2" -n "$3" --create-namespace -f "$4" --wait --timeout 15m
}

install gatekeeper gatekeeper/gatekeeper gatekeeper-system $V/gatekeeper.values.yaml
install kube-prometheus-stack prometheus-community/kube-prometheus-stack observability $V/kube-prometheus-stack.values.yaml
install loki grafana/loki observability $V/loki.values.yaml
install tempo grafana/tempo observability $V/tempo.values.yaml
install otel-collector open-telemetry/opentelemetry-collector observability $V/otel-collector.values.yaml
install argocd argo/argo-cd argocd $V/argocd.values.yaml
echo "==> plateforme prête"
