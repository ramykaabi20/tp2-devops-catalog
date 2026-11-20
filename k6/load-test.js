// Test de charge catalog-api : ramp-up 100 VU -> stress 500 VU -> spike 1500 VU (30 s).
// Les seuils reprennent les SLO : disponibilité 99,5 % et p95 <= 200 ms.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const SCALE = Number(__ENV.SCALE || 1); // 0.1 pour une répétition rapide en local

const serverErrors = new Rate('server_errors'); // SLI disponibilité : status >= 500
const checkoutDuration = new Trend('checkout_duration', true);

const vu = (n) => Math.max(1, Math.round(n * SCALE));

export const options = {
  discardResponseBodies: true,
  scenarios: {
    ramp_up: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: vu(100) },
        { duration: '2m', target: vu(100) },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '10s',
      tags: { scenario: 'ramp_up' },
    },
    stress: {
      executor: 'ramping-vus',
      startTime: '4m40s',
      startVUs: 0,
      stages: [
        { duration: '1m', target: vu(500) },
        { duration: '5m', target: vu(500) }, // palier prolongé
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '10s',
      tags: { scenario: 'stress' },
    },
    spike: {
      executor: 'ramping-vus',
      startTime: '11m20s',
      startVUs: 0,
      stages: [
        { duration: '10s', target: vu(1500) }, // montée brutale
        { duration: '30s', target: vu(1500) }, // pic pendant 30 s
        { duration: '10s', target: 0 },
      ],
      gracefulRampDown: '5s',
      tags: { scenario: 'spike' },
    },
  },
  thresholds: {
    server_errors: ['rate<0.005'], // SLO disponibilité 99,5 %
    http_req_duration: ['p(95)<200'], // SLO latence
    'http_req_duration{scenario:ramp_up}': ['p(95)<200'],
    'http_req_duration{scenario:stress}': ['p(95)<200'],
    'http_req_duration{scenario:spike}': ['p(95)<200'],
    'server_errors{scenario:spike}': ['rate<0.005'],
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const JSON_HEADERS = { headers: { 'Content-Type': 'application/json' }, timeout: '10s' };

function record(res, name) {
  serverErrors.add(res.status >= 500 || res.status === 0);
  check(res, { [`${name} pas de 5xx`]: (r) => r.status > 0 && r.status < 500 });
}

// Parcours réaliste : 40 % liste, 25 % fiche produit, 20 % checkout, 15 % flaky.
export default function () {
  const p = Math.random();
  if (p < 0.4) {
    record(http.get(`${BASE_URL}/products`, { tags: { name: 'GET /products' }, timeout: '10s' }), 'list');
  } else if (p < 0.65) {
    const id = 1 + Math.floor(Math.random() * 3);
    record(http.get(`${BASE_URL}/products/${id}`, { tags: { name: 'GET /products/{id}' }, timeout: '10s' }), 'get');
  } else if (p < 0.85) {
    const res = http.post(
      `${BASE_URL}/checkout`,
      JSON.stringify({ product_id: 2, quantity: 1 }),
      Object.assign({ tags: { name: 'POST /checkout' } }, JSON_HEADERS),
    );
    checkoutDuration.add(res.timings.duration);
    record(res, 'checkout');
  } else {
    record(http.get(`${BASE_URL}/flaky`, { tags: { name: 'GET /flaky' }, timeout: '10s' }), 'flaky');
  }
  sleep(0.5 + Math.random()); // temps de réflexion de l'utilisateur : 0,5 à 1,5 s
}

export function handleSummary(data) {
  return {
    stdout: textSummary(data),
    '/tmp/summary.json': JSON.stringify(data, null, 2),
  };
}

function textSummary(data) {
  const m = data.metrics;
  const d = m.http_req_duration.values;
  const lines = [
    '===== Résumé k6 catalog-api =====',
    `Requêtes : ${m.http_reqs.values.count} (${m.http_reqs.values.rate.toFixed(1)} req/s)`,
    `Erreurs serveur (5xx/timeout) : ${(m.server_errors.values.rate * 100).toFixed(3)} %`,
    `Latence p50=${d['p(50)'].toFixed(1)} ms  p90=${d['p(90)'].toFixed(1)} ms  p95=${d['p(95)'].toFixed(1)} ms  p99=${d['p(99)'].toFixed(1)} ms  max=${d.max.toFixed(1)} ms`,
    `VU max : ${m.vus_max.values.max}`,
    'Seuils :',
  ];
  for (const [name, metric] of Object.entries(m)) {
    if (!metric.thresholds) continue;
    for (const [expr, res] of Object.entries(metric.thresholds)) {
      lines.push(`  ${res.ok ? 'OK  ' : 'KO  '} ${name} ${expr}`);
    }
  }
  return lines.join('\n') + '\n';
}
