#!/usr/bin/env bash
# Scénario d'incident simulé pendant le test k6 :
#   T0          : lancement k6 (ramp-up 100 VU, stress 500 VU, spike 1500 VU)
#   T0 + 5m     : déploiement d'une release défectueuse (FLAKY_ERROR_RATE=0.8)
#   fin du spike: rollback vers la release saine (helm rollback)
# Les horodatages sont écrits dans k6/results/timeline.txt pour le rapport.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p k6/results
LOG=k6/results/timeline.txt
VALUES=helm/catalog-api/values-local.yaml
stamp() { echo "$(date -u +%H:%M:%S) UTC - $*" | tee -a "$LOG"; }

: > "$LOG"
kubectl -n catalog delete job k6-load-test --ignore-not-found >/dev/null
kubectl -n catalog create configmap k6-script --from-file=k6/load-test.js --dry-run=client -o yaml | kubectl apply -f - >/dev/null
GOOD_REV=$(helm history catalog-api -n catalog -o json | python -c "import json,sys;print(json.load(sys.stdin)[-1]['revision'])")
kubectl apply -f k6/k6-job.yaml >/dev/null
# Le chronomètre démarre quand le pod k6 tourne (le tirage d'image peut prendre du temps).
kubectl -n catalog wait --for=condition=ready pod -l job-name=k6-load-test --timeout=5m >/dev/null
stamp "k6 démarré (release saine = révision $GOOD_REV)"

sleep 320  # milieu du palier de stress à 500 VU
stamp "INCIDENT : déploiement d'une release défectueuse (FLAKY_ERROR_RATE=0.8)"
helm upgrade catalog-api helm/catalog-api -n catalog -f "$VALUES" \
  --set env.FLAKY_ERROR_RATE=0.8 --wait >/dev/null
stamp "release défectueuse en ligne"

sleep 420  # après le spike à 1500 VU
stamp "MITIGATION : helm rollback vers la révision $GOOD_REV"
helm rollback catalog-api "$GOOD_REV" -n catalog --wait >/dev/null
stamp "rollback terminé"

kubectl -n catalog wait --for=condition=complete --for=condition=failed job/k6-load-test --timeout=15m >/dev/null 2>&1 || true
kubectl -n catalog logs job/k6-load-test > k6/results/k6-output.txt 2>&1 || true
stamp "k6 terminé"
