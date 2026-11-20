"""Génère le dashboard Grafana SRE (méthode RED + Error Budget) et sa ConfigMap.

Usage : python scripts/build_dashboard.py
Sortie : observability/dashboards/catalog-sre.json et observability/dashboards/configmap.yaml
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "observability" / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
SEL = 'app="catalog-api"'

_next_id = 0


def panel(title, kind, targets, x, y, w, h, **extra):
    global _next_id
    _next_id += 1
    p = {
        "id": _next_id,
        "title": title,
        "type": kind,
        "datasource": PROM,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [
            {"refId": chr(65 + i), "expr": expr, "legendFormat": legend, "datasource": PROM}
            for i, (expr, legend) in enumerate(targets)
        ],
    }
    p.update(extra)
    return p


def thresholds(*steps):
    return {
        "mode": "absolute",
        "steps": [{"color": c, "value": v} for v, c in steps],
    }


def row(title, y):
    global _next_id
    _next_id += 1
    return {
        "id": _next_id,
        "type": "row",
        "title": title,
        "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "panels": [],
    }


panels = [
    row("SLO & Error Budget", 0),
    panel(
        "Error Budget restant (SLO dispo 99,5 % / $window)",
        "gauge",
        [
            (
                f'1 - ((sum(increase(http_requests_total{{{SEL},status=~"5.."}}[$window])) '
                f"/ sum(increase(http_requests_total{{{SEL}}}[$window]))) / 0.005)",
                "budget",
            )
        ],
        0,
        1,
        6,
        8,
        fieldConfig={
            "defaults": {
                "unit": "percentunit",
                "min": -1,
                "max": 1,
                "decimals": 1,
                "thresholds": thresholds((None, "red"), (0, "orange"), (0.5, "green")),
            },
            "overrides": [],
        },
        options={"showThresholdMarkers": True, "reduceOptions": {"calcs": ["lastNotNull"]}},
    ),
    panel(
        "Disponibilité (SLI) sur $window",
        "stat",
        [
            (
                f'1 - sum(increase(http_requests_total{{{SEL},status=~"5.."}}[$window])) '
                f"/ sum(increase(http_requests_total{{{SEL}}}[$window]))",
                "SLI",
            )
        ],
        6,
        1,
        4,
        4,
        fieldConfig={
            "defaults": {
                "unit": "percentunit",
                "decimals": 3,
                "thresholds": thresholds((None, "red"), (0.995, "green")),
            },
            "overrides": [],
        },
        options={"colorMode": "background", "reduceOptions": {"calcs": ["lastNotNull"]}},
    ),
    panel(
        "Latence : part < 200 ms sur $window",
        "stat",
        [
            (
                f'sum(increase(http_request_duration_seconds_bucket{{{SEL},le="0.2"}}[$window])) '
                f"/ sum(increase(http_request_duration_seconds_count{{{SEL}}}[$window]))",
                "SLI",
            )
        ],
        6,
        5,
        4,
        4,
        fieldConfig={
            "defaults": {
                "unit": "percentunit",
                "decimals": 2,
                "thresholds": thresholds((None, "red"), (0.95, "green")),
            },
            "overrides": [],
        },
        options={"colorMode": "background", "reduceOptions": {"calcs": ["lastNotNull"]}},
    ),
    panel(
        "Burn Rate (disponibilité)",
        "timeseries",
        [
            ("catalog:burn_rate:5m", "5 min"),
            ("catalog:burn_rate:1h", "1 h"),
            ("catalog:burn_rate:30m", "30 min"),
            ("catalog:burn_rate:6h", "6 h"),
        ],
        10,
        1,
        14,
        8,
        fieldConfig={
            "defaults": {
                "unit": "x",
                "min": 0,
                "custom": {"thresholdsStyle": {"mode": "line+area"}, "lineWidth": 2},
                "thresholds": thresholds((None, "transparent"), (6, "orange"), (14.4, "red")),
            },
            "overrides": [],
        },
        description="Seuils : 6 (warning, 5 % du budget en 6 h) et 14,4 (critical, 2 % du budget en 1 h).",
    ),
    row("RED : Rate / Errors / Duration", 9),
    panel(
        "Rate : requêtes par seconde (RPS)",
        "timeseries",
        [
            (f"sum(rate(http_requests_total{{{SEL}}}[1m]))", "total"),
            (f"sum by (route) (rate(http_requests_total{{{SEL}}}[1m]))", "{{route}}"),
        ],
        0,
        10,
        12,
        8,
        fieldConfig={"defaults": {"unit": "reqps"}, "overrides": []},
    ),
    panel(
        "Errors : erreurs 5xx par seconde",
        "timeseries",
        [
            (
                f'sum by (route, status) (rate(http_requests_total{{{SEL},status=~"5.."}}[1m]))',
                "{{route}} {{status}}",
            )
        ],
        12,
        10,
        6,
        8,
        fieldConfig={
            "defaults": {"unit": "reqps", "color": {"mode": "fixed", "fixedColor": "red"}},
            "overrides": [],
        },
    ),
    panel(
        "Errors : % d'erreur global",
        "stat",
        [
            (
                f'sum(rate(http_requests_total{{{SEL},status=~"5.."}}[1m])) '
                f"/ sum(rate(http_requests_total{{{SEL}}}[1m]))",
                "erreurs",
            )
        ],
        18,
        10,
        6,
        8,
        fieldConfig={
            "defaults": {
                "unit": "percentunit",
                "decimals": 2,
                "thresholds": thresholds((None, "green"), (0.005, "orange"), (0.072, "red")),
            },
            "overrides": [],
        },
        options={
            "colorMode": "background",
            "graphMode": "area",
            "reduceOptions": {"calcs": ["lastNotNull"]},
        },
    ),
    panel(
        "Duration : latence p50 / p90 / p95 / p99",
        "timeseries",
        [
            (
                f"histogram_quantile({q}, sum by (le) (rate(http_request_duration_seconds_bucket{{{SEL}}}[1m])))",
                f"p{int(q * 100)}",
            )
            for q in (0.5, 0.9, 0.95, 0.99)
        ],
        0,
        18,
        16,
        9,
        fieldConfig={
            "defaults": {
                "unit": "s",
                "custom": {"thresholdsStyle": {"mode": "dashed"}},
                "thresholds": thresholds((None, "transparent"), (0.2, "red")),
            },
            "overrides": [],
        },
        options={"tooltip": {"mode": "multi"}},
    ),
    panel(
        "Duration : p95 par route",
        "timeseries",
        [
            (
                f"histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket{{{SEL}}}[1m])))",
                "{{route}}",
            )
        ],
        16,
        18,
        8,
        9,
        fieldConfig={"defaults": {"unit": "s"}, "overrides": []},
    ),
    row("Corrélation logs / traces", 27),
]

_next_id += 1
panels.append(
    {
        "id": _next_id,
        "title": "Logs catalog-api (cliquer sur trace_id -> Tempo)",
        "type": "logs",
        "datasource": LOKI,
        "gridPos": {"x": 0, "y": 28, "w": 24, "h": 10},
        "targets": [{"refId": "A", "datasource": LOKI, "queryType": "range", "expr": '{service_name="catalog-api"}'}],
        "options": {"showTime": True, "enableLogDetails": True, "sortOrder": "Descending"},
    }
)

dashboard = {
    "uid": "catalog-sre",
    "title": "catalog-api - SRE (RED & Error Budget)",
    "tags": ["sre", "slo", "red"],
    "timezone": "browser",
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "schemaVersion": 39,
    "templating": {
        "list": [
            {
                "name": "window",
                "label": "Fenêtre SLO",
                "type": "custom",
                "query": "1h,6h,24h,30d",
                "current": {"text": "30d", "value": "30d"},
                "options": [
                    {"text": v, "value": v, "selected": v == "30d"}
                    for v in ("1h", "6h", "24h", "30d")
                ],
            }
        ]
    },
    "panels": panels,
}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "catalog-sre.json").write_text(
    json.dumps(dashboard, indent=2, ensure_ascii=False), encoding="utf-8"
)
indented = "\n".join(
    "    " + line for line in json.dumps(dashboard, indent=2, ensure_ascii=False).splitlines()
)
(OUT / "configmap.yaml").write_text(
    "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: catalog-sre-dashboard\n"
    '  namespace: observability\n  labels:\n    grafana_dashboard: "1"\n'
    f"data:\n  catalog-sre.json: |\n{indented}\n",
    encoding="utf-8",
)
print("ok", len(panels), "panels")
