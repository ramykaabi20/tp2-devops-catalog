"""Exécute une commande et enregistre sa sortie réelle en PNG (style terminal).

Usage : python scripts/terminal_capture.py <nom.png> "<commande>"
"""

import html
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "report" / "img"


def main(name: str, command: str) -> None:
    result = subprocess.run(command, shell=True, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    text = f"$ {command}\n{result.stdout}{result.stderr}"
    body = html.escape(text)
    body = body.replace("denied the request", '<span class="red">denied the request</span>')
    body = body.replace(" created\n", ' <span class="green">created</span>\n')
    page_html = f"""<html><head><meta charset="utf-8"><style>
      body {{ margin:0; background:#1e1e1e; }}
      pre {{ margin:0; padding:18px 22px; color:#d4d4d4; font:14px/1.45 Consolas,monospace;
             white-space:pre-wrap; word-break:break-word; }}
      .red {{ color:#f14c4c; font-weight:bold; }} .green {{ color:#23d18b; font-weight:bold; }}
    </style></head><body><pre>{body}</pre></body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1300, "height": 200})
        page.set_content(page_html)
        page.screenshot(path=str(OUT / name), full_page=True)
        browser.close()
    print(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
