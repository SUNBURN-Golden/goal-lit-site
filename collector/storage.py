#!/usr/bin/env python3
"""Goal Lit (꼴릿) 수집함 SQLite 스토리지 및 5단계 상태·충돌 보존·큐 영속화 모듈.

핵심 불변 조건:
1. 모든 레코드와 큐 항목은 DB 기록 직전에 반드시 `pii_filter.sanitize_and_filter_record`를 통과한다.
2. `discovered`(발견 후보)와 `source_checked`/`verified_ready`(원문 확인·검증 완료)는 엄격히 구분한다.
3. 서로 다른 출처의 주장이 충돌(`conflict = 1`)하면 두 레코드 모두 보존하고, 중복 제외(`deduped`)로 덮어쓰지 않으며, 해결 전까지 자동 `publish_pending` 승격을 차단한다.
4. `source_access_level`은 `book_intro` / `paper_abstract` / `full_text_read` / `press_article` / `author_interview` 5종만 허용하며, 논문 초록(`paper_abstract`)이나 언론 기사(`press_article`)가 `full_text_read`(실제 원문 독서 기록)로 둔갑하는 것을 차단한다.
5. 사이트 라이브 게시(`build_site.py`)는 절대 자동 호출하지 않는다 (`AUTO_PUBLISH_TO_SITE = False`).
"""
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    AUTO_PUBLISH_TO_SITE,
    BRAND,
    DB_PATH,
    SOURCE_ACCESS_LEVELS,
    STATUS_SUMMARY_PATH,
    UNVERIFIED_CATEGORIES,
    VALID_STATUSES,
)
from dedup import canonicalize_url, compute_dedup_cluster_id, extract_identifier_key
from pii_filter import filter_pii_text, sanitize_and_filter_record

KST = dt.timezone(dt.timedelta(hours=9))


def now_kst_iso() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


