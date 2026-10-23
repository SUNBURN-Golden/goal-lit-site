#!/usr/bin/env python3
"""경로 1: 자동 수집기 (auto_collector.py).

RSS·공개 API(OpenAlex, Crossref, 국립중앙도서관 서지, KCI 공개 초록, The Booker Prizes 아카이브 등)·
사이트맵·목록·본문 내 관련 링크(최대 깊이 max_depth=2)에서 새 자료를 발견하고 검증한다.
신간·수상·절판 등 변동성이 높은 항목(priority >= 80)을 신규 탐색(priority = 50)보다 우선 재확인한다.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from config import MAX_LINK_DEPTH, USER_AGENT
from dedup import canonicalize_url
from pii_filter import extract_main_region, filter_pii_text
from politeness import PolitenessManager, extract_domain, is_trap_or_disallowed_url
from storage import CollectorStorage, now_kst_iso


class LinkExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: List[str] = []
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        if tag.lower() == "title":
            self._in_title = True
        elif tag.lower() == "a":
            for k, v in attrs:
                if k.lower() == "href" and v:
                    full = urllib.parse.urljoin(self.base_url, v.strip())
                    if full.startswith(("http://", "https://")):
                        self.links.append(full)

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str):
        if self._in_title:
            self.title += data


def classify_source_access_level(url: str, outlet: str = "", text: str = "") -> str:
    """URL, 매체명, 본문 특징에 따라 5대 원문 접근 수준을 엄격히 분류한다."""
    u = (url or "").lower()
    o = (outlet or "").lower()
    t = (text or "").lower()
    if any(k in u for k in ("doi.org/", "openalex.org/", "journal.kci.go.kr", "api.crossref.org")) or "논문 초록" in o or "서평 첫머리" in o:
        return "paper_abstract"
    if any(k in u for k in ("minumsa.com/book", "nl.go.kr", "thebookerprizes.com/the-booker-library/books", "novel.munpia.com", "page.kakao.com/content", "series.naver.com", "comic.naver.com/webtoon/list")):
        return "book_intro"
    if "인터뷰" in o or "인터뷰" in t or "간담회" in t or "수상 소감" in t:
        return "author_interview"
    return "press_article"


class AutoCollector:
    def __init__(self, storage: Optional[CollectorStorage] = None, politeness: Optional[PolitenessManager] = None):
        self.storage = storage or CollectorStorage()
        self.politeness = politeness or PolitenessManager(self.storage.db_path)

    def discover_candidate(
        self,
        url: str,
        target_work_slug: str,
        title: str = "",
        outlet: str = "",
        claim_hint: str = "",
        link_depth: int = 0,
        priority: int = 50,
        source_access_level: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """비공식 출처(블로그·검색 단서·행사 공지)를 포함한 신규 링크를 '발견 후보(discovered)' 상태로 수용하고 큐에 등록한다."""
        disallowed, reason = is_trap_or_disallowed_url(url, depth=link_depth)
        if disallowed:
            return None
        ok_budget, _ = self.politeness.try_consume_discovery_budget(1)
        if not ok_budget:
            return None

        access = source_access_level or classify_source_access_level(url, outlet, claim_hint)
        record = {
            "collection_path": "auto",
            "url": url,
            "title": title or url,
            "outlet": outlet or extract_domain(url),
            "collected_at": now_kst_iso(),
            "target_work_slug": target_work_slug,
            "validation_status": "discovered",
            "bundle_type": "research_bundle",
            "source_access_level": access,
            "extracted_facts": [{"label": "발견 단서", "claim": claim_hint}] if claim_hint else [],
            "evidence_locator": "candidate_discovery",
        }
        saved = self.storage.upsert_item(record, auto_dedup=False)
        self.storage.enqueue_url(
            url=url,
            target_work_slug=target_work_slug,
            collection_path="auto",
            link_depth=link_depth,
            priority=priority,
        )
        return saved

    def fetch_openalex_work(self, openalex_url_or_id: str, target_work_slug: str) -> Optional[Dict[str, Any]]:
        """OpenAlex 공개 API를 통해 학술 논문 초록·서지 메타데이터를 원문 확인(source_checked) 수준으로 수집한다."""
        m = re.search(r"(W\d+)", openalex_url_or_id)
        if not m:
            return None
        work_id = m.group(1)
        api_url = f"https://api.openalex.org/works/{work_id}"
        disallowed, _ = is_trap_or_disallowed_url(api_url, depth=0)
        if disallowed:
            return None
        ok_budget, _ = self.politeness.try_consume_fetch_budget(1)
        if not ok_budget:
            return None

        try:
            with self.politeness.domain_slot(api_url, simulated_sleep=True):
                req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    status = resp.status
                    data = json.loads(resp.read().decode("utf-8", "replace"))
            self.politeness.record_response_status(api_url, status)
        except urllib.error.HTTPError as e:
            self.politeness.record_response_status(api_url, e.code)
            return None
        except Exception:
            return None

        title = data.get("title") or data.get("display_name") or work_id
        pub_year = str(data.get("publication_year") or "")
        pub_date = str(data.get("publication_date") or pub_year)
        doi = data.get("doi") or f"https://openalex.org/{work_id}"
        venue = ((data.get("primary_location") or {}).get("source") or {}).get("display_name") or "OpenAlex 학술 메타데이터"
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (data.get("authorships") or [])[:5]
            if (a.get("author") or {}).get("display_name")
        ]

        # OpenAlex abstract_inverted_index 복원 (짧은 핵심 요지만 추출)
        inv = data.get("abstract_inverted_index") or {}
        abstract_snippet = ""
        if isinstance(inv, dict) and inv:
            pos_map = {}
            for word, positions in inv.items():
                for p in positions:
                    pos_map[p] = word
            words = [pos_map[k] for k in sorted(pos_map.keys())][:80]
            abstract_snippet = " ".join(words)

        clean_abs, _, _ = filter_pii_text(abstract_snippet)
        rec = {
            "collection_path": "auto",
            "url": f"https://openalex.org/{work_id}",
            "title": title,
            "outlet": f"{venue} ({pub_year}) 논문 초록",
            "published_at": pub_date,
            "collected_at": now_kst_iso(),
            "target_work_slug": target_work_slug,
            "validation_status": "source_checked",
            "bundle_type": "research_bundle",
            "source_access_level": "paper_abstract",
            "work": {"slug": target_work_slug, "paper_authors": authors},
            "edition": {"doi": doi, "publication_year": pub_year},
            "critical_thesis": clean_abs[:300] if clean_abs else f"{title} 학술 연구 메타데이터 확인",
            "extracted_facts": [
                {
                    "label": "학술 메타데이터 검증",
                    "claim": f"논문 제목: {title} / 학술지: {venue} ({pub_date}) / 저자: {', '.join(authors) if authors else '미기재'}",
                }
            ],
            "evidence_locator": f"OpenAlex API /works/{work_id} (DOI: {doi})",
        }
        return self.storage.upsert_item(rec, auto_dedup=True)

    def fetch_html_page(
        self,
        url: str,
        target_work_slug: str,
        link_depth: int = 0,
        follow_links: bool = True,
        simulated_sleep: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """허용된 공개 웹페이지를 정적 수집하여 필요한 본문 영역만 추출하고 하위 링크(depth<=2)를 발견 후보로 등록한다."""
        disallowed, _ = is_trap_or_disallowed_url(url, depth=link_depth)
        if disallowed:
            return None
        ok_budget, _ = self.politeness.try_consume_fetch_budget(1)
        if not ok_budget:
            return None

        try:
            with self.politeness.domain_slot(url, simulated_sleep=simulated_sleep):
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    status = resp.status
                    raw_html = resp.read(300_000).decode("utf-8", "replace")
            self.politeness.record_response_status(url, status)
        except urllib.error.HTTPError as e:
            self.politeness.record_response_status(url, e.code)
            return None
        except Exception:
            return None

        parser = LinkExtractor(url)
        try:
            parser.feed(raw_html)
        except Exception:
            pass

        main_text = extract_main_region(raw_html)
        clean_text, _, _ = filter_pii_text(main_text)
        title = (parser.title or url).strip()

        rec = {
            "collection_path": "auto",
            "url": url,
            "title": title[:200],
            "outlet": extract_domain(url),
            "collected_at": now_kst_iso(),
            "target_work_slug": target_work_slug,
            "validation_status": "source_checked",
            "bundle_type": "research_bundle",
            "source_access_level": classify_source_access_level(url, extract_domain(url), clean_text),
            "extracted_facts": [{"label": "본문 핵심 요지", "claim": clean_text[:280]}],
            "evidence_locator": "main_article_region[0:280]",
        }
        saved = self.storage.upsert_item(rec, auto_dedup=True)

        # 최대 깊이 2단계까지만 동일 도메인 또는 관련 링크를 발견 후보에 추가
        if follow_links and link_depth < MAX_LINK_DEPTH:
            base_dom = extract_domain(url)
            added = 0
            for child_url in parser.links:
                if added >= 5:
                    break
                if extract_domain(child_url) == base_dom and canonicalize_url(child_url) != canonicalize_url(url):
                    res = self.discover_candidate(
                        url=child_url,
                        target_work_slug=target_work_slug,
                        link_depth=link_depth + 1,
                        priority=40,
                    )
                    if res:
                        added += 1
        return saved
