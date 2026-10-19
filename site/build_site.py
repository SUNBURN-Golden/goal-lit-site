#!/usr/bin/env python3
"""Goal Lit static site builder — a criticism-first webzine for Korean literature, webtoons and web novels.
(Direction reset 2026-10-17: the works themselves + editor 평론 are the subject; film/drama adaptations are only a one-line "관련 매체" note. Old adaptation build archived in ../archive/adaptation-v1/.)

Single sources of truth:
  ../data/works.csv                 work facts that carry dates/status (medium, genres, author, last_verified)
  ../data/human_ratings.csv         HUMAN ratings only (empty for now). Editor posts never feed this.
  ../personas/personas.json         9 pen-name 에디터 (3 section editors + 6 angle editors); abstract glyph avatars only
  content/works.json                Korean copy + facts [label,value,tier,url,source_label] + optional small 'related' media note
  content/posts.json                editor posts (read level B = synthesis of publicly reported reactions, no scores)
  ../research/do_not_copy.txt       source sentences that must not reappear verbatim (15-char shingle check)

Design (준태님): writers appear as plain pen-name 에디터 bylines. No per-post AI badge or fixed label. ONE short, non-prominent
note on /principles/ says editorial pieces are produced with AI assistance under the editors' pen names (the build requires it).
The build REFUSES to publish if a post lacks its public-synthesis framing + dated source list, makes an "I read/watched it" claim,
carries a star/score, has a long quote, copies a known source sentence, cites an unknown source, if a pen name gets an invented
human biography/photo/age/job, if editor opinion leaks into human-rating views, if the principles-page AI note is missing,
or if a work has no tier 1-3 fact. Every page is noindex; robots Disallow. Stdlib only (+fonttools for font subset).
Nothing is deployed, sent or requested over the network.
"""
import argparse, csv, datetime as dt, html, json, re, shutil, sys
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "data"
DIST = ROOT / "dist"
BRAND, BRAND_NOTE = "Goal Lit", "비공개 프리뷰"
TAGLINE = "한국 문학·웹툰·웹소설 평론 웹진"
GENRES = {"순문학": "literary", "단편·소설집": "short", "시·에세이": "poetry-essay", "SF": "sf", "판타지": "fantasy", "미스터리·스릴러": "mystery",
          "로맨스": "romance", "호러": "horror", "무협": "wuxia", "웹툰": "webtoon", "웹소설": "webnovel"}
GENRE_NOTE = {"순문학": "장편·중단편 소설과 문학상 수상작", "단편·소설집": "소설집·초단편집", "시·에세이": "시집과 에세이", "SF": "과학소설", "판타지": "판타지·환상 문학",
              "미스터리·스릴러": "추리·범죄·스릴러", "로맨스": "로맨스·로맨스 판타지", "호러": "공포·괴담·환상호러", "무협": "무협 장르", "웹툰": "웹툰", "웹소설": "웹소설·연재 소설"}
MEDIUM_ORDER = ["소설", "소설집", "시집", "에세이", "웹툰", "웹소설"]
RELATED_MAX = 80
WD = "월화수목금토일"
TIERS = {1: ("공식", "tier-1"), 2: ("공식 공지", "tier-2"), 3: ("보도", "tier-3"), 4: ("참고", "tier-4")}
ENABLED_LEVELS = {"B"}   # A (read the work) and C (human-written) are NOT enabled in this build.
HUMAN_MIN_N = 10         # human average is only shown from this many human ratings
E = html.escape

LEAK = [r"변호사", r"로스쿨", r"법무", r"법학", r"\b442\b", r"KWANG", r"크왕", r"한셋", r"HANSET", r"hanset@",
        r"\b0\d{1,2}-\d{3,4}-\d{4}\b", r"\b010\d{8}\b", r"@(naver|gmail|daum)\.com"]
# first-person / experience claims a pen-name editor must never make (checked on body text + framing)
EXPERIENCE = re.compile(r"(읽었|읽어봤|읽어 봤|읽고 나|봤다|봤어|봤습니|봤는데|보았|시청했|관람했|정주행했|울었|웃었|감동받|감동했|느꼈|인상 깊게|제가 읽|제가 보|내가 읽|내가 보|직접 읽|직접 봤|직접 본)")
SCORE = re.compile(r"(★|☆|별점|평점\s*\d|\d(\.\d)?\s*/\s*(5|10)\b|\d(\.\d)?\s*점을 (주|매)|만점)")
PROMO = re.compile(r"(인생작|역대급|꼭 봐야|무조건 (봐|읽)|필독|필람|강추)")
QUOTE = re.compile(r"[“\"「]([^”\"」]{1,200})[”\"」]")
MAX_QUOTE, MAX_QUOTE_TOTAL, SHINGLE = 12, 40, 15
# invented human biography for a pen name (age / job / schooling / residence / family / photo): checked on persona fields and post framing
BIO = re.compile(r"(\d{2}\s*(살|세)(?![가-힣])|\d{2}대\s|출신|졸업|재직|근무|직장인|대학원생|대학생|프리랜서|전직|현직|거주|결혼|육아|두 아이|본명|프로필 사진|얼굴 사진)")
BIO_KEYS = {"photo", "avatar_url", "image", "img", "bio", "biography", "age", "job", "occupation", "birth", "birthday", "gender", "residence", "career", "education", "real_name"}
PERSONA_KEYS = {"id", "kind", "name", "badge", "tagline", "domain", "lens", "rubric", "blind_spot", "style", "banned_phrases", "glyph", "version", "status", "changelog", "template"}
GLYPH_SHAPES = {"arc", "grid", "frame", "tick", "duo", "nodes", "wave", "sun", "thorn"}
POST_FORBIDDEN_KEYS = {"rating", "ratings", "score", "scores", "stars", "overall_score", "human_rating", "reader_rating", "label_text"}
AI_NOTE = "AI의 도움을 받아"      # must appear on /principles/ (the one site-wide AI-assistance note)
AI_NOTE_MAX = 160                # ...as ONE short sentence, not a banner

def fail(msg): sys.exit(f"ERROR: {msg}")

