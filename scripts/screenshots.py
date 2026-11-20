"""Captures d'écran pour le rapport (Grafana, Prometheus, Alertmanager, ArgoCD).

Usage : python scripts/screenshots.py <nom> [<nom> ...]
Noms : dashboard, alerts, alertmanager, explore-logs, trace, argocd
Nécessite scripts/port-forward.sh en cours d'exécution.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "report" / "img"
GRAFANA = "http://localhost:3000"

PAGES = {
    "dashboard": (f"{GRAFANA}/d/catalog-sre/?orgId=1&from=now-30m&to=now&kiosk&theme=light", 12),
    "dashboard-1h": (f"{GRAFANA}/d/catalog-sre/?orgId=1&from=now-1h&to=now&kiosk&theme=light&var-window=1h", 12),
    "alerts": ("http://localhost:9090/alerts?state=firing&state=pending", 4),
    "alertmanager": ("http://localhost:9093/#/alerts", 4),
    "argocd": ("http://localhost:8081/applications/argocd/catalog-api?view=tree", 8),
}


def shoot(page, name, url, wait):
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(wait)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print("ok", path.name)


def main(names):
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1650},
            http_credentials={"username": "admin", "password": "tp2-admin"},
            color_scheme="light",
        )
        page = ctx.new_page()
        page.goto(f"{GRAFANA}/login")
        page.fill("input[name=user]", "admin")
        page.fill("input[name=password]", "tp2-admin")
        page.click("button[type=submit]")
        page.wait_for_url(lambda u: "/login" not in u, timeout=15000)
        for name in names:
            if name.startswith("url="):  # capture libre : url=<url>|<nom>
                url, out = name[4:].rsplit("|", 1)
                shoot(page, out, url, 10)
            else:
                shoot(page, name, *PAGES[name])
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or ["dashboard"])
