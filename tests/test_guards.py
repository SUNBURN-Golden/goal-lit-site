#!/usr/bin/env python3
"""Negative tests: each mutation MUST make the build guard refuse it. Run: python3 tests/test_guards.py
Design: pen-name 에디터 bylines, no per-post AI badge/label; one short AI-assistance note on /principles/."""
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
 "avatar not an abstract glyph": lambda p: p.update(glyph={"shape": "photo", "color": "#A78BFA", "url": "x.jpg"}),
 "no disclosed blind spot": lambda p: p.update(blind_spot=""),
}
bad = 0
def expect_refused(name, fn):
    global bad
    try: fn(); print("NOT REFUSED:", name); bad += 1
    except SystemExit as e: print("refused ok:", name, "->", str(e)[:70])
for name, f in post_cases.items(): expect_refused(name, lambda f=f: bs.validate_post(mut(f), personas, works, dnc))
for name, f in persona_cases.items(): expect_refused(name, lambda f=f: bs.check_persona(pmut(f)))
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
# site-level checks
good_note = '<p class="muted fine">에디터 글은 필명 에디터의 이름으로, AI의 도움을 받아 작성돼요.</p>'
for name, html in {"principles page without AI note": "<p>원칙</p>",
                   "AI note too long / banner": '<p class="muted fine">' + "에디터 필명 AI의 도움을 받아 " * 20 + "</p>",
                   "AI note not mentioning pen name": '<p class="muted fine">AI의 도움을 받아 작성돼요.</p>'}.items():
    if bs.check_principles(html): print("refused ok:", name)
    else: print("NOT REFUSED:", name); bad += 1
if bs.check_principles(good_note): print("NOT ACCEPTED: valid principles note"); bad += 1
else: print("valid principles note passes")
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
    print("built-output checks done (%d pages)" % len(txt))
bs.validate_post(base, personas, works, dnc); print("baseline post passes")
for p in personas.values(): bs.check_persona(p)
print("all 9 pen names pass persona guard")
sys.exit(1 if bad else 0)
