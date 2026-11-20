"""Convertit report/RAPPORT_SRE.md en report/RAPPORT_SRE.pdf (Markdown -> HTML -> PDF via Edge)."""

from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

REPORT = Path(__file__).resolve().parent.parent / "report"

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1f2328; }
h1 { font-size: 20pt; border-bottom: 3px solid #0969da; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 15pt; color: #0969da; border-bottom: 1px solid #d0d7de; padding-bottom: 3px;
     margin-top: 26px; page-break-after: avoid; }
h3 { font-size: 12pt; margin-top: 18px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f6f8fa; padding: 1px 4px; border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 9px 11px;
      font-size: 8.4pt; line-height: 1.35; white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
img { max-width: 100%; border: 1px solid #d0d7de; border-radius: 4px; margin: 6px 0;
      page-break-inside: avoid; }
blockquote { border-left: 4px solid #0969da; margin: 10px 0; padding: 2px 12px; color: #444;
             background: #f6f8fa; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 20px 0; }
.math { font-family: 'Cambria Math', serif; }
"""


def main() -> None:
    text = (REPORT / "RAPPORT_SRE.md").read_text(encoding="utf-8")
    # Formule LaTeX du burn rate -> forme lisible sans moteur MathJax.
    text = text.replace(
        "$$\\text{burn rate} = \\frac{\\text{taux d'erreur}}{1 - \\text{SLO}} \\qquad "
        "\\text{budget consommé sur } W = \\text{burn rate} \\times \\frac{W}{30\\,\\text{j}}$$",
        "**burn rate = taux d'erreur / (1 − SLO)**  et  "
        "**budget consommé sur W = burn rate × W / 30 j**",
    )
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    html = f'<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{body}</body></html>'
    out_html = REPORT / "RAPPORT_SRE.html"
    out_html.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page()
        page.goto(out_html.as_uri())
        page.wait_for_load_state("networkidle")
        page.pdf(
            path=str(REPORT / "RAPPORT_SRE.pdf"),
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<span></span>",
            footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#888">'
            'TP2 DevOps avancé - catalog-api - <span class="pageNumber"></span>/'
            '<span class="totalPages"></span></div>',
            margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
        )
        browser.close()
    print("ok", REPORT / "RAPPORT_SRE.pdf")


if __name__ == "__main__":
    main()
