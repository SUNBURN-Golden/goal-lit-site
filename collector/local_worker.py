#!/usr/bin/env python3
"""로컬 작업기 데몬 & Chrome 수동 보충 수신 API 서버 (local_worker.py).

역할:
1. 브라우저는 자료를 읽는 도구로만 쓰고, 대기열 관리·중복 제거·PII 필터링·정규화는 본 로컬 작업기가 전담.
2. Chrome 확장프로그램('이 자료 담기', activeTab + scripting)이 전송하는 정제된 클립을
   `POST http://127.0.0.1:8791/api/clip`으로 수신하여 저장 전 2차 PII 필터(`sanitize_and_filter_record`) 적용 후 SQLite에 저장.
3. 서비스워커 종료 후 재개 시 `GET /api/queue/resume` 및 `POST /api/queue/ack`로 중단 지점(`cursor_pos`)부터 재개 지원.
4. `GET /api/status`로 후보·원문 확인·중복 제외·검증 완료·공개 대기 5단계 현황을 실시간 반환.
"""
import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
import urllib.parse

from config import BRAND, LOCAL_WORKER_HOST, LOCAL_WORKER_PORT
from politeness import PolitenessManager, is_trap_or_disallowed_url
from storage import CollectorStorage, now_kst_iso


class LocalWorkerHandler(BaseHTTPRequestHandler):
    storage = CollectorStorage()
    politeness = PolitenessManager(storage.db_path)

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # 개인정보나 쿼리가 표준에러에 무분별하게 찍히지 않도록 억제

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-GoalLit-Client")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/status":
            summary = self.storage.get_status_summary()
            summary["daily_politeness"] = self.politeness.get_daily_counts()
            self._send_json(200, summary)
            return
        if parsed.path == "/api/queue/resume":
            with self.storage._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT queue_id, url, target_work_slug, collection_path, link_depth, priority, cursor_pos, updated_at
                    FROM crawl_queue
                    WHERE brand = ? AND state IN ('queued', 'in_progress')
                    ORDER BY priority DESC, updated_at ASC
                    LIMIT 25
                    """,
                    (BRAND,),
                ).fetchall()
            items = [dict(r) for r in rows]
            self._send_json(200, {"ok": True, "brand": BRAND, "resumable_count": len(items), "queue": items})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 256_000:
            self._send_json(400, {"ok": False, "error": "invalid_payload_size"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except Exception:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        if parsed.path == "/api/clip":
            url = str(data.get("url") or "").strip()
            disallowed, reason = is_trap_or_disallowed_url(url, depth=0)
            if disallowed:
                self._send_json(422, {"ok": False, "error": f"disallowed_url:{reason}"})
                return
            record = {
                "brand": str(data.get("brand") or BRAND),
                "collection_path": "manual_clip",
                "url": url,
                "title": str(data.get("title") or url),
                "outlet": str(data.get("outlet") or ""),
                "published_at": str(data.get("published_at") or ""),
                "collected_at": now_kst_iso(),
                "target_work_slug": str(data.get("target_work_slug") or "general"),
                "validation_status": str(data.get("validation_status") or "source_checked"),
                "bundle_type": str(data.get("bundle_type") or "research_bundle"),
                "source_access_level": str(data.get("source_access_level") or "press_article"),
                "work": data.get("work") or {},
                "edition": data.get("edition") or {},
                "author_statement": str(data.get("author_statement") or ""),
                "critical_thesis": str(data.get("critical_thesis") or ""),
                "counter_argument": str(data.get("counter_argument") or ""),
                "extracted_facts": data.get("extracted_facts") or [
                    {"label": "수동 클립 발췌", "claim": str(data.get("excerpt") or "")[:350]}
                ],
                "evidence_locator": str(data.get("evidence_locator") or "manual_activeTab_selection"),
            }
            saved = self.storage.upsert_item(record, auto_dedup=True)
            if data.get("cursor_pos") or data.get("queue_id"):
                self.storage.enqueue_url(
                    url=url,
                    target_work_slug=record["target_work_slug"],
                    collection_path="manual_clip",
                    cursor_pos=str(data.get("cursor_pos") or "completed"),
                )
            self._send_json(
                200,
                {
                    "ok": True,
                    "id": saved["id"],
                    "validation_status": saved["validation_status"],
                    "dedup_cluster_id": saved["dedup_cluster_id"],
                    "pii_redactions_count": saved["pii_redactions_count"],
                    "prompt_injection_detected": saved["prompt_injection_detected"],
                },
            )
            return

        if parsed.path == "/api/queue/checkpoint":
            url = str(data.get("url") or "").strip()
            if not url:
                self._send_json(400, {"ok": False, "error": "missing_url"})
                return
            qid = self.storage.enqueue_url(
                url=url,
                target_work_slug=str(data.get("target_work_slug") or ""),
                collection_path=str(data.get("collection_path") or "manual_clip"),
                link_depth=int(data.get("link_depth") or 0),
                priority=int(data.get("priority") or 60),
                cursor_pos=str(data.get("cursor_pos") or ""),
                payload=data.get("payload") or {},
            )
            self._send_json(200, {"ok": True, "queue_id": qid})
            return

        self._send_json(404, {"ok": False, "error": "not_found"})


def run_server(host: str = LOCAL_WORKER_HOST, port: int = LOCAL_WORKER_PORT) -> None:
    server = ThreadingHTTPServer((host, port), LocalWorkerHandler)
    print(f"Goal Lit Local Worker listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Goal Lit local worker HTTP server")
    ap.add_argument("--host", default=LOCAL_WORKER_HOST)
    ap.add_argument("--port", type=int, default=LOCAL_WORKER_PORT)
    args = ap.parse_args()
    run_server(args.host, args.port)
