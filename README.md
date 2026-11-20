# TP2 DevOps avancé : catalog-api

Chaîne de livraison continue sécurisée (Quality Gates, OPA Gatekeeper, GitOps) et ingénierie SRE
(SLI/SLO, Error Budget, burn rate) pour un microservice FastAPI observé avec OpenTelemetry,
Prometheus, Grafana, Loki et Tempo.

Le rapport SRE est dans [`report/RAPPORT_SRE.md`](report/RAPPORT_SRE.md) (et sa version PDF).

## Arborescence

| Chemin | Contenu |
|---|---|
| `app/` | Microservice FastAPI : `/products`, `/checkout` (lent), `/flaky` (erreurs), `/metrics`, `/health` |
| `app/telemetry.py` | OpenTelemetry : traces + logs JSON avec `trace_id`, export OTLP |
| `tests/` | Tests unitaires et d'intégration pytest (couverture Cobertura, seuil 85 %) |
| `Dockerfile` | Image multi-stage, utilisateur non-root |
| `sonar-project.properties` | Configuration SonarCloud |
| `.github/workflows/ci.yml` | Lint & Test → SonarCloud + Quality Gate → Build → Trivy (CRITICAL = échec) → Push GHCR → bump GitOps |
| `helm/catalog-api/` | Chart Helm déployé par ArgoCD |
| `argocd/application.yaml` | Application ArgoCD (auto-sync, self-heal) |
| `policies/gatekeeper/` | ConstraintTemplates Rego + Constraints (pas de `latest`, requests/limits obligatoires) |
| `policies/tests/` | Manifestes conforme / non conformes pour démontrer le rejet |
| `observability/` | Values Helm (Prometheus, Grafana, Alertmanager, Loki, Tempo, OTel Collector), règles SLO, dashboard |
| `k6/` | Script k6 (ramp-up 100 VU, stress 500 VU, spike 1500 VU) et Job Kubernetes |
| `scripts/` | Installation de la plateforme, génération du dashboard |

## Démarrage rapide (Minikube)

```bash
minikube start -p tp2 --cpus=6 --memory=5000
bash scripts/install-platform.sh
kubectl apply -f policies/gatekeeper/templates/ && kubectl apply -f policies/gatekeeper/constraints/
kubectl apply -f observability/slo-rules.yaml -f observability/alert-receiver.yaml -f observability/dashboards/configmap.yaml
kubectl apply -f argocd/application.yaml        # ou en local : helm upgrade --install catalog-api helm/catalog-api -n catalog -f helm/catalog-api/values-local.yaml
```

Tests locaux :

```bash
pip install -r requirements-dev.txt
pytest            # échoue si couverture < 85 %
```

Test de charge :

```bash
kubectl -n catalog create configmap k6-script --from-file=k6/load-test.js
kubectl apply -f k6/k6-job.yaml && kubectl -n catalog logs -f job/k6-load-test
```

## Secrets et variables GitHub Actions

| Nom | Type | Usage |
|---|---|---|
| `SONAR_TOKEN` | secret | Authentification SonarCloud |
| `SONAR_ORGANIZATION` | variable | Organisation SonarCloud |
| `SONAR_PROJECT_KEY` | variable | Clé du projet SonarCloud |
| `GITHUB_TOKEN` | automatique | Push de l'image sur GHCR et commit GitOps |

Aucun secret n'est écrit dans le dépôt.