# robots.txt audit (research/robots/_summary.json, made by research/audit_robots.py): domains that name AI crawlers with Disallow: /
# (or disallow everything except a few named bots) are NEVER a basis for a post. On work pages they may remain only as a bare
# bibliographic citation listed in research/robots/bare_citations.json (title/date/number facts, no reproduced content).
def _bare(u): return urlparse(u).netloc.lower().replace("www.", "")
def load_blocked_hosts():
    f = ROOT.parent / "research/robots/_summary.json"
    if not f.exists(): fail("research/robots/_summary.json missing — run the robots audit before building")
    return {d.lower().replace("www.", "") for d, v in json.loads(f.read_text(encoding="utf-8")).items() if v["status"] == "BLOCKS-AI" or v.get("star_blocks_all")}
BLOCKED_HOSTS = load_blocked_hosts()
def load_bare_ok():
    f = ROOT.parent / "research/robots/bare_citations.json"
    return {(x["work"], x["label"]) for x in json.loads(f.read_text(encoding="utf-8"))} if f.exists() else set()
BARE_OK = load_bare_ok()
def ymd(s): return dt.date.fromisoformat(s)
def dot(d): return d.strftime("%Y.%m.%d")
def host(u): return urlparse(u).netloc.replace("www.", "")
def span(d): return f"{d.month}/{d.day}({WD[d.weekday()]})"
def read_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f: return list(csv.DictReader(f))
def squash(s): return re.sub(r"[\s\W_]+", "", s)

# ---------------------------------------------------------------- load + validate
def check_persona(p):
    """A pen name is a byline + a stated way of sorting public reactions. It must not grow a fake human life."""
    if sum(p["rubric"].values()) != 100: fail(f"persona {p['id']}: rubric weights must sum to 100")
    if not p.get("blind_spot"): fail(f"persona {p['id']}: blind_spot must be disclosed")
    if p["badge"] != "에디터": fail(f"persona {p['id']}: byline must be the plain word 에디터")
    if p["kind"] not in ("section", "angle"): fail(f"persona {p['id']}: bad kind")
    extra = set(p) - PERSONA_KEYS
    if extra: fail(f"persona {p['id']}: unexpected/biographical fields {sorted(extra)}")
    g = p["glyph"]
    if set(g) != {"shape", "color"} or g["shape"] not in GLYPH_SHAPES or not re.fullmatch(r"#[0-9A-Fa-f]{6}", g["color"]):
        fail(f"persona {p['id']}: avatar must be an abstract glyph (no photos/images)")
    txt = json.dumps({k: p[k] for k in ("name", "tagline", "domain", "lens", "blind_spot", "style")}, ensure_ascii=False)
    m = BIO.search(txt)
    if m: fail(f"persona {p['id']}: invented human biography/photo/age/job: …{txt[max(0, m.start()-15):m.end()+15]}…")

def load_personas():
    d = json.loads((ROOT.parent / "personas/personas.json").read_text(encoding="utf-8"))
    ps = d["personas"]
    if len(ps) != 9 or sum(p["kind"] == "section" for p in ps) != 3: fail("personas.json must define 3 section editors + 6 angle editors")
    if len({p["name"] for p in ps}) != 9: fail("pen names must be unique")
    for p in ps: check_persona(p)
    return d["dims"], {p["id"]: p for p in ps}

def check_work_sources(slug, c):
    for f in c["facts"]:
        if _bare(f[3]) in BLOCKED_HOSTS and (slug, f[0]) not in BARE_OK: fail(f"{slug!r}: fact {f[0]!r} cites an AI-blocking domain ({_bare(f[3])}) and is not on the bare-citation list")
    rl = c.get("related")
    if rl and _bare(rl["url"]) in BLOCKED_HOSTS and (slug, "related") not in BARE_OK: fail(f"{slug!r}: related note cites an AI-blocking domain and is not on the bare-citation list")

def load_works():
    rows = {r["slug"]: r for r in read_csv(DATA / "works.csv")}
    content = json.loads((ROOT / "content/works.json").read_text(encoding="utf-8"))
    works = []
    for slug, c in content.items():
        r = rows.get(slug) or fail(f"{slug!r} not in works.csv")
        if r["status"] != "verified": fail(f"refusing to publish {slug!r} ({r['status']})")
        for f in c["facts"]:
            if len(f) != 5 or not f[3].startswith("http") or f[2] not in TIERS: fail(f"bad fact in {slug}: {f[:2]}")
        if not any(f[2] <= 3 for f in c["facts"]): fail(f"{slug!r} has only tier-4 facts")
        check_work_sources(slug, c)
        if not c.get("unverified"): fail(f"{slug!r} must list what is NOT verified")
        genres = [g for g in r["genres"].split(";") if g]
        if not genres or any(g not in GENRES for g in genres): fail(f"{slug!r}: unknown genre in {genres}")
        if r["medium"] not in MEDIUM_ORDER: fail(f"{slug!r}: unknown medium {r['medium']!r}")
        rel = c.get("related")
        if rel and (len(rel["text"]) > RELATED_MAX or not rel["url"].startswith("http") or not rel.get("label")):
            fail(f"{slug!r}: related-media note must be one short line (<= {RELATED_MAX} chars) with a source")
        works.append(dict(c=c, slug=slug, title=c["title"], kind=c["kind"], summary=c["summary"], facts=c["facts"], unverified=c["unverified"], related=rel,
                          medium=r["medium"], genres=genres, author=r["author"], platform=r["publisher_platform"], pub=r["first_published"],
                          precision=r["date_precision"], verified=ymd(r["last_verified"]), row=r))
    works.sort(key=lambda w: (MEDIUM_ORDER.index(w["medium"]), w["title"]))
    return works

def post_text(p):
    parts = [p["title"], p["summary"], p["verdict"], *p["limits"]]
    for s in p["sections"]: parts += [s["h"], *s["p"]]
    for o in p["opinions"]: parts += [o["topic"], o["gist"]]
    if p.get("metrics"): parts.append(p["metrics"]["text"])
    return "\n".join(parts)

