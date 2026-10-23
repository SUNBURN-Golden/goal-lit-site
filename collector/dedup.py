#!/usr/bin/env python3
"""다계층 중복 판정 및 클러스터링 모듈 (dedup.py).

중복 판정 기준:
1. 정규화 URL 일치 (canonical_url: utm_*, fbclid 등 추적 파라미터 제거, 스킴/말미 슬래시 통일)
2. 고유 학술/서지 식별자 일치 (DOI, OpenAlex ID, KCI artiId, ISBN)
3. 동일 보도자료·기사 재전송·번역본·판본 옵션 클러스터링 (동일 작품 내 사실 텍스트/핵심 수치 토큰 유사도 >= 0.65 또는 동일 보도자료 시그니처)
"""
import hashlib
import re
import urllib.parse
from typing import Dict, Any, Set


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "source",
}


def canonicalize_url(url: str) -> str:
    """URL에서 추적 파라미터와 불필요한 프래그먼트를 제거하고 표준 형식으로 정규화한다."""
    if not url or not str(url).strip():
        return ""
    u = str(url).strip()
    try:
        parsed = urllib.parse.urlsplit(u)
    except Exception:
        return u
    scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = re.sub(r"/+", "/", parsed.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_q = sorted((k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS)
    query_str = urllib.parse.urlencode(filtered_q)
    return urllib.parse.urlunsplit((scheme, netloc, path, query_str, ""))


def extract_identifier_key(url: str, edition: Dict[str, Any] = None, text: str = "") -> str:
    """DOI, OpenAlex ID, KCI artiId, ISBN 등 표준 식별자가 있으면 추출한다."""
    u = (url or "").strip()
    m_doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", u) or re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text or "")
    if m_doi:
        return f"doi:{m_doi.group(0).lower().rstrip('.')}"
    m_oa = re.search(r"openalex\.org/(W\d+)", u, re.I)
    if m_oa:
        return f"openalex:{m_oa.group(1).upper()}"
    m_kci = re.search(r"artiId=(ART\d+)", u, re.I)
    if m_kci:
        return f"kci:{m_kci.group(1).upper()}"
    isbn = (edition or {}).get("isbn") or ""
    if not isbn:
        m_isbn = re.search(r"\b(97[89][- ]?\d{1,5}[- ]?\d{1,7}[- ]?\d{1,6}[- ]?\d)\b", (u + " " + (text or "")))
        if m_isbn:
            isbn = re.sub(r"[- ]", "", m_isbn.group(1))
    if isbn:
        return f"isbn:{re.sub(r'[^0-9X]', '', str(isbn))}"
    return ""


def normalize_edition_signature(work_slug: str, edition: Dict[str, Any] = None, text: str = "") -> str:
    """동일 작품의 단순 판본/옵션 차이(양장본, 무선본, 전자책, 색상/표지 에디션 등)나 동일 보도자료 주제를 하나의 서지 시그니처로 묶는다."""
    t = (text or "").lower()
    # 보도자료/공통 주제 시그니처 감지 (예: 인터내셔널 부커상 최종 후보 6편 / 롱리스트 / 누적 판매 부수 보도자료)
    if "인터내셔널 부커상" in t and ("최종 후보" in t or "쇼트리스트" in t or "롱리스트" in t):
        year_m = re.search(r"(20\d{2})년", t)
        yr = year_m.group(1) if year_m else "any"
        return f"press_wire:{work_slug}:booker_{yr}"
    if edition and isinstance(edition, dict):
        pub = re.sub(r"\s+", "", str(edition.get("publisher") or "")).lower()
        model_or_ver = re.sub(r"(양장본|무선본|보급판|특별판|리커버|전자책|e북|hardcover|paperback)", "", str(edition.get("edition_type") or "")).strip()
        if pub and work_slug:
            return f"edition:{work_slug}:{pub}:{model_or_ver}"
    return ""


def token_set(text: str) -> Set[str]:
    """한국어/영어 핵심 어절 및 2-gram 집합을 생성한다."""
    if not text:
        return set()
    cleaned = re.sub(r"[^가-힣a-zA-Z0-9\s]", " ", text.lower())
    words = [w for w in cleaned.split() if len(w) >= 2]
    grams = set(words)
    joined = "".join(words)
    for i in range(0, max(0, len(joined) - 2)):
        grams.add(joined[i : i + 3])
    return grams


def text_similarity(a: str, b: str) -> float:
    """두 텍스트 간 Jaccard 유사도(0.0 ~ 1.0)를 계산한다."""
    sa, sb = token_set(a), token_set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def compute_dedup_cluster_id(
    work_slug: str,
    url: str,
    title: str = "",
    fact_text: str = "",
    edition: Dict[str, Any] = None,
) -> str:
    """URL 정규화, 표준 식별자(DOI/ISBN/OpenAlex), 보도자료/판본 시그니처를 결합해 결정론적 클러스터 ID를 반환한다."""
    ident = extract_identifier_key(url, edition=edition, text=fact_text)
    if ident:
        raw = f"{work_slug or 'global'}|{ident}"
        return "cluster_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    ed_sig = normalize_edition_signature(work_slug or "global", edition=edition, text=fact_text)
    if ed_sig:
        return "cluster_" + hashlib.sha1(ed_sig.encode("utf-8")).hexdigest()[:12]

    canon = canonicalize_url(url)
    if canon:
        raw = f"url|{canon}"
        return "cluster_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    norm_text = re.sub(r"\s+", " ", (fact_text or title or "").strip().lower())[:120]
    raw = f"text|{work_slug or 'global'}|{norm_text}"
    return "cluster_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
