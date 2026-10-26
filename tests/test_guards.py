#!/usr/bin/env python3
"""Negative tests: each mutation MUST make the build guard refuse it. Run: python3 tests/test_guards.py
Design: pen-name 에디터 bylines, no per-post badge or fixed label."""
import copy, importlib.util, json, sys
from pathlib import Path
R = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bs", R / "site/build_site.py"); bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
dims, personas = bs.load_personas(); works = bs.load_works()
# the baseline is a fixed fixture (a copy of a known-good post), so unpublishing/reordering posts never breaks the tests
posts = [json.loads((R / "tests/fixture_post.json").read_text(encoding="utf-8"))]
dnc = [l.strip() for l in (R / "research/do_not_copy.txt").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
base = posts[0]
def mut(f):
    p = copy.deepcopy(base); f(p); return p
def pmut(f):
    p = copy.deepcopy(personas["gyeol"]); f(p); return p
nm = base["persona"]
post_cases = {
 "missing framing": lambda p: p.pop("framing"),
 "empty framing": lambda p: p.update(framing=""),
 "framing without public-synthesis wording": lambda p: p.update(framing=f"작성 에디터 ‘{personas[nm]['name']}’(필명). 좋은 글이에요."),
 "framing without pen-name editor": lambda p: p.update(framing="공개된 기사를 종합해 정리한 글이에요."),
 "experience claim inside framing": lambda p: p.update(framing=p["framing"] + " 저는 끝까지 봤어요."),
 "biography in framing": lambda p: p.update(framing=p["framing"] + " 34세 직장인이에요."),
 "legacy label_text field": lambda p: p.update(label_text="x"),
 "editor rating field": lambda p: p.update(rating=4.5),
 "editor score field": lambda p: p.update(score=8),
 "read_level A not enabled": lambda p: p.update(read_level="A"),
 "experience claim in body": lambda p: p["sections"][0]["p"].append("저는 이 작품을 끝까지 봤어요."),
 "star rating": lambda p: p.update(verdict=p["verdict"] + " ★★★★☆"),
 "score number": lambda p: p.update(verdict=p["verdict"] + " 4/5"),
 "promo superlative": lambda p: p.update(summary=p["summary"] + " 인생작이에요"),
 "long quote": lambda p: p["opinions"][0].update(gist=p["opinions"][0]["gist"] + " “번역은 충실함에 정확히 부합하는 것이라는 주장이다”"),
 "copied source sentence": lambda p: p["opinions"][0].update(gist="문자 그대로 옮긴 번역 같은 것이 존재할 수 없기 때문에 창조적이지 않은 번역이란 있을 수 없다 라는 설명이에요."),
 "unknown citation id": lambda p: p["opinions"][0].update(cite=["s9"]),
 "opinion without citation": lambda p: p["opinions"][0].update(cite=[]),
 "no sources at all": lambda p: p.update(sources=[], sections=[], opinions=[], metrics=None, pre_release=True, no_reaction_notice="x"),
 "source without URL": lambda p: p["sources"][0].update(url=""),
 "source without date field": lambda p: p["sources"][0].pop("date"),
 "source without media/outlet": lambda p: p["sources"][0].update(outlet=""),
 "persona banned phrase": lambda p: p.update(verdict=p["verdict"] + " 소름 돋았다"),
 "no critical reaction post-release": lambda p: p.update(opinions=[o for o in p["opinions"] if o["stance"] != "비판"]),
 "no limits section": lambda p: p.update(limits=[]),
 "source on AI-blocking domain (yna)": lambda p: p["sources"][0].update(url="https://www.yna.co.kr/view/AKR20180115055500005"),
 "source on AI-blocking domain (khan, www-less)": lambda p: p["sources"][0].update(url="https://khan.co.kr/article/201312082125015"),
 "source on all-bots-blocked domain (www.kci.go.kr)": lambda p: p["sources"][0].update(url="https://www.kci.go.kr/kciportal/x"),
}
persona_cases = {
 "byline not plain 에디터": lambda p: p.update(badge="AI 에디터"),
 "invented age": lambda p: p.update(tagline="34세 에디터"),
 "invented job": lambda p: p.update(domain="전직 출판사 편집자 출신 에디터"),
 "invented residence/family": lambda p: p.update(lens=p["lens"] + " 서울 거주, 결혼 3년차"),
 "photo field": lambda p: p.update(photo="https://example.com/a.jpg"),
 "bio field": lambda p: p.update(bio="대학 졸업 후 평론 활동"),
 "avatar not an abstract glyph": lambda p: p.update(glyph={"shape": "photo", "color": "#C96442", "url": "x.jpg"}),
 "no disclosed blind spot": lambda p: p.update(blind_spot=""),
}
bad = 0
def expect_refused(name, fn):
    global bad
    try: fn(); print("NOT REFUSED:", name); bad += 1
    except SystemExit as e: print("refused ok:", name, "->", str(e)[:70])
for name, f in post_cases.items(): expect_refused(name, lambda f=f: bs.validate_post(mut(f), personas, works, dnc))
for name, f in persona_cases.items(): expect_refused(name, lambda f=f: bs.check_persona(pmut(f)))
# essay type (편집부 칼럼, 준태님 원고 2026-10-19): synthesis rules do not apply, but AI marks / scores / ratings / promo / unknown persona-work are refused
essay_base = {"slug": "t-essay", "type": "essay", "persona": "cut", "persona_version": personas["cut"]["version"], "work": "pointed-awl",
              "title": "테스트 칼럼", "date": "2026-10-19", "summary": "요약 한 줄.", "framing": "편집부 칼럼", "body": ["첫 단락이다.", "둘째 단락이다."]}
def emut(f):
    p = copy.deepcopy(essay_base); f(p); return p
essay_cases = {
 "essay AI mark": lambda p: p["body"].append("이 글은 AI가 도왔다."),
 "essay 인공지능 mark": lambda p: p.update(summary="인공지능 칼럼"),
 "essay star rating": lambda p: p["body"].append("★☆☆☆☆"),
 "essay star rating with 별점": lambda p: p["body"].append("별점 ★"),
 "essay 평점 number": lambda p: p["body"].append("평점 1"),
 "essay figure AI alt": lambda p: p.update(figures=[{"file": "t-essay-1.webp", "alt": "에곤 실레풍 삽화: AI 그림", "after": 1}]),
 "essay figure alt without style label": lambda p: p.update(figures=[{"file": "t-essay-1.webp", "alt": "그림", "after": 1}]),
 "essay figure foreign file": lambda p: p.update(figures=[{"file": "../x.webp", "alt": "클림트풍 삽화: 여인", "after": 1}]),
 "essay figure after out of body": lambda p: p.update(figures=[{"file": "t-essay-1.webp", "alt": "클림트풍 삽화: 여인", "after": 9}]),
 "essay figure extra key": lambda p: p.update(figures=[{"file": "t-essay-1.webp", "alt": "클림트풍 삽화: 여인", "after": 1, "src": "http://x"}]),
 "essay score number": lambda p: p.update(summary="3/5"),
 "essay rating field": lambda p: p.update(rating=1),
 "essay score field": lambda p: p.update(score=1),
 "essay framing not 편집부 칼럼": lambda p: p.update(framing="공개 자료 정리"),
 "essay missing framing": lambda p: p.pop("framing"),
 "essay unknown persona": lambda p: p.update(persona="nobody"),
 "essay unknown work": lambda p: p.update(work="no-such-work"),
 "essay empty body": lambda p: p.update(body=[]),
 "essay promo superlative": lambda p: p["body"].append("인생작이다."),
 "essay unexpected field": lambda p: p.update(label_text="AI"),
 "essay empty block quote": lambda p: p["body"].append("> "),
 "essay block quotes only": lambda p: p.update(body=["> 인용만 있다."]),
}
for name, f in essay_cases.items(): expect_refused(name, lambda f=f: bs.validate_post(emut(f), personas, works, dnc))
bs.validate_post(essay_base, personas, works, dnc); print("baseline essay passes")
bs.validate_post(emut(lambda p: p["body"].append("별점 1점조차 아까운 작품이다.")), personas, works, dnc); print("essay rhetoric '별점' word accepted (no star/score)")
bs.validate_post(emut(lambda p: p.update(figures=[{"file": "t-essay-1.webp", "alt": "에곤 실레풍 삽화: 정원의 식물", "after": 1}])), personas, works, dnc); print("essay figure accepted")
bs.validate_post(emut(lambda p: p["body"].insert(1, "> " + "가" * 200)), personas, works, dnc); print("essay long block quote accepted (critical quotation, no 12-char limit)")
shipped = json.loads((R / "site/content/posts.json").read_text(encoding="utf-8"))
for p_ in shipped: bs.validate_post(p_, personas, works, dnc)
print("shipped posts pass (%d)" % len(shipped))
# work-level robots guard: a flagged-domain fact that is not on the bare-citation list must be refused; listed ones pass
import copy as _c
wc = json.loads((R / "site/content/works.json").read_text(encoding="utf-8"))
w0 = _c.deepcopy(wc["misaeng"]); w0["facts"].append(["테스트", "x", 3, "https://www.khan.co.kr/article/1", "경향신문"])
expect_refused("work fact on AI-blocking domain not on bare list", lambda: bs.check_work_sources("misaeng", w0))
w1 = _c.deepcopy(wc["misaeng"]); w1["related"] = {"text": "x", "url": "https://www.yna.co.kr/view/1", "label": "연합뉴스"}
expect_refused("related note on AI-blocking domain not on bare list", lambda: bs.check_work_sources("misaeng", w1))
for slug, c in wc.items(): bs.check_work_sources(slug, c)
print("all current work citations pass the robots guard (flagged ones are on the bare-citation list)")
# no post in the shipped content cites a blocked domain
for p_ in posts:
    for s_ in p_["sources"]:
        if bs._bare(s_["url"]) in bs.BLOCKED_HOSTS: print("SHIPPED POST ON BLOCKED DOMAIN", p_["slug"], s_["url"]); bad += 1
print("shipped posts: no AI-blocking source domains")
# built output: no per-post badge, human panel free of editor content, 9 distinct pen names
dist = R / "site/dist"
if dist.exists():
    import re
    txt = {p: p.read_text(encoding="utf-8") for p in dist.rglob("*.html")}
    for p, t in txt.items():
        rel = str(p.relative_to(dist))
        if re.search(r"ai-badge|ailabel|AI 에디터|AI 독자|AI 페르소나", t): print("STALE AI BADGE/LABEL in", rel); bad += 1
        if rel.startswith("posts/") and "보관된 글이에요" not in t and 'class="byline"' not in t: print("post without byline", rel); bad += 1
        m = re.search(r'<div class="panel human">(.*?)</div>', t, re.S)
        if m and re.search(r"/posts/|/personas/|byline", m.group(1)): print("editor content in human panel", rel); bad += 1
        if rel.startswith("posts/") and "보관된 글이에요" not in t and rel.split("/")[1] not in {p_["slug"] for p_ in shipped}: print("unshipped post page in dist", rel); bad += 1
        if 'class="detail post-detail essay"' in t and re.search(r"<p>&gt;", t): print("essay block quote rendered as plain paragraph", rel); bad += 1
        if 'class="detail post-detail essay"' in t and ("공개 자료를 정리" in t or "편집부 칼럼" not in t): print("essay page with synthesis notice / without 편집부 칼럼", rel); bad += 1
    print("built-output checks done (%d pages)" % len(txt))
    for home in (dist / "index.html", dist / "en/index.html"):
        t = txt[home]
        if 'class="kicker"' in t or 'srow-num' in t or '<ol class="rows" role="list">' not in t:
            print("home must use margin headings and an ordered review list", home); bad += 1
        if not re.search(r'<h2 class="margin-heading" id="today-heading">[^<]+</h2>', t):
            print("home missing the lead section heading", home); bad += 1
        if not re.search(r'class="cta cta-main"[^>]*>[^<]+<span aria-hidden="true">→</span>', t):
            print("held CTA arrow missing", home); bad += 1
    # A mockup-only font subset silently loses essay Hangul and Hanja. Verify
    # both body weights cover every CJK character in the complete generated site.
    from fontTools.ttLib import TTFont
    visible = bs.html.unescape("".join(txt.values()))
    required = {ord(c) for c in visible if '\u3400' <= c <= '\u9fff' or '\uac00' <= c <= '\ud7a3'}
    for weight in (400, 700):
        with TTFont(dist / f"assets/fonts/NotoSerifKR-{weight}-subset.woff2") as font:
            missing = required - set(font.getBestCmap())
        if missing: print("body font missing CJK glyphs", weight, sorted(missing)); bad += 1
    print("full-site font coverage checked")
bs.validate_post(base, personas, works, dnc); print("baseline post passes")
for p in personas.values(): bs.check_persona(p)
print("all 9 pen names pass persona guard")
sys.exit(1 if bad else 0)