def validate_post(p, personas, works, dnc):
    pid = p.get("slug", "?")
    pe = personas.get(p["persona"]) or fail(f"post {pid}: unknown persona")
    if p["work"] not in {w["slug"] for w in works}: fail(f"post {pid}: unknown work")
    # 1. framing: every post says, in plain words, that it synthesises publicly reported reactions (no fixed badge/label wording)
    bad_keys = POST_FORBIDDEN_KEYS & set(p)
    if bad_keys: fail(f"post {pid}: forbidden field(s) {sorted(bad_keys)} (editors give no ratings; no label field)")
    fr = (p.get("framing") or "").strip()
    if not fr: fail(f"post {pid}: framing is empty — every post must say it is a synthesis of publicly reported reactions")
    if "공개" not in fr or not re.search(r"(종합|정리|요약)", fr) or pe["name"] not in fr:
        fail(f"post {pid}: framing must name the pen-name editor and say it synthesises publicly reported reactions")
    if EXPERIENCE.search(fr.replace("직접 읽거나 보고 쓴 후기가 아니", "")): fail(f"post {pid}: experience claim in framing")
    if BIO.search(fr): fail(f"post {pid}: biographical detail about the pen name in framing")
    # 2. read level
    if p["read_level"] not in ENABLED_LEVELS: fail(f"post {pid}: read_level {p['read_level']} is not enabled in this build")
    if p.get("persona_version") != pe["version"]: fail(f"post {pid}: persona_version mismatch")
    # 3. sources
    srcs = {s["id"]: s for s in p["sources"]}
    if len(srcs) != len(p["sources"]): fail(f"post {pid}: duplicate source ids")
    for s in srcs.values():
        if not s["url"].startswith("http") or not s["outlet"] or not s["title"] or "date" not in s: fail(f"post {pid}: incomplete source {s['id']} (needs media, title, URL, date field)")
    if not srcs: fail(f"post {pid}: no sources")
    for s_ in srcs.values():
        if _bare(s_["url"]) in BLOCKED_HOSTS: fail(f"post {pid}: source {s_['id']} is on an AI-blocking domain ({_bare(s_['url'])}) — robots.txt audit")
    used = {c for sec in p["sections"] for c in sec["cite"]} | {c for o in p["opinions"] for c in o["cite"]} | set(p["metrics"]["cite"] if p.get("metrics") else [])
    if not used: fail(f"post {pid}: nothing cites a source")
    cites = [c for s in p["sections"] for c in s["cite"]] + [c for o in p["opinions"] for c in o["cite"]] + (p["metrics"]["cite"] if p.get("metrics") else [])
    for c in cites:
        if c not in srcs: fail(f"post {pid}: cites unknown source {c!r}")
    for o in p["opinions"]:
        if not o["cite"]: fail(f"post {pid}: opinion {o['topic']!r} has no citation")
        if o["stance"] not in ("호평", "비판", "중립"): fail(f"post {pid}: bad stance")
    if not p["pre_release"]:
        if len(p["opinions"]) < 3 or len({srcs[c]["outlet"] for o in p["opinions"] for c in o["cite"]}) < 2:
            fail(f"post {pid}: needs >=3 cited opinions from >=2 outlets")
        if not any(o["stance"] == "호평" for o in p["opinions"]) or not any(o["stance"] == "비판" for o in p["opinions"]):
            fail(f"post {pid}: post-release synthesis must show both positive and critical reactions (or say none were found)")
    elif not p["opinions"] and not p.get("no_reaction_notice"): fail(f"post {pid}: pre-release post without opinions needs no_reaction_notice")
    if len(p["limits"]) < 3: fail(f"post {pid}: needs a limits section (>=3 items)")
    # 4. text rules
    txt = post_text(p)
    for rx, why in ((EXPERIENCE, "first-person experience claim"), (SCORE, "score/star rating (read level B has none)"), (PROMO, "promotional superlative")):
        m = rx.search(txt)
        if m: fail(f"post {pid}: {why}: …{txt[max(0, m.start()-15):m.end()+15]}…")
    for b in pe["banned_phrases"]:
        if b in txt: fail(f"post {pid}: persona banned phrase {b!r}")
    qs = [q for q in QUOTE.findall(txt)]
    if any(len(q) > MAX_QUOTE for q in qs) or sum(map(len, qs)) > MAX_QUOTE_TOTAL: fail(f"post {pid}: quotes too long {qs}")
    sq = squash(txt)
    for line in dnc:
        sl = squash(line)
        for i in range(0, max(len(sl) - SHINGLE + 1, 0)):
            if sl[i:i + SHINGLE] in sq: fail(f"post {pid}: copies a known source sentence ({line[:20]}…)")

