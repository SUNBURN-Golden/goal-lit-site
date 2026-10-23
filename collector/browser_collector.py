#!/usr/bin/env python3
"""경로 2: 브라우저 수집기 (browser_collector.py).

자바스크립트로 표시되는 공개 페이지는 승인된 사이트 목록(APPROVED_JS_DOMAINS) 및
robots.txt 허용 경로에 한해서만 확인하여 필요한 영역만 추출한다.
"""
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from config import APPROVED_JS_DOMAINS, USER_AGENT
from pii_filter import extract_main_region, filter_pii_text
from politeness import PolitenessManager, extract_domain, is_trap_or_disallowed_url
from storage import CollectorStorage, now_kst_iso


def is_approved_js_domain(url: str) -> bool:
    dom = extract_domain(url)
    return any(dom == d or dom.endswith("." + d) for d in APPROVED_JS_DOMAINS)


class BrowserCollector:
    def __init__(self, storage: Optional[CollectorStorage] = None, politeness: Optional[PolitenessManager] = None):
        self.storage = storage or CollectorStorage()
        self.politeness = politeness or PolitenessManager(self.storage.db_path)

    def extract_from_rendered_dom(
        self,
        url: str,
        target_work_slug: str,
        rendered_html: str,
        outlet: str = "",
        edition_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """승인된 도메인의 렌더링된 DOM에서 필요한 서지·소개 영역만 추출하고 저장 전 PII 필터를 적용한다."""
        if not is_approved_js_domain(url):
            raise PermissionError(f"Domain not in APPROVED_JS_DOMAINS: {extract_domain(url)}")
        disallowed, reason = is_trap_or_disallowed_url(url, depth=0)
        if disallowed:
            raise PermissionError(f"URL disallowed by policy/robots: {reason}")

        ok_budget, _ = self.politeness.try_consume_fetch_budget(1)
        if not ok_budget:
            return None

        title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", rendered_html or "")
        raw_title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else url
        main_region = extract_main_region(rendered_html or "")
        clean_text, _, _ = filter_pii_text(main_region)

        rec = {
            "collection_path": "browser",
            "url": url,
            "title": raw_title[:200],
            "outlet": outlet or extract_domain(url),
            "collected_at": now_kst_iso(),
            "target_work_slug": target_work_slug,
            "validation_status": "source_checked",
            "bundle_type": "research_bundle",
            "source_access_level": "book_intro",
            "edition": edition_meta or {},
            "extracted_facts": [
                {
                    "label": "공개 표지·서지 영역 추출",
                    "claim": clean_text[:300],
                }
            ],
            "evidence_locator": "approved_js_dom_main_region",
        }
        return self.storage.upsert_item(rec, auto_dedup=True)
