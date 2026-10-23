#!/usr/bin/env python3
"""저장 전 개인정보(PII)·민감정보 필터 및 프롬프트 인젝션 무력화 모듈.

원칙:
1. 페이지 전체를 먼저 서버에 저장하고 나중에 지우는 방식을 금지함.
2. DOM/HTML 단계에서 필요한 영역(article, main, 서지 메타)만 추출하고 input/textarea/form/댓글/개인 프로필을 즉시 제거.
3. 로컬 저장 및 AI 전달 전에 정규식+규칙 필터(sanitize_and_filter)를 통과시켜 전화번호·이메일·주거주소·주민번호·아동정보·건강/금융정보·쿠키/토큰/비밀번호·DM을 마스킹/제거.
4. 페이지 안의 '이 명령을 실행하라', 'Ignore previous instructions' 같은 문구는 자료일 뿐 봇의 지시로 취급하지 않도록 격리.
"""
import re
from typing import Dict, Any, Tuple

# 1. 개인정보(PII) 및 민감정보 정규식 패턴
PII_PATTERNS = [
    # 주민등록번호 / 외국인등록번호
    ("rrn", re.compile(r"\b\d{6}\s*[-~]\s*[1-8]\d{6}\b"), "[REDACTED_RRN]"),
    # 신용카드 번호 (4-4-4-4)
    ("card", re.compile(r"\b(?:\d{4}[-\s]){3}\d{4}\b"), "[REDACTED_CARD]"),
    # 휴대폰 및 개인 전화번호 (010-xxxx-xxxx, +82-10-xxxx-xxxx, 02-xxx-xxxx 등)
    ("phone", re.compile(r"(?:\+82[-\s]?10|01[016789]|02|0[3-6][1-5])[-\s.]?\d{3,4}[-\s.]?\d{4}\b"), "[REDACTED_PHONE]"),
    # 이메일 주소
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    # JWT 토큰
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_TOKEN]"),
    # Bearer / API 키 / 쿠키 / 세션 토큰 / 비밀번호 파라미터
    (
        "secret",
        re.compile(
            r"(?i)\b(?:bearer\s+[A-Za-z0-9._\-+/=]{12,}|(?:api[_-]?key|access[_-]?token|auth[_-]?token|session[_-]?id|csrf[_-]?token|password|passwd|pwd|cookie|set-cookie)\s*[:=]\s*['\"]?[^\s'\";,&]{4,}['\"]?)"
        ),
        "[REDACTED_CREDENTIAL]",
    ),
    # 상세 주거 주소 (동·호수 및 번지 상세)
    (
        "address",
        re.compile(
            r"(?:[가-힣]+(?:시|도)\s+[가-힣]+(?:구|군|시)\s+[가-힣0-9]+(?:로|길|동)\s+\d+(?:-\d+)?\s*(?:[가-힣0-9]+아파트|[가-힣0-9]+빌라|\d+동\s*\d+호))"
        ),
        "[REDACTED_ADDRESS]",
    ),
    (
        "apt_unit",
        re.compile(r"\b\d{1,4}동\s*\d{1,4}호\b"),
        "[REDACTED_ADDRESS_UNIT]",
    ),
    # 계좌번호 패턴 (은행명 + 숫자열)
    (
        "bank_account",
        re.compile(r"(?:국민|신한|우리|하나|농협|기업|카카오뱅크|토스뱅크)\s*\d{2,6}[-\s]\d{2,6}[-\s]\d{2,6}"),
        "[REDACTED_ACCOUNT]",
    ),
    # 아동 개인정보 / 건강·진료 기록 민감 문구
    (
        "child_or_health",
        re.compile(r"(?:환자번호|진료기록번호|건강보험증번호|아동\s*주민번호|어린이집\s*원아번호)\s*[:：]?\s*[A-Za-z0-9-]+"),
        "[REDACTED_SENSITIVE_ID]",
    ),
    # DM / 비공개 대화 / 회원 전용 메시지 마커
    (
        "private_dm",
        re.compile(r"(?i)(?:\[비공개\s*DM\]|\[1:1\s*쪽지\]|\[회원\s*전용\s*대화\][^\n]*)"),
        "[REDACTED_PRIVATE_MESSAGE]",
    ),
]

# 2. 프롬프트 인젝션 및 명령문 패턴 (자료 내 명령문을 봇 지시로 취급하지 않도록 격리)
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?"),
    re.compile(r"(?i)disregard\s+(?:all\s+)?(?:previous|prior|system)\s+(?:instructions?|prompts?)"),
    re.compile(r"(?i)system\s*prompt\s*:"),
    re.compile(r"(?i)you\s+are\s+now\s+(?:a|an|in)\s+"),
    re.compile(r"이전\s*지시를\s*무시하(?:고|라|세요)"),
    re.compile(r"이\s*명령을\s*실행하(?:고|라|세요)"),
    re.compile(r"시스템\s*프롬프트를?\s*(?:출력|무시|변경)"),
    re.compile(r"관리자\s*권한으로\s*즉시\s*실행"),
    re.compile(r"(?i)<\s*script[^>]*>"),
    re.compile(r"(?i)javascript\s*:"),
]

