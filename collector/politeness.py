#!/usr/bin/env python3
"""도메인별 레이트리밋, 동시성 제어, robots.txt 준수 및 일일 수집 상한(500/200) 관리 모듈.

폭주 방지 규칙:
- 브랜드당 하루 신규 후보 URL 발견 상한: 500개 (MAX_DAILY_DISCOVERED = 500)
- 브랜드당 하루 새 본문 수집 상한: 200개 (MAX_DAILY_FETCHED = 200)
- 같은 도메인 동시 요청: 1개 (MAX_CONCURRENT_PER_DOMAIN = 1, 파일 락 기반 프로세스 간 강제)
- 요청 간격: 기본 최소 5초 (MIN_DOMAIN_INTERVAL_SEC = 5.0), robots.txt Crawl-delay가 더 길면 그 기준 적용
- 링크 추적 깊이: 최대 2단계 (MAX_LINK_DEPTH = 2)
- 달력·검색 조합·무한 페이지네이션 URL 패턴 차단
- 429/503/403 응답 시 해당 도메인 감속·중단 (차단 회피용 프록시·계정 회전·UA 위장 일절 없음)
"""
import datetime as dt
import fcntl
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

from config import (
    BRAND,
    DATA_DIR,
    DB_PATH,
    MAX_CONCURRENT_PER_DOMAIN,
    MAX_DAILY_DISCOVERED,
    MAX_DAILY_FETCHED,
    MAX_LINK_DEPTH,
    MIN_DOMAIN_INTERVAL_SEC,
    ROBOTS_SUMMARY_PATH,
    TRAP_URL_PATTERNS,
    USER_AGENT,
)

KST = dt.timezone(dt.timedelta(hours=9))
LOCKS_DIR = DATA_DIR / "domain_locks"
LOCKS_DIR.mkdir(parents=True, exist_ok=True)

TRAP_REGEXES = [re.compile(pat, re.I) for pat in TRAP_URL_PATTERNS]

# 정책상 수집 제외 도메인 (네이버 블로그/예약/지도, SNS, AI 명시 차단 언론사 본문 크롤링)
POLICY_BLOCKED_HOSTS = (
    "booking.naver.com",
    "blog.naver.com",
    "rss.blog.naver.com",
    "map.naver.com",
    "pcmap.place.naver.com",
    "instagram.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "dcinside.com",
    "dbpia.co.kr",
    "www.kci.go.kr",
)


def today_kst() -> str:
    return dt.datetime.now(KST).strftime("%Y-%m-%d")


