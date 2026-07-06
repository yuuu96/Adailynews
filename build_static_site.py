#!/usr/bin/env python3
"""Build the static GitHub Pages site for the daily intelligence report."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SITE_DIR = ROOT / "site"
WEB_DIR = ROOT / "web"
LATEST_JSON = ROOT / "reports" / "daily" / "latest.json"
LATEST_MD = ROOT / "reports" / "daily" / "latest.md"


def main() -> None:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    if not LATEST_JSON.exists():
        raise SystemExit("reports/daily/latest.json not found; run daily_intel.py first")
    shutil.copyfile(WEB_DIR / "static.html", SITE_DIR / "index.html")
    shutil.copyfile(WEB_DIR / "manifest.webmanifest", SITE_DIR / "manifest.webmanifest")
    shutil.copyfile(WEB_DIR / "sw.js", SITE_DIR / "sw.js")
    shutil.copyfile(WEB_DIR / "styles.css", SITE_DIR / "styles.css")
    shutil.copyfile(WEB_DIR / "render.js", SITE_DIR / "render.js")
    shutil.copyfile(LATEST_JSON, SITE_DIR / "latest.json")
    if LATEST_MD.exists():
        shutil.copyfile(LATEST_MD, SITE_DIR / "latest.md")
    report = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    version_key = re.sub(r"[^0-9A-Za-z_-]+", "-", f"{report.get('date')}-{report.get('generated_at')}".strip("-"))
    versioned_report = f"latest-{version_key}.json" if version_key else "latest-versioned.json"
    shutil.copyfile(LATEST_JSON, SITE_DIR / versioned_report)
    metadata = {
        "date": report.get("date"),
        "generated_at": report.get("generated_at"),
        "market_data_cutoff": report.get("market_data_cutoff"),
        "market_data_cutoff_note": report.get("market_data_cutoff_note"),
        "has_ai_summary": bool(report.get("ai_summary")),
        "report_url": f"./{versioned_report}",
    }
    (SITE_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built static site in {SITE_DIR}")


if __name__ == "__main__":
    main()
