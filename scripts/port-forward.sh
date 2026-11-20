#!/usr/bin/env bash
# Accès locaux : Prometheus :9090, Grafana :3000, Alertmanager :9093, ArgoCD :8081, API :8080.
# Chaque port-forward est relancé s'il tombe (redéploiement de pods).
keep() { while true; do kubectl "$@" >/dev/null 2>&1; sleep 2; done; }
keep -n observability port-forward svc/kube-prometheus-stack-prometheus 9090:9090 &
keep -n observability port-forward svc/kube-prometheus-stack-grafana 3000:80 &
keep -n observability port-forward svc/kube-prometheus-stack-alertmanager 9093:9093 &
keep -n argocd port-forward svc/argocd-server 8081:80 &
keep -n catalog port-forward svc/catalog-api 8080:80 &
wait