def extract_domain(url: str) -> str:
    try:
        host = urllib.parse.urlsplit(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def is_trap_or_disallowed_url(url: str, depth: int = 0) -> Tuple[bool, str]:
    """링크 깊이 상한(2단계), 크롤 트랩 패턴, 정책 차단 도메인 여부를 검사한다."""
    if depth > MAX_LINK_DEPTH:
        return True, f"exceeds_max_link_depth({depth}>{MAX_LINK_DEPTH})"
    if not url or not str(url).startswith(("http://", "https://")):
        return True, "invalid_scheme"
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower()
    for bh in POLICY_BLOCKED_HOSTS:
        if host == bh or host.endswith("." + bh):
            return True, f"policy_blocked_host({bh})"
    # 네이버 웹툰/시리즈는 작품 표지(/webtoon/list, /novel/detail.series 등)만 허용하고 회차 뷰어는 차단
    if "comic.naver.com" in host and "/webtoon/list" not in parsed.path:
        return True, "naver_comic_non_cover_disallowed"
    for rx in TRAP_REGEXES:
        if rx.search(url):
            return True, f"trap_pattern({rx.pattern})"
    # robots 감사 요약(_summary.json)에서 BLOCKS-AI로 분류된 도메인은 자동 본문 수집 차단
    if ROBOTS_SUMMARY_PATH.exists():
        try:
            summary = json.loads(ROBOTS_SUMMARY_PATH.read_text(encoding="utf-8"))
            st = (summary.get(host) or summary.get("www." + host) or {}).get("status")
            if st in ("BLOCKS-AI", "BLOCKS-ALL"):
                return True, f"robots_audit_{st}"
        except Exception:
            pass
    return False, "ok"


class PolitenessManager:
    """SQLite + 파일 락 기반 일일 예산(500/200) 및 도메인 간격(>=5초)·동시성(1) 제어기."""

    def __init__(self, db_path: Path = DB_PATH, brand: str = BRAND):
        self.db_path = Path(db_path)
        self.brand = brand
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_counters (
                    date_kst TEXT NOT NULL,
                    brand TEXT NOT NULL,
                    discovered_count INTEGER NOT NULL DEFAULT 0,
                    fetched_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (date_kst, brand)
                );
                CREATE TABLE IF NOT EXISTS domain_politeness (
                    domain TEXT PRIMARY KEY,
                    last_request_ts REAL NOT NULL DEFAULT 0,
                    crawl_delay_sec REAL NOT NULL DEFAULT 5.0,
                    backoff_until_ts REAL NOT NULL DEFAULT 0,
                    last_status_code INTEGER NOT NULL DEFAULT 0,
                    consecutive_errors INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def get_daily_counts(self, date_str: Optional[str] = None) -> Dict[str, int]:
        d = date_str or today_kst()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT discovered_count, fetched_count FROM daily_counters WHERE date_kst = ? AND brand = ?",
                (d, self.brand),
            ).fetchone()
            if not row:
                return {"discovered_count": 0, "fetched_count": 0}
            return {"discovered_count": int(row["discovered_count"]), "fetched_count": int(row["fetched_count"])}

    def try_consume_discovery_budget(self, count: int = 1, date_str: Optional[str] = None) -> Tuple[bool, int]:
        """하루 신규 후보 URL 발견 상한(500개) 내에서 예산을 차감한다."""
        d = date_str or today_kst()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO daily_counters (date_kst, brand, discovered_count, fetched_count) VALUES (?, ?, 0, 0)",
                (d, self.brand),
            )
            row = conn.execute(
                "SELECT discovered_count FROM daily_counters WHERE date_kst = ? AND brand = ?",
                (d, self.brand),
            ).fetchone()
            cur = int(row["discovered_count"]) if row else 0
            if cur + count > MAX_DAILY_DISCOVERED:
                return False, cur
            conn.execute(
                "UPDATE daily_counters SET discovered_count = discovered_count + ? WHERE date_kst = ? AND brand = ?",
                (count, d, self.brand),
            )
            return True, cur + count

    def try_consume_fetch_budget(self, count: int = 1, date_str: Optional[str] = None) -> Tuple[bool, int]:
        """하루 새 본문 수집 상한(200개) 내에서 예산을 차감한다."""
        d = date_str or today_kst()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO daily_counters (date_kst, brand, discovered_count, fetched_count) VALUES (?, ?, 0, 0)",
                (d, self.brand),
            )
            row = conn.execute(
                "SELECT fetched_count FROM daily_counters WHERE date_kst = ? AND brand = ?",
                (d, self.brand),
            ).fetchone()
            cur = int(row["fetched_count"]) if row else 0
            if cur + count > MAX_DAILY_FETCHED:
                return False, cur
            conn.execute(
                "UPDATE daily_counters SET fetched_count = fetched_count + ? WHERE date_kst = ? AND brand = ?",
                (count, d, self.brand),
            )
            return True, cur + count

    @contextmanager
    def domain_slot(self, url: str, simulated_sleep: bool = False):
        """동일 도메인 동시 요청 1개(파일 락) 및 최소 요청 간격(max(5.0초, crawl_delay))을 보장한다."""
        domain = extract_domain(url) or "unknown"
        safe_dom = re.sub(r"[^a-zA-Z0-9._-]", "_", domain)
        lock_file = LOCKS_DIR / f"{safe_dom}.lock"
        fp = open(lock_file, "a+", encoding="utf-8")
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
            now = time.time()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT last_request_ts, crawl_delay_sec, backoff_until_ts FROM domain_politeness WHERE domain = ?",
                    (domain,),
                ).fetchone()
                if row and float(row["backoff_until_ts"]) > now:
                    raise RuntimeError(f"domain_in_backoff({domain} until {row['backoff_until_ts']:.0f})")
                last_ts = float(row["last_request_ts"]) if row else 0.0
                crawl_delay = max(MIN_DOMAIN_INTERVAL_SEC, float(row["crawl_delay_sec"]) if row else MIN_DOMAIN_INTERVAL_SEC)
                wait_sec = (last_ts + crawl_delay) - now
                if wait_sec > 0 and not simulated_sleep:
                    time.sleep(wait_sec)
                new_ts = time.time() if not simulated_sleep else max(now, last_ts + crawl_delay)
                conn.execute(
                    """
                    INSERT INTO domain_politeness (domain, last_request_ts, crawl_delay_sec, backoff_until_ts, last_status_code, consecutive_errors)
                    VALUES (?, ?, ?, 0, 200, 0)
                    ON CONFLICT(domain) DO UPDATE SET last_request_ts = excluded.last_request_ts
                    """,
                    (domain, new_ts, crawl_delay),
                )
            yield domain, crawl_delay
        finally:
            try:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            finally:
                fp.close()

    def record_response_status(self, url: str, status_code: int, robots_crawl_delay: float = 0.0) -> None:
        """응답 코드가 429/503/403이면 즉시 백오프(감속·중단)를 설정한다."""
        domain = extract_domain(url) or "unknown"
        delay = max(MIN_DOMAIN_INTERVAL_SEC, float(robots_crawl_delay or 0.0))
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT consecutive_errors FROM domain_politeness WHERE domain = ?",
                (domain,),
            ).fetchone()
            errs = int(row["consecutive_errors"]) if row else 0
            if status_code in (429, 503, 403, 401):
                errs += 1
                # 지수 백오프 (최소 300초 ~ 최대 3600초 중단)
                backoff_until = now + min(3600.0, 300.0 * (2 ** (errs - 1)))
            else:
                errs = 0
                backoff_until = 0.0
            conn.execute(
                """
                INSERT INTO domain_politeness (domain, last_request_ts, crawl_delay_sec, backoff_until_ts, last_status_code, consecutive_errors)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    crawl_delay_sec = MAX(domain_politeness.crawl_delay_sec, excluded.crawl_delay_sec),
                    backoff_until_ts = excluded.backoff_until_ts,
                    last_status_code = excluded.last_status_code,
                    consecutive_errors = excluded.consecutive_errors
                """,
                (domain, now, delay, backoff_until, status_code, errs),
            )