def load_posts(personas, works):
    posts = json.loads((ROOT / "content/posts.json").read_text(encoding="utf-8"))
    dnc = [l.strip() for l in (ROOT.parent / "research/do_not_copy.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    for p in posts: validate_post(p, personas, works, dnc)
    return posts

def load_human(works):
    out = {w["slug"]: [] for w in works}
    for r in read_csv(DATA / "human_ratings.csv"):
        if r["rater_type"] != "human": fail("human_ratings.csv may only contain rater_type=human")
        out.setdefault(r["work_slug"], []).append(float(r["rating"]))
    return out

# ---------------------------------------------------------------- rendering
def glyph(shape, color):
    c = color
    g = {"arc": f'<path d="M10 32a12 12 0 0 1 24 0" fill="none" stroke="{c}" stroke-width="4" stroke-linecap="round"/>',
         "grid": "".join(f'<rect x="{10+i%2*13}" y="{10+i//2*13}" width="10" height="10" rx="2" fill="{c}"/>' for i in range(4)),
         "frame": f'<rect x="10" y="12" width="24" height="20" rx="3" fill="none" stroke="{c}" stroke-width="4"/><path d="M16 38h12" stroke="{c}" stroke-width="3" stroke-linecap="round"/>',
         "tick": f'<path d="M22 8v14l8 6" fill="none" stroke="{c}" stroke-width="4" stroke-linecap="round"/><circle cx="22" cy="22" r="14" fill="none" stroke="{c}" stroke-width="2.5"/>',
         "duo": f'<circle cx="17" cy="22" r="8" fill="{c}"/><circle cx="28" cy="22" r="8" fill="none" stroke="{c}" stroke-width="3"/>',
         "nodes": f'<path d="M12 30l10-16 10 16z" fill="none" stroke="{c}" stroke-width="2.5"/>' + "".join(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{c}"/>' for x, y in ((12, 30), (22, 14), (32, 30))),
         "wave": f'<path d="M8 24c4-10 8-10 12 0s8 10 12 0 4-4 4-4" fill="none" stroke="{c}" stroke-width="4" stroke-linecap="round"/>',
         "sun": f'<circle cx="22" cy="22" r="7" fill="{c}"/>' + "".join(f'<path d="M22 6v5M22 33v5M6 22h5M33 22h5" stroke="{c}" stroke-width="3" stroke-linecap="round"/>' for _ in (0,)),
         "thorn": f'<path d="M12 34L22 8l10 26-10-6z" fill="{c}"/>'}[shape]
    return f'<svg class="glyph" viewBox="0 0 44 44" role="img" aria-label="에디터 아이콘(추상 도형)">{g}</svg>'

def tier_badge(t): lab, cls = TIERS[t]; return f'<span class="tier {cls}">{lab}</span>'
def src_html(f): return f'{tier_badge(f[2])} <a href="{E(f[3])}" rel="noopener noreferrer">{E(f[4])}</a>'
def facts_table(items):
    rows = "".join(f'<tr><th>{E(k)}</th><td><span class="v">{E(v)}</span><span class="srcline">{src_html((k, v, t, u, l))}</span></td></tr>' for k, v, t, u, l in items)
    return f'<table class="facts"><tbody>{rows}</tbody></table>'
TIERKEY = '<div class="tierkey">' + "".join(f'<span>{tier_badge(t)}</span>' for t in TIERS) + '<a href="/sources/">등급 설명</a></div>'
def byline(p): return f'<span class="byline">{E(p["badge"])} <b>{E(p["name"])}</b></span>'
def cite_html(ids, srcs):
    if not ids: return ""
    return '<span class="cite">' + ", ".join(f'<a href="{E(srcs[i]["url"])}" rel="noopener noreferrer">{E(srcs[i]["outlet"])}</a>' for i in ids) + "</span>"

def pub_label(w):
    if w["precision"] == "unknown" or not w["pub"]: return "발표 시기 미확인"
    if w["precision"] == "year": return f'{w["pub"]}년'
    if w["precision"] == "month": y, m = w["pub"].split("-"); return f"{y}년 {int(m)}월"
    d = ymd(w["pub"]); return f"{d.year}년 {d.month}월 {d.day}일"

class Site:
    def __init__(self, today): self.today, self.pages = today, {}
    def head(self, title, desc):
        full = title if title.startswith(BRAND) else f"{title} · {BRAND}"
        return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{E(full)}</title><meta name="description" content="{E(desc)}">\n<meta name="robots" content="noindex,nofollow">\n'
                f'<meta property="og:title" content="{E(full)}"><meta property="og:description" content="{E(desc)}">'
                f'<meta name="theme-color" media="(prefers-color-scheme: light)" content="#F5F5F7"><meta name="theme-color" media="(prefers-color-scheme: dark)" content="#000000"><link rel="icon" href="/favicon.svg" type="image/svg+xml">'
                f'<link rel="preload" href="/assets/fonts/Pretendard-Regular.subset.woff2" as="font" type="font/woff2" crossorigin>'
                f'<link rel="stylesheet" href="/assets/css/site.css"></head>')
    def nav(self, active):
        cur = lambda k: ' aria-current="page"' if active == k else ""
        return ('<a class="skip" href="#main">본문으로 건너뛰기</a><div class="preview-bar">비공개 프리뷰 — 검색 노출 꺼짐(noindex) · 이 사이트의 평론 글은 필명 에디터가 공개 자료를 정리한 글이에요</div>'
                f'<header class="site-header"><div class="wrap"><div class="hrow"><a class="brand" href="/"><i></i>{BRAND}<small>{TAGLINE}</small></a>'
                f'<a class="pin" href="/principles/"{cur("principles")}>편집 원칙</a></div>'
                f'<nav class="nav" aria-label="주 메뉴"><a href="/reviews/"{cur("reviews")}>평론</a><a href="/works/"{cur("works")}>작품</a><a href="/genres/"{cur("genres")}>장르</a>'
                f'<a href="/authors/"{cur("authors")}>작가</a><a href="/new-books/"{cur("books")}>이번 주 신간·완결</a><a href="/personas/"{cur("personas")}>에디터</a></nav></div></header>')
    def foot(self):
        return (f'<footer class="site-footer"><div class="wrap"><strong>{BRAND}</strong> <span class="muted">({BRAND_NOTE})</span>'
                '<div class="flinks"><a href="/principles/">편집 원칙</a><a href="/sources/">출처 등급</a><a href="/ads/">광고·제휴 표기</a><a href="/corrections/">정정·삭제 요청</a><a href="/privacy/">개인정보 처리 안내</a></div>'
                '<p>작품 정보는 항목마다 출처와 확인일을 붙여요. 에디터 글은 공개된 기사·평론·서평을 정리한 글이고, 작품을 직접 읽거나 보고 쓴 후기가 아니에요.</p><p>© 2026</p></div></footer>')
    def add(self, path, title, desc, body, active=""):
        self.pages[path] = self.head(title, desc) + f'<body>{self.nav(active)}<main id="main" class="wrap">{body}</main>{self.foot()}</body></html>'

def genre_chips(genres, link=True):
    return "".join((f'<a class="badge badge-g" href="/genres/{GENRES[g]}/">{E(g)}</a>' if link else f'<span class="badge">{E(g)}</span>') for g in genres)

def work_card(w, posts_by_work):
    n = len(posts_by_work.get(w["slug"], []))
    gb = "".join(f'<span class="badge">{E(g)}</span>' for g in w["genres"])
    who = " · ".join(x for x in (w["author"], w["platform"]) if x)
    return (f'<article class="card"><div class="chips"><span class="badge">{E(w["medium"])}</span>{gb}</div>'
            f'<h3><a href="/works/{w["slug"]}/">{E(w["title"])}</a></h3><div class="loc">{E(who) if who else "작가 미확인"} · {E(pub_label(w))}</div>'
            f'<div class="meta">평론 {n}편 · 사람 평점 0개 · 확인일 {dot(w["verified"])}</div></article>')

def post_card(p, personas, works_by, big=False):
    pe = personas[p["persona"]]; w = works_by[p["work"]]
    st = {k: sum(1 for o in p["opinions"] if o["stance"] == k) for k in ("호평", "비판", "중립")}
    gb = "".join(f'<span class="badge">{E(g)}</span>' for g in w["genres"][:2])
    return (f'<article class="card{" lead-card" if big else ""}"><div class="chips"><span class="badge">{E(w["title"])}</span>{gb}</div>'
            f'<h3><a href="/posts/{p["slug"]}/">{E(p["title"])}</a></h3><div class="loc">{E(p["summary"])}</div>'
            f'<div class="meta">{byline(pe)} · 호평 {st["호평"]} · 비판 {st["비판"]} · 공개 자료 {len(p["sources"])}건 · 점수 없음</div></article>')

def build(site, dims, personas, works, posts, human, today):
    works_by = {w["slug"]: w for w in works}
    pbw = {}
    for p in posts: pbw.setdefault(p["work"], []).append(p)
    ordered = sorted(posts, key=lambda p: p["date"], reverse=True)
    lead, side, rest = ordered[0], ordered[1:4], ordered[4:]
    # ---- home: magazine front page, criticism first
    genre_nav = "".join(f'<a class="chip-l" href="/genres/{GENRES[g]}/">{E(g)}</a>' for g in GENRES)
    ed_nav = "".join(f'<a class="chip-l" href="/personas/{pe["id"]}/">{E(pe["name"])}</a>' for pe in personas.values())
    authors = sorted({w["author"] for w in works if w["author"]})
    site.add("/", f"{BRAND} — {TAGLINE}", "한국 문학·웹툰·웹소설을 공개된 평론·서평·보도 속 반응으로 읽는 평론 웹진(프리뷰). 평론 글은 필명 에디터가 공개 자료를 출처와 함께 정리한 글이에요.",
        f'''<section class="masthead"><span class="eyebrow">PREVIEW · 평론 웹진</span><h1>작품은 이렇게 읽혔다 — 한국 문학·웹툰·웹소설 평론</h1>
<p>소설·시·에세이부터 SF·판타지·미스터리, 웹툰과 웹소설까지. 평론가와 매체가 실제로 남긴 호평과 비판을 출처와 함께 정리해요.</p></section>
<section class="front"><div class="front-lead"><span class="kicker">오늘의 평론</span>{post_card(lead, personas, works_by, True)}</div>
<div class="front-side"><span class="kicker">이어서 읽기</span>{"".join(post_card(p, personas, works_by) for p in side)}</div></section>
<section class="sec"><div class="sec-h"><h2>평론 더 보기</h2><a href="/reviews/">전체 {len(posts)}편</a></div><div class="grid">{"".join(post_card(p, personas, works_by) for p in rest)}</div></section>
<section class="sec"><div class="sec-h"><h2>에디터별로 읽기</h2><a href="/personas/">에디터 9명 소개</a></div><div class="chip-row">{ed_nav}</div><p class="muted">에디터는 필명이에요. 각자 무엇을 먼저 정리하는지와 약점을 공개해요.</p></section>
<section class="sec"><div class="sec-h"><h2>작품</h2><a href="/works/">전체 {len(works)}편</a></div><div class="grid">{"".join(work_card(w, pbw) for w in works[:6])}</div></section>
<section class="sec"><div class="sec-h"><h2>장르</h2><a href="/genres/">전체 보기</a></div><div class="chip-row">{genre_nav}</div></section>
<section class="sec"><div class="sec-h"><h2>작가</h2><a href="/authors/">전체 {len(authors)}명</a></div><p class="muted">작품 페이지에 확인된 작가만 올려요.</p></section>
<section class="sec"><div class="sec-h"><h2>이번 주 신간·완결</h2><a href="/new-books/">준비 중</a></div><div class="todo">신간·완결 코너는 아직 열지 않았어요. 공식 서지 API와 플랫폼 공지를 확인할 수 있게 되면 열어요. 특집 에세이·칼럼 코너도 사람 검수 절차가 갖춰진 뒤에 열어요.</div></section>
<section class="band"><h2>이렇게 달라요</h2><ul class="clean"><li>에디터 글은 <strong>작품을 직접 읽거나 보고 쓴 후기가 아니에요.</strong> 공개된 평론·서평·기사를 출처와 함께 종합해요.</li><li><strong>사람 평점과 에디터 의견은 섞지 않아요.</strong> 에디터 글에는 점수가 없어요.</li><li>호평만 있거나 비판만 있으면 그렇다고 적고, 확인하지 못한 것은 &lsquo;아직 확인하지 못한 것&rsquo;에 적어요.</li></ul></section>''', "home")
    # ---- reviews index
    site.add("/reviews/", "평론", "필명 에디터가 공개된 평론·서평·기사를 종합해 정리한 글 모음.",
        f'<div class="page wide"><h1>평론</h1><p class="lead">공개된 평론·서평·보도 속 호평과 비판을 작품별로 정리한 글이에요. {len(posts)}편이고, 점수는 없어요.</p></div><div class="grid">' + "".join(post_card(p, personas, works_by) for p in ordered) + '</div>', "reviews")
    # ---- works
    groups = "".join(f'<section class="sec"><div class="sec-h"><h2>{E(m)}</h2></div><div class="grid">' + "".join(work_card(w, pbw) for w in works if w["medium"] == m) + '</div></section>' for m in MEDIUM_ORDER if any(w["medium"] == m for w in works))
    site.add("/works/", "작품", "소설·시·에세이·웹툰·웹소설을 작품별로 모았어요.",
        f'<div class="page wide"><h1>작품</h1><p class="lead">지금 {len(works)}편이에요. 작품의 가치를 기준으로 골랐고, 항목마다 출처와 확인일이 붙어요.</p>{TIERKEY}</div>{groups}', "works")
    for w in works:
        hr = human.get(w["slug"], [])
        if len(hr) >= HUMAN_MIN_N: hbody = f'<p><strong>평균 {sum(hr)/len(hr):.1f}</strong> · 사람 {len(hr)}명</p>'
        else: hbody = f'<p>사람이 남긴 평점이 아직 {len(hr)}개예요. {HUMAN_MIN_N}개 이상 모이면 평균을 보여줘요.</p>'
        ps = pbw.get(w["slug"], [])
        aibody = ("".join(f'<p>{byline(personas[p["persona"]])} <a href="/posts/{p["slug"]}/">{E(p["title"])}</a></p>' for p in ps)
                  or '<p class="muted">아직 이 작품에 대한 에디터 글이 없어요.</p>')
        unv = "<h2>아직 확인하지 못한 것</h2><ul class='clean warn-list'>" + "".join(f"<li>{E(x)}</li>" for x in w["unverified"]) + "</ul>"
        srcs = {}
        for f in w["facts"]: srcs.setdefault(f[3], f[4])
        if w["related"]: srcs.setdefault(w["related"]["url"], w["related"]["label"])
        srcl = "".join(f'<li><a href="{E(u)}" rel="noopener noreferrer">{E(l)}</a> <span class="muted">({E(host(u))})</span></li>' for u, l in srcs.items())
        rel = (f'<p class="related">관련 매체 · {E(w["related"]["text"])} <span class="cite"><a href="{E(w["related"]["url"])}" rel="noopener noreferrer">{E(w["related"]["label"])}</a></span></p>' if w["related"] else "")
        who = " · ".join(x for x in (w["author"], w["platform"]) if x)
        body = f'''<div class="detail"><p class="crumb"><a href="/works/">작품</a> › {E(w["medium"])}</p>
<div class="chips"><span class="badge">{E(w["medium"])}</span>{genre_chips(w["genres"])}</div><h1>{E(w["title"])}</h1><p class="muted">{E(w["kind"])} · {E(who) if who else "작가 미확인"} · {E(pub_label(w))}</p>
<p class="lead">{E(w["summary"])}</p>{TIERKEY}
<h2>평론</h2><div class="panel editors"><h3>에디터의 글</h3>{aibody}<p class="muted">에디터 글에는 점수가 없어요. 공개된 평론·서평·기사를 정리한 글이에요.</p></div>
<h2>작품 정보</h2>{facts_table(w["facts"])}{rel}
<h2>사람 평점</h2><div class="panel human"><h3>사람 평점</h3>{hbody}<p class="muted">사람이 직접 남긴 평점만 세요. 에디터 글과 의견은 여기에 들어가지 않아요.</p></div>
{unv}
<div class="verify"><p><strong>확인일 {dot(w["verified"])}</strong></p><p>이 페이지에 쓴 출처 전체:</p><ul class="clean">{srcl}</ul><p>정보가 다르면 <a href="/corrections/">정정·삭제 요청</a>으로 알려 주세요.</p></div>
<div class="note">이 페이지에는 광고나 제휴 링크가 없어요.</div></div>'''
        site.add(f'/works/{w["slug"]}/', w["title"], f'{w["title"]} — {w["summary"]}'[:150], body, "works")
    # ---- genres
    gcards = "".join(f'<article class="card"><h3><a href="/genres/{GENRES[g]}/">{E(g)}</a></h3><div class="loc">{E(GENRE_NOTE[g])}</div><div class="meta">작품 {sum(1 for w in works if g in w["genres"])}편 · 평론 {sum(len(pbw.get(w["slug"], [])) for w in works if g in w["genres"])}편</div></article>' for g in GENRES)
    site.add("/genres/", "장르", "소설·시·에세이·SF·판타지·미스터리·웹툰·웹소설 장르별로 모아봤어요.", f'<div class="page wide"><h1>장르</h1><p class="lead">한 작품이 여러 장르에 걸칠 수 있어요.</p></div><div class="grid">{gcards}</div>', "genres")
    for g, gs in GENRES.items():
        ws = [w for w in works if g in w["genres"]]
        ps = [p for p in ordered if g in works_by[p["work"]]["genres"]]
        site.add(f"/genres/{gs}/", g, f"{g} 작품과 평론.",
            f'<div class="page wide"><p class="crumb"><a href="/genres/">장르</a></p><h1>{E(g)}</h1><p class="lead">{E(GENRE_NOTE[g])}</p></div>'
            + (f'<section class="sec"><div class="sec-h"><h2>평론</h2></div><div class="grid">{"".join(post_card(p, personas, works_by) for p in ps)}</div></section>' if ps else '<div class="todo">이 장르의 평론은 아직 없어요.</div>')
            + f'<section class="sec"><div class="sec-h"><h2>작품</h2></div><div class="grid">{"".join(work_card(w, pbw) for w in ws)}</div></section>', "genres")
    # ---- authors
    by_author = {}
    for w in works:
        if w["author"]: by_author.setdefault(w["author"], []).append(w)
    arows = "".join(f'<article class="card"><h3>{E(a)}</h3><p class="loc">' + " · ".join(f'<a href="/works/{w["slug"]}/">{E(w["title"])}</a>' for w in ws) + '</p></article>' for a, ws in sorted(by_author.items()))
    site.add("/authors/", "작가", "작품 페이지에서 확인된 작가 목록.", f'<div class="page wide"><h1>작가</h1><p class="lead">이 사이트에 올라온 작품의 작가예요. 필명은 필명 그대로 적어요. 작가 소개문은 따로 쓰지 않아요.</p></div><div class="grid">{arows}</div>', "authors")
    # ---- personas
    def pcard(p):
        return (f'<article class="card"><div class="prow">{glyph(p["glyph"]["shape"], p["glyph"]["color"])}<div>{byline(p)}<h3 class="tight"><a href="/personas/{p["id"]}/">{E(p["name"])} — {E(p["tagline"])}</a></h3></div></div>'
                f'<div class="loc">{E(p["domain"])}</div><div class="meta">정리 관점 v{p["version"]} · 초안</div></article>')
    eds = [p for p in personas.values() if p["kind"] == "section"]; rds = [p for p in personas.values() if p["kind"] == "angle"]
    site.add("/personas/", "에디터", "이 사이트의 필명 에디터 9명 소개.",
        f'<div class="page"><h1>에디터</h1><p class="lead">이 사이트의 글은 필명 에디터가 써요. 공개된 기사·리뷰·후기를 출처와 함께 종합해 정리하고, 각자 &lsquo;무엇을 먼저 정리하는지&rsquo;와 <strong>약점</strong>을 공개해요. 필명이라 이력·사진 같은 개인 정보는 없어요.</p></div>'
        f'<section class="sec"><div class="sec-h"><h2>분야 담당 에디터 3</h2></div><div class="grid">{"".join(pcard(p) for p in eds)}</div></section>'
        f'<section class="sec"><div class="sec-h"><h2>관점 담당 에디터 6</h2></div><div class="grid">{"".join(pcard(p) for p in rds)}</div></section>', "personas")
    for p in personas.values():
        bars = "".join(f'<div class="bar"><span>{E(k)}</span><i class="w{v}"></i> {v}</div>' for k, v in p["rubric"].items())
        mine = [x for x in posts if x["persona"] == p["id"]]
        plist = "".join(f'<li><a href="/posts/{x["slug"]}/">{E(x["title"])}</a></li>' for x in mine) or '<li class="muted">아직 글이 없어요.</li>'
        log = "".join(f'<li>v{c["version"]} ({c["date"]}) {E(c["note"])}</li>' for c in p["changelog"])
        body = f'''<div class="detail"><p class="crumb"><a href="/personas/">에디터</a></p><div class="prow">{glyph(p["glyph"]["shape"], p["glyph"]["color"])}<div>{byline(p)}<h1 class="tight">{E(p["name"])}</h1></div></div>
<p class="lead">{E(p["tagline"])} · 필명이에요. 이력·사진은 공개하지 않아요.</p>
<h2>정리 관점</h2><p>{E(p["lens"])}.</p><p class="muted">담당 영역: {E(p["domain"])}</p>
<h2>무엇을 비중 있게 정리하나요</h2><p class="muted">공개 반응을 정리할 때 각 영역에 두는 비중(합계 100)이에요. 작품 점수가 아니에요.</p><div class="bars">{bars}</div>
<div class="limits"><h3>이 에디터의 약점(공개)</h3><p>{E(p["blind_spot"])}</p></div>
<h2>글쓰기 규칙</h2><ul class="clean">{"".join(f"<li>{E(s)}</li>" for s in p["style"])}<li>글 구성: {" → ".join(E(s) for s in p["template"])}</li><li>직접 경험 주장·별점·과장 표현을 쓰지 않아요.</li></ul>
<h2>쓴 글</h2><ul class="clean">{plist}</ul>
<h2>버전 기록</h2><ul class="clean">{log}</ul></div>'''
        site.add(f'/personas/{p["id"]}/', f'{p["badge"]} {p["name"]}', f'{p["badge"]} {p["name"]} — {p["tagline"]}', body, "personas")
    # ---- posts
    for x in posts:
        pe = personas[x["persona"]]; w = works_by[x["work"]]; srcs = {s["id"]: s for s in x["sources"]}
        secs = "".join(f'<h2>{E(s["h"])}</h2>' + "".join(f"<p>{E(t)}</p>" for t in s["p"]) + (f'<p>{cite_html(s["cite"], srcs)}</p>' if s["cite"] else "") for s in x["sections"])
        if x["opinions"]:
            cls = {"호평": "st-good", "비판": "st-bad", "중립": "st-mid"}
            ops = "".join(f'<li><span class="stance {cls[o["stance"]]}">{o["stance"]}</span><strong>{E(o["topic"])}</strong><br>{E(o["gist"])} {cite_html(o["cite"], srcs)}</li>' for o in x["opinions"])
            opsb = f'<h2>평가가 갈리는 지점</h2><p class="muted">평론·서평·기사에 담긴 의견을 다시 정리한 것이에요. 원문을 옮기지 않았어요.</p><ul class="ops">{ops}</ul>'
        else: opsb = f'<h2>공개 반응</h2><div class="todo">{E(x.get("no_reaction_notice", "반응 없음"))}</div>'
        met = f'<h2>공개 지표</h2><p>{E(x["metrics"]["text"])} {cite_html(x["metrics"]["cite"], srcs)}</p>' if x.get("metrics") else ""
        lim = "<div class='limits'><h3>이 글의 한계</h3><ul class='clean'>" + "".join(f"<li>{E(t)}</li>" for t in x["limits"]) + "</ul></div>"
        srcl = "".join(f'<li>{E(s["outlet"])} · <a href="{E(s["url"])}" rel="noopener noreferrer">{E(s["title"])}</a> <span class="muted">({E(s["kind"])}{", " + s["date"] if s["date"] else ", 게재일 미확인"}{"; " + E(s["note"]) if s.get("note") else ""})</span></li>' for s in x["sources"])
        body = f'''<div class="detail post-detail"><p class="crumb"><a href="/reviews/">평론</a> › <a href="/works/{w["slug"]}/">{E(w["title"])}</a></p><div class="chips">{genre_chips(w["genres"])}</div>
<div class="prow">{glyph(pe["glyph"]["shape"], pe["glyph"]["color"])}<div>{byline(pe)}<br><span class="muted">작성 {dot(ymd(x["date"]))} · <a href="/personas/{pe["id"]}/">정리 관점 v{pe["version"]}</a> · 검수 전 샘플</span></div></div>
<h1>{E(x["title"])}</h1>
<p class="framing">{E(x["framing"])}</p>
{secs}{opsb}{met}<div class="panels"><div class="panel editors"><h3>이 글의 점수</h3><p>없음. 공개 자료를 정리한 글에는 점수를 매기지 않아요.</p></div><div class="panel human"><h3>사람 평점</h3><p>이 글과 별개로 <a href="/works/{w["slug"]}/">작품 페이지</a>에서 보여줘요.</p></div></div>
{lim}<h2>참고한 공개 자료</h2><ul class="clean">{srcl}</ul>
<div class="verify"><p>잘못 요약된 부분이 있으면 <a href="/corrections/">정정·삭제 요청</a>으로 알려 주세요. 이 글에는 광고나 제휴 링크가 없어요.</p></div></div>'''
        site.add(f'/posts/{x["slug"]}/', x["title"], x["summary"], body, "reviews")
    # ---- new books / completions stub
    site.add("/new-books/", "이번 주 신간·완결", "이번 주 신간·완결 코너는 준비 중이에요.",
        '''<div class="page"><h1>이번 주 신간·완결</h1><p class="muted">준비 중 · 비공개 프리뷰</p><p class="lead">신간 도서와 웹툰·웹소설 완결 소식은 아직 열지 않았어요. 지어낸 목록으로 채우지 않아요.</p>
<div class="todo"><ul class="clean"><li>자료 출처 후보: 국립중앙도서관 ISBN 서지 API(인증키 신청 필요), 출판사·플랫폼의 공식 신간·완결 공지(수동 확인).</li><li>열리면 각 항목에 출처·확인일이 붙고, 평론은 서평·보도에 인용된 반응이 있을 때만 붙어요.</li></ul></div></div>''', "books")
    for slug, title, desc, act in [("principles", "편집 원칙", "필명 에디터 글의 작성 원칙(초안).", "principles"), ("sources", "출처 등급", "출처 등급 설명.", "about"),
                                   ("ads", "광고·제휴 표기", "광고·제휴 표시 원칙(초안).", "about"), ("privacy", "개인정보 처리 안내", "추적 도구 없이 운영(초안).", "about"),
                                   ("corrections", "정정·삭제 요청", "정정·삭제 요청 안내.", "about")]:
        site.add(f"/{slug}/", title, desc, f'<div class="page">{(ROOT / f"content/pages/{slug}.html").read_text(encoding="utf-8")}</div>', act)
    site.add("/404.html", "페이지를 찾을 수 없어요", "페이지를 찾을 수 없어요.", '<div class="page"><h1>페이지를 찾을 수 없어요</h1><p><a href="/">홈으로</a></p></div>')
    # retired posts (robots.txt audit 2026-10-17): kept out of nav/pages; the old URL shows a plain archived notice (also overwrites stale edge copies)
    for old in ("vegetarian-translation-debate", "gray-human-reviews"):
        site.add(f"/posts/{old}/", "보관된 글이에요", "이 글은 보관 처리되어 더 이상 공개하지 않아요.", '<div class="page"><h1>보관된 글이에요</h1><p>출처 점검 결과에 따라 이 글은 공개에서 내렸어요. <a href="/sources/">출처 원칙</a> · <a href="/">홈으로</a></p></div>')

def subset_fonts(dist):
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        print("WARN: fonttools not installed; using system Korean fonts. Use /workspace/fitness-hub/site/.venv/bin/python."); return
    text = "".join(p.read_text(encoding="utf-8") for p in dist.rglob("*.html")) + "".join(p.read_text(encoding="utf-8") for p in (dist / "assets/js").glob("*.js"))
    chars = "".join(sorted(set(text + "".join(chr(c) for c in range(0x20, 0x7F)) + "₩–—·→›×℃™…“”‘’〈〉")))
    out = dist / "assets/fonts"; out.mkdir(parents=True, exist_ok=True)
    for w in ("Regular", "Bold"):
        o = subset.Options(); o.flavor = "woff2"; o.layout_features = ["*"]; o.name_IDs = ["*"]; o.notdef_outline = True
        f = TTFont(ROOT / f"static/fonts/Pretendard-{w}.otf"); s = subset.Subsetter(o); s.populate(text=chars); s.subset(f)
        f.flavor = "woff2"; f.save(out / f"Pretendard-{w}.subset.woff2")
    shutil.copy(ROOT / "static/fonts/Pretendard-OFL-LICENSE.txt", out / "Pretendard-OFL-LICENSE.txt")

def check_principles(t):
    """The ONE site-wide AI-assistance note: present on /principles/, short, and not styled as a banner."""
    m = re.search(r'<p class="muted fine">([^<]*' + re.escape(AI_NOTE) + r'[^<]*)</p>', t)
    if not m: return [("principles/index.html", "missing short AI-assistance note (<p class=\"muted fine\">…AI의 도움을 받아…</p>)", "")]
    if len(m.group(1)) > AI_NOTE_MAX or "에디터" not in m.group(1) or "필명" not in m.group(1): return [("principles/index.html", "AI note must be short and mention 필명 에디터", m.group(1))]
    return []

def leak_check(dist):
    bad = []
    alltxt = ""
    for p in dist.rglob("*.html"):
        t = p.read_text(encoding="utf-8"); alltxt += t
        rel = str(p.relative_to(dist))
        for pat in LEAK:
            m = re.search(pat, t)
            if m: bad.append((rel, pat, t[max(0, m.start() - 20):m.end() + 20]))
        if 'content="noindex,nofollow"' not in t: bad.append((rel, "missing noindex", ""))
        if "각색 트래커" in t: bad.append((rel, "stale 각색 트래커 wording (direction reset: works + 평론 first)", ""))
        if re.search(r'style="', t): bad.append((rel, "inline style attribute (blocked by CSP style-src self)", ""))
        if rel == "index.html" and t.find('class="front"') > t.find('class="grid"') and 'class="front"' in t: bad.append((rel, "home must lead with editor 평론", ""))
        if rel == "index.html" and 'class="front"' not in t: bad.append((rel, "home lacks the 평론-first front page", ""))
        if rel.startswith("posts/") and "보관된 글이에요" not in t:
            if 'class="byline"' not in t or 'class="framing"' not in t: bad.append((rel, "post without 에디터 byline/framing", ""))
            if "참고한 공개 자료" not in t or "rel=\"noopener noreferrer\"" not in t: bad.append((rel, "post without source list", ""))
            if SCORE.search(re.sub(r"<[^>]+>", " ", t)): bad.append((rel, "score on editor post page", ""))
        if rel.startswith(("posts/", "personas/")) and "<img" in t: bad.append((rel, "image on persona/post page (no photos for pen names)", ""))
        if rel.startswith("works/") and rel != "works/index.html":
            m = re.search(r'<div class="panel human">(.*?)</div>', t, re.S)
            if m and re.search(r"/posts/|/personas/|class=\"byline\"", m.group(1)): bad.append((rel, "editor content inside the human-rating panel", ""))
        if "ai-badge" in t or "ailabel" in t or re.search(r"AI 에디터|AI 독자|AI 페르소나", t): bad.append((rel, "stale per-post AI badge/label wording", ""))
    bad += check_principles((dist / "principles/index.html").read_text(encoding="utf-8") if (dist / "principles/index.html").exists() else "")
    if re.search(r"https?://[^\"' >]*(google-analytics|googletagmanager|facebook\.net|doubleclick|hotjar|clarity\.ms)", alltxt): bad.append(("*", "tracker", ""))
    return bad

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--today"); ap.add_argument("--out", default=str(DIST)); a = ap.parse_args()
    today = ymd(a.today) if a.today else dt.datetime.now(ZoneInfo("Asia/Seoul")).date()
    dims, personas = load_personas(); works = load_works(); posts = load_posts(personas, works); human = load_human(works)
    dist = Path(a.out); site = Site(today); build(site, dims, personas, works, posts, human, today)
    if dist.exists(): shutil.rmtree(dist)
    dist.mkdir(parents=True)
    for path, h in site.pages.items():
        p = dist / path.lstrip("/") if path.endswith(".html") else dist / path.lstrip("/") / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(h, encoding="utf-8")
    (dist / "assets").mkdir(); shutil.copytree(ROOT / "static/css", dist / "assets/css")
    if (ROOT / "static/js").exists(): shutil.copytree(ROOT / "static/js", dist / "assets/js")
    shutil.copy(ROOT / "static/favicon.svg", dist / "favicon.svg")
    (dist / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (dist / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  X-Frame-Options: DENY\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n"
        "  Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'\n/assets/*\n  Cache-Control: public, max-age=86400\n")
    subset_fonts(dist)
    bad = leak_check(dist)
    n = sum(1 for p in dist.rglob("*") if p.is_file())
    print(f"built {len(site.pages)} pages ({len(works)} works, {len(personas)} personas, {len(posts)} editor posts) -> {dist} ({n} files, {sum(p.stat().st_size for p in dist.rglob('*') if p.is_file())/1024:.0f} KB)")
    if bad:
        for b in bad: print("CHECK FAIL:", b)
        sys.exit(2)
    print("checks OK (framing + sources, pen-name guards, principles AI note, no experience claims, no scores, quote/copy limits, leak check, every page noindex)")

if __name__ == "__main__":
    main()
