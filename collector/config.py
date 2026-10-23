#!/usr/bin/env python3
"""Goal Lit (꼴릿) 수집기 초기 설정 및 상수 정의."""
from pathlib import Path

BRAND = "goal-lit"
BRAND_DISPLAY = "꼴릿 (Goal Lit)"

BASE_DIR = Path("/workspace/lit-hub/collector").resolve()
LIT_HUB_DIR = Path("/workspace/lit-hub").resolve()
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

DB_PATH = DATA_DIR / "goallit_inbox.db"
STATUS_SUMMARY_PATH = DATA_DIR / "status_summary.json"
WORKS_JSON_PATH = LIT_HUB_DIR / "site/content/works.json"
POSTS_JSON_PATH = LIT_HUB_DIR / "site/content/posts.json"
ROBOTS_SUMMARY_PATH = LIT_HUB_DIR / "research/robots/_summary.json"
BARE_CITATIONS_PATH = LIT_HUB_DIR / "research/robots/bare_citations.json"

# --- 준태님 확정 초기 폭주 방지 설정값 (2026-10-23 10:14) ---
MAX_DAILY_DISCOVERED = 500          # 브랜드당 하루 신규 후보 URL 발견 상한: 500개
MAX_DAILY_FETCHED = 200             # 브랜드당 하루 새 본문 수집 상한: 200개
MAX_CONCURRENT_PER_DOMAIN = 1       # 같은 도메인 동시 요청: 1개
MIN_DOMAIN_INTERVAL_SEC = 5.0       # 요청 간격: 기본 최소 5초 (사이트 제한이 더 느리면 그 기준 적용)
MAX_LINK_DEPTH = 2                  # 페이지에서 새 링크를 따라가는 깊이: 최대 2단계

# 정직한 User-Agent (차단 회피용 UA 위장·프록시·계정 회전 일절 금지)
USER_AGENT = "GoalLitCollector/1.0 (+https://goallit.soulbound.co.kr; respectful-archiver)"

# 로컬 작업기 수신 서버 설정 (Chrome 확장프로그램 수동 보충 & 상태 조회용)
LOCAL_WORKER_HOST = "127.0.0.1"
LOCAL_WORKER_PORT = 8795

# 자동 게시 연결 차단 플래그 (수집은 자동으로 돌리되 사이트 라이브 게시는 수동 승인 전까지 절대 자동 실행하지 않음)
AUTO_PUBLISH_TO_SITE = False

# 5단계 검증·공개 상태
VALID_STATUSES = (
    "discovered",        # 1. 발견 후보 (비공식 출처 단서, 미확인 항목 포함)
    "source_checked",    # 2. 원문 확인 (원문 대조 및 근거 위치 확보)
    "deduped",           # 3. 중복 제외 (동일 URL/보도자료/번역본/판본 클러스터의 비대표 항목)
    "verified_ready",    # 4. 검증 완료 (조사자료 묶음 research_bundle vs 독창 평론 준비 묶음 critique_ready_bundle)
    "publish_pending",   # 5. 공개 대기 (사이트 반영 후보, 에디터 승인 대기)
)

# 꼴릿 전용 원문 접근 수준 5종
SOURCE_ACCESS_LEVELS = (
    "book_intro",        # 작품 소개 / 공식 서지 / 도서관 서지 / 플랫폼 표지
    "paper_abstract",    # 학술 논문 초록 / 학술 서평 첫머리 (KCI, OpenAlex, Crossref, DOI)
    "full_text_read",    # 실제 작품 원문 독서 기록 / 직접 텍스트 강독 인용
    "press_article",     # 언론 기사 / 문예지 보도
    "author_interview",  # 작가 직접 인터뷰 / 수상 소감 / 작가의 말
)

# 미확인(unverified) 항목 3분류
UNVERIFIED_CATEGORIES = (
    "서지",
    "발언",
    "작품 해석",
)

# 브라우저 수집(JS 렌더링/공개 표지 추출)이 허용된 승인 도메인 목록 (robots.txt 허용 경로에 한함)
APPROVED_JS_DOMAINS = (
    "thebookerprizes.com",
    "magazine.changbi.com",
    "page.kakao.com",
    "novel.munpia.com",
    "series.naver.com",
    "comic.naver.com",
    "journal.kci.go.kr",
    "openalex.org",
    "nl.go.kr",
)

# 크롤 트랩(달력·검색 조합·무한 페이지네이션·로그인/결제/뷰어) 차단 정규식
TRAP_URL_PATTERNS = (
    r"/calendar/",
    r"[?&]year=\d{4}.*[?&]month=\d{1,2}",
    r"[?&]page=([2-9]\d|\d{3,})",
    r"[?&]offset=([1-9]\d{2,})",
    r"[?&]sort=.*&filter=.*&q=",
    r"/(login|signin|signup|logout|member|mypage|cart|checkout|pay|order)(/|$|\?)",
    r"/webtoon/detail",
    r"/viewer/",
    r"booking\.naver\.com",
    r"blog\.naver\.com",
    r"rss\.blog\.naver\.com",
    r"map\.naver\.com",
)
