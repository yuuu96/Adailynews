#!/usr/bin/env python3
"""Local mobile-first web UI for the daily A-share intelligence report."""
from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from daily_intel import generate_report, jsonable, load_latest


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def update_job(job_id: str, patch: dict) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(patch)
        job["updated_at"] = time.time()


def run_job(job_id: str, api_key: str | None, model: str | None) -> None:
    def progress(event: dict) -> None:
        done = int(event.get("done", 0))
        total = max(int(event.get("total", 1)), 1)
        update_job(
            job_id,
            {
                "status": "running",
                "progress": round(done / total * 100),
                "stage": event.get("stage"),
                "current_source": event.get("source"),
                "last_event": event,
            },
        )

    update_job(
        job_id,
        {
            "status": "running",
            "progress": 1,
            "stage": "starting",
            "current_source": "启动采集",
            "started_at": time.time(),
        },
    )
    try:
        report = generate_report(api_key=api_key, model=model, progress_callback=progress)
        update_job(job_id, {"status": "done", "progress": 100, "current_source": "完成", "report": report})
    except Exception as exc:
        update_job(job_id, {"status": "failed", "progress": 100, "error": f"{type(exc).__name__}: {str(exc)}"})


class IntelHandler(BaseHTTPRequestHandler):
    server_version = "AStockIntel/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path == "/api/latest":
            self.send_json(load_latest() or {"empty": True, "message": "暂无报告，请点击一键生成。"})
            return
        if parsed.path.startswith("/api/job/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if not job:
                self.send_json({"ok": False, "error": "job not found"}, status=404)
                return
            self.send_json(job)
            return
        if parsed.path == "/":
            self.send_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        static_path = (WEB_DIR / parsed.path.lstrip("/")).resolve()
        if WEB_DIR in static_path.parents and static_path.exists() and static_path.is_file():
            content_type = None
            if static_path.name == "manifest.webmanifest":
                content_type = "application/manifest+json"
            elif static_path.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif static_path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            self.send_file(static_path, content_type)
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self.send_error(404, "Not found")
            return
        try:
            payload = self.read_json_body()
            job_id = uuid.uuid4().hex
            api_key = (payload.get("deepseek_api_key") or "").strip() or None
            model = (payload.get("deepseek_model") or "").strip() or None
            thread = threading.Thread(target=run_job, args=(job_id, api_key, model), daemon=True)
            thread.start()
            self.send_json({"ok": True, "job_id": job_id}, status=202)
        except Exception as exc:
            self.send_json({"ok": False, "error": f"{type(exc).__name__}: {str(exc)}"}, status=500)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[intel-web] {self.address_string()} - {fmt % args}")

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(jsonable(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Not found")
            return
        body = path.read_bytes()
        guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type or guessed)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local A-share intelligence PWA server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host, use 0.0.0.0 for phone access on LAN")
    parser.add_argument("--port", default=8765, type=int, help="bind port")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), IntelHandler)
    print(f"Serving A股情报 PWA at http://{args.host}:{args.port}")
    print("Set DEEPSEEK_API_KEY before running if you want AI summaries.")
    server.serve_forever()


if __name__ == "__main__":
    main()