# 3. HTML에서 제거할 불필요·민감 태그 (입력창, 폼, 스크립트, 댓글, 네비게이션 등)
STRIP_HTML_BLOCKS_RE = re.compile(
    r"(?is)<(script|style|noscript|iframe|svg|canvas|form|input|textarea|select|button|nav|footer|aside)\b[^>]*>.*?</\1>"
    r"|<(input|meta|link|hr|br)\b[^>]*/?>"
    r"|<!--.*?-->"
)


def extract_main_region(html: str) -> str:
    """페이지 전체를 저장하지 않고 본문 핵심 영역(article/main/본문 문단)만 추출하며 입력창·스크립트를 제거한다."""
    if not html:
        return ""
    cleaned = STRIP_HTML_BLOCKS_RE.sub(" ", html)
    # article 또는 main 영역 우선 추출
    match = re.search(r"(?is)<article\b[^>]*>(.*?)</article>", cleaned)
    if not match:
        match = re.search(r"(?is)<main\b[^>]*>(.*?)</main>", cleaned)
    region = match.group(1) if match else cleaned
    # 나머지 HTML 태그 제거 및 공백 정규화
    text = re.sub(r"<[^>]+>", " ", region)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4000]  # 전문 복제 방지: 사실 추출에 필요한 상한 길이로 제한


def sanitize_untrusted_text(text: str) -> Tuple[str, bool]:
    """페이지 안의 명령문('이 명령을 실행하라', 'Ignore previous instructions' 등)을 무력화하고 감지 여부를 반환."""
    if not text:
        return "", False
    detected = False
    out = text
    for rx in PROMPT_INJECTION_PATTERNS:
        if rx.search(out):
            detected = True
            out = rx.sub("[UNTRUSTED_COMMAND_STRING_ISOLATED]", out)
    return out, detected


def filter_pii_text(text: str) -> Tuple[str, int, bool]:
    """문자열에서 개인정보·민감정보·프롬프트 인젝션을 모두 필터링하고 (정제된 텍스트, PII 마스킹 건수, 인젝션 감지 여부) 반환."""
    if not text:
        return "", 0, False
    # HTML input/textarea 잔여 속성 제거
    cleaned = re.sub(r"(?is)<(input|textarea|form)\b[^>]*>", "[REDACTED_FORM_FIELD]", str(text))
    redactions = 0
    for _name, rx, repl in PII_PATTERNS:
        cleaned, n = rx.subn(repl, cleaned)
        redactions += n
    cleaned, inj = sanitize_untrusted_text(cleaned)
    return cleaned, redactions, inj


def sanitize_and_filter_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """수집 레코드 전체를 로컬 DB 저장 전에 검사·정제한다."""
    rec = dict(record)
    # 쿠키·토큰·비밀번호·원시 전체 HTML 필드가 혹시라도 들어왔다면 저장 전 즉시 삭제
    for forbidden_key in ("cookies", "headers", "raw_html", "full_html", "session_token", "password", "form_inputs", "dm_thread"):
        rec.pop(forbidden_key, None)

    total_redactions = 0
    injection_detected = False

    str_fields = [
        "title",
        "outlet",
        "author_statement",
        "critical_thesis",
        "counter_argument",
        "evidence_locator",
        "conflict_note",
    ]
    for field in str_fields:
        if rec.get(field):
            cleaned, n, inj = filter_pii_text(str(rec[field]))
            rec[field] = cleaned
            total_redactions += n
            if inj:
                injection_detected = True

    # extracted_facts 정제
    facts = rec.get("extracted_facts") or []
    cleaned_facts = []
    for f in facts:
        if isinstance(f, dict):
            cf = {}
            for k, v in f.items():
                if isinstance(v, str):
                    cv, n, inj = filter_pii_text(v)
                    cf[k] = cv
                    total_redactions += n
                    if inj:
                        injection_detected = True
                else:
                    cf[k] = v
            cleaned_facts.append(cf)
        elif isinstance(f, str):
            cv, n, inj = filter_pii_text(f)
            cleaned_facts.append(cv)
            total_redactions += n
            if inj:
                injection_detected = True
    rec["extracted_facts"] = cleaned_facts

    # work / edition 딕셔너리 내부 문자열 정제 (저자명·번역자명 등 공개 직업 정보는 유지하되 연락처·토큰은 제거)
    for dict_field in ("work", "edition"):
        d = rec.get(dict_field)
        if isinstance(d, dict):
            cd = {}
            for k, v in d.items():
                if k in ("personal_phone", "personal_email", "home_address", "sns_dm"):
                    total_redactions += 1
                    continue
                if isinstance(v, str):
                    cv, n, inj = filter_pii_text(v)
                    cd[k] = cv
                    total_redactions += n
                    if inj:
                        injection_detected = True
                else:
                    cd[k] = v
            rec[dict_field] = cd

    rec["pii_filtered"] = 1
    rec["pii_redactions_count"] = total_redactions
    rec["prompt_injection_detected"] = 1 if injection_detected else 0
    return rec