class CollectorStorage:
    def __init__(self, db_path: Path = DB_PATH, brand: str = BRAND):
        self.db_path = Path(db_path)
        self.brand = brand
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    brand TEXT NOT NULL DEFAULT 'goal-lit',
                    collection_path TEXT NOT NULL,
                    url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    outlet TEXT NOT NULL,
                    published_at TEXT NOT NULL DEFAULT '',
                    collected_at TEXT NOT NULL,
                    target_work_slug TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    bundle_type TEXT NOT NULL DEFAULT 'research_bundle',
                    source_access_level TEXT NOT NULL,
                    unverified_category TEXT NOT NULL DEFAULT '',
                    work_info_json TEXT NOT NULL DEFAULT '{}',
                    edition_info_json TEXT NOT NULL DEFAULT '{}',
                    author_statement TEXT NOT NULL DEFAULT '',
                    critical_thesis TEXT NOT NULL DEFAULT '',
                    counter_argument TEXT NOT NULL DEFAULT '',
                    extracted_facts_json TEXT NOT NULL DEFAULT '[]',
                    evidence_locator TEXT NOT NULL DEFAULT '',
                    dedup_cluster_id TEXT NOT NULL,
                    is_cluster_primary INTEGER NOT NULL DEFAULT 1,
                    conflict INTEGER NOT NULL DEFAULT 0,
                    conflict_note TEXT NOT NULL DEFAULT '',
                    conflict_with_id TEXT NOT NULL DEFAULT '',
                    pii_filtered INTEGER NOT NULL DEFAULT 1,
                    pii_redactions_count INTEGER NOT NULL DEFAULT 0,
                    prompt_injection_detected INTEGER NOT NULL DEFAULT 0,
                    fulltext_allowed INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_items_brand_status ON items(brand, validation_status);
                CREATE INDEX IF NOT EXISTS idx_items_work ON items(target_work_slug);
                CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(dedup_cluster_id);
                CREATE INDEX IF NOT EXISTS idx_items_access ON items(source_access_level);

                CREATE TABLE IF NOT EXISTS crawl_queue (
                    queue_id TEXT PRIMARY KEY,
                    brand TEXT NOT NULL DEFAULT 'goal-lit',
                    url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    target_work_slug TEXT NOT NULL DEFAULT '',
                    collection_path TEXT NOT NULL DEFAULT 'auto',
                    link_depth INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 50,
                    state TEXT NOT NULL DEFAULT 'queued',
                    cursor_pos TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_queue_state_prio ON crawl_queue(brand, state, priority DESC);
                """
            )

    def upsert_item(self, raw_record: Dict[str, Any], auto_dedup: bool = True) -> Dict[str, Any]:
        """저장 전 PII 필터 및 프롬프트 인젝션 격리를 강제 적용한 뒤 수집함에 저장한다."""
        rec = sanitize_and_filter_record(raw_record)

        brand = rec.get("brand") or self.brand
        work_slug = str(rec.get("target_work_slug") or "general").strip()
        url = str(rec.get("url") or "").strip()
        canon_url = canonicalize_url(url)
        domain = ""
        if canon_url:
            try:
                domain = canon_url.split("//", 1)[-1].split("/", 1)[0]
            except Exception:
                domain = ""

        status = rec.get("validation_status") or "discovered"
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid validation_status: {status}")

        access_level = rec.get("source_access_level") or "press_article"
        if access_level not in SOURCE_ACCESS_LEVELS:
            raise ValueError(f"Invalid source_access_level: {access_level}")

        unv_cat = str(rec.get("unverified_category") or "").strip()
        if unv_cat and unv_cat not in UNVERIFIED_CATEGORIES:
            raise ValueError(f"Invalid unverified_category: {unv_cat}")

        facts = rec.get("extracted_facts") or []
        fact_text_joined = " ".join(
            (f.get("claim", "") if isinstance(f, dict) else str(f)) for f in facts
        )
        edition = rec.get("edition") or {}
        title = str(rec.get("title") or "").strip()

        cluster_id = rec.get("dedup_cluster_id") or compute_dedup_cluster_id(
            work_slug=work_slug,
            url=url,
            title=title,
            fact_text=fact_text_joined,
            edition=edition,
        )

        item_id = rec.get("id")
        if not item_id:
            raw_id_seed = f"{brand}|{work_slug}|{url}|{title}|{fact_text_joined[:160]}|{rec.get('collection_path', 'auto')}"
            item_id = "gl_" + hashlib.sha1(raw_id_seed.encode("utf-8")).hexdigest()[:16]

        conflict = 1 if rec.get("conflict") else 0
        conflict_note = str(rec.get("conflict_note") or "").strip()
        conflict_with_id = str(rec.get("conflict_with_id") or "").strip()

        # 미해결 충돌 항목은 자동으로 publish_pending 상태가 될 수 없음 (사람 에디터 확인 필수)
        if conflict and status == "publish_pending" and not rec.get("conflict_resolved"):
            status = "source_checked"

        bundle_type = str(rec.get("bundle_type") or "research_bundle")
        if bundle_type not in ("research_bundle", "critique_ready_bundle"):
            bundle_type = "research_bundle"

        is_primary = int(rec.get("is_cluster_primary", 1))

        with self._connect() as conn:
            if auto_dedup and status != "discovered" and not conflict:
                existing = conn.execute(
                    "SELECT id, extracted_facts_json, conflict FROM items WHERE brand = ? AND dedup_cluster_id = ? AND id != ? AND is_cluster_primary = 1",
                    (brand, cluster_id, item_id),
                ).fetchall()
                if existing:
                    # 이미 동일 클러스터 대표 원문이 존재하고 충돌이 아니면 중복 제외(deduped)로 분류하되 사실 데이터는 보존
                    is_primary = 0
                    if status not in ("publish_pending",):
                        status = "deduped"

            conn.execute(
                """
                INSERT INTO items (
                    id, brand, collection_path, url, canonical_url, domain, title, outlet,
                    published_at, collected_at, target_work_slug, validation_status, bundle_type,
                    source_access_level, unverified_category, work_info_json, edition_info_json,
                    author_statement, critical_thesis, counter_argument, extracted_facts_json,
                    evidence_locator, dedup_cluster_id, is_cluster_primary, conflict, conflict_note,
                    conflict_with_id, pii_filtered, pii_redactions_count, prompt_injection_detected,
                    fulltext_allowed, notes
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                    validation_status = excluded.validation_status,
                    bundle_type = excluded.bundle_type,
                    source_access_level = excluded.source_access_level,
                    unverified_category = excluded.unverified_category,
                    work_info_json = excluded.work_info_json,
                    edition_info_json = excluded.edition_info_json,
                    author_statement = excluded.author_statement,
                    critical_thesis = excluded.critical_thesis,
                    counter_argument = excluded.counter_argument,
                    extracted_facts_json = excluded.extracted_facts_json,
                    evidence_locator = excluded.evidence_locator,
                    dedup_cluster_id = excluded.dedup_cluster_id,
                    is_cluster_primary = excluded.is_cluster_primary,
                    conflict = excluded.conflict,
                    conflict_note = excluded.conflict_note,
                    conflict_with_id = excluded.conflict_with_id,
                    pii_filtered = excluded.pii_filtered,
                    pii_redactions_count = excluded.pii_redactions_count,
                    prompt_injection_detected = excluded.prompt_injection_detected
                """,
                (
                    item_id,
                    brand,
                    str(rec.get("collection_path") or "auto"),
                    url,
                    canon_url,
                    domain,
                    title,
                    str(rec.get("outlet") or ""),
                    str(rec.get("published_at") or ""),
                    str(rec.get("collected_at") or now_kst_iso()),
                    work_slug,
                    status,
                    bundle_type,
                    access_level,
                    unv_cat,
                    json.dumps(rec.get("work") or {}, ensure_ascii=False),
                    json.dumps(edition, ensure_ascii=False),
                    str(rec.get("author_statement") or ""),
                    str(rec.get("critical_thesis") or ""),
                    str(rec.get("counter_argument") or ""),
                    json.dumps(facts, ensure_ascii=False),
                    str(rec.get("evidence_locator") or ""),
                    cluster_id,
                    is_primary,
                    conflict,
                    conflict_note,
                    conflict_with_id,
                    int(rec.get("pii_filtered", 1)),
                    int(rec.get("pii_redactions_count", 0)),
                    int(rec.get("prompt_injection_detected", 0)),
                    int(rec.get("fulltext_allowed", 0)),
                    str(rec.get("notes") or ""),
                ),
            )

        rec["id"] = item_id
        rec["validation_status"] = status
        rec["dedup_cluster_id"] = cluster_id
        rec["is_cluster_primary"] = is_primary
        return rec

    def register_conflict_pair(
        self, rec_a: Dict[str, Any], rec_b: Dict[str, Any], conflict_note: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """서로 다른 출처의 주장이 충돌할 때 두 레코드를 모두 보존하고 양쪽에 충돌 표시 및 상대 ID를 연결한다."""
        clean_note, _, _ = filter_pii_text(conflict_note)
        rec_a = dict(rec_a, conflict=1, conflict_note=clean_note)
        rec_b = dict(rec_b, conflict=1, conflict_note=clean_note)
        saved_a = self.upsert_item(rec_a, auto_dedup=False)
        rec_b["conflict_with_id"] = saved_a["id"]
        saved_b = self.upsert_item(rec_b, auto_dedup=False)
        saved_a["conflict_with_id"] = saved_b["id"]
        self.upsert_item(saved_a, auto_dedup=False)
        return saved_a, saved_b

    def enqueue_url(
        self,
        url: str,
        target_work_slug: str = "",
        collection_path: str = "auto",
        link_depth: int = 0,
        priority: int = 50,
        cursor_pos: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """큐와 진행 위치(cursor_pos)를 SQLite에 영속 저장하여 서비스워커나 데몬 재시작 시 중단 지점부터 재개한다."""
        clean_url, _, _ = filter_pii_text(url)
        canon = canonicalize_url(clean_url)
        qid = "q_" + hashlib.sha1(f"{self.brand}|{collection_path}|{canon or clean_url}".encode("utf-8")).hexdigest()[:16]
        safe_payload = sanitize_and_filter_record(payload or {}) if payload else {}
        now = now_kst_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO crawl_queue (
                    queue_id, brand, url, canonical_url, target_work_slug, collection_path,
                    link_depth, priority, state, cursor_pos, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                ON CONFLICT(queue_id) DO UPDATE SET
                    priority = MAX(crawl_queue.priority, excluded.priority),
                    cursor_pos = CASE WHEN excluded.cursor_pos != '' THEN excluded.cursor_pos ELSE crawl_queue.cursor_pos END,
                    updated_at = excluded.updated_at
                """,
                (
                    qid,
                    self.brand,
                    clean_url,
                    canon,
                    target_work_slug,
                    collection_path,
                    int(link_depth),
                    int(priority),
                    cursor_pos,
                    json.dumps(safe_payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return qid

    def get_status_summary(self) -> Dict[str, Any]:
        """첫 버전 완료 기준: 후보(discovered), 원문 확인(source_checked), 중복 제외(deduped), 검증 완료(verified_ready), 공개 대기(publish_pending) 수를 집계."""
        with self._connect() as conn:
            status_rows = conn.execute(
                "SELECT validation_status, COUNT(*) AS cnt FROM items WHERE brand = ? GROUP BY validation_status",
                (self.brand,),
            ).fetchall()
            counts = {s: 0 for s in VALID_STATUSES}
            for r in status_rows:
                counts[r["validation_status"]] = int(r["cnt"])

            bundle_rows = conn.execute(
                "SELECT bundle_type, COUNT(*) AS cnt FROM items WHERE brand = ? AND validation_status IN ('verified_ready', 'publish_pending') GROUP BY bundle_type",
                (self.brand,),
            ).fetchall()
            bundles = {"research_bundle": 0, "critique_ready_bundle": 0}
            for r in bundle_rows:
                bundles[r["bundle_type"]] = int(r["cnt"])

            access_rows = conn.execute(
                "SELECT source_access_level, COUNT(*) AS cnt FROM items WHERE brand = ? GROUP BY source_access_level",
                (self.brand,),
            ).fetchall()
            access_counts = {k: 0 for k in SOURCE_ACCESS_LEVELS}
            for r in access_rows:
                access_counts[r["source_access_level"]] = int(r["cnt"])

            unv_rows = conn.execute(
                "SELECT unverified_category, COUNT(*) AS cnt FROM items WHERE brand = ? AND unverified_category != '' GROUP BY unverified_category",
                (self.brand,),
            ).fetchall()
            unv_counts = {k: 0 for k in UNVERIFIED_CATEGORIES}
            for r in unv_rows:
                unv_counts[r["unverified_category"]] = int(r["cnt"])

            path_rows = conn.execute(
                "SELECT collection_path, COUNT(*) AS cnt FROM items WHERE brand = ? GROUP BY collection_path",
                (self.brand,),
            ).fetchall()
            path_counts = {r["collection_path"]: int(r["cnt"]) for r in path_rows}

            conflict_cnt = conn.execute(
                "SELECT COUNT(*) AS cnt FROM items WHERE brand = ? AND conflict = 1",
                (self.brand,),
            ).fetchone()["cnt"]

            clusters_cnt = conn.execute(
                "SELECT COUNT(DISTINCT dedup_cluster_id) AS cnt FROM items WHERE brand = ?",
                (self.brand,),
            ).fetchone()["cnt"]

            queue_rows = conn.execute(
                "SELECT state, COUNT(*) AS cnt FROM crawl_queue WHERE brand = ? GROUP BY state",
                (self.brand,),
            ).fetchall()
            queue_counts = {r["state"]: int(r["cnt"]) for r in queue_rows}

            total_items = sum(counts.values())

        summary = {
            "brand": self.brand,
            "generated_at_kst": now_kst_iso(),
            "auto_publish_connected": AUTO_PUBLISH_TO_SITE,
            "total_records": total_items,
            "unique_clusters": int(clusters_cnt),
            "stage_counts": {
                "discovered": counts["discovered"],
                "source_checked": counts["source_checked"],
                "deduped": counts["deduped"],
                "verified_ready": counts["verified_ready"],
                "publish_pending": counts["publish_pending"],
            },
            "verified_bundle_breakdown": bundles,
            "source_access_level_breakdown": access_counts,
            "unverified_3category_breakdown": unv_counts,
            "collection_path_breakdown": path_counts,
            "conflict_records_count": int(conflict_cnt),
            "queue_state_counts": queue_counts,
        }
        STATUS_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return summary
