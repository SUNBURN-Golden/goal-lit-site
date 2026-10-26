"""Check built pages without starting a server; all browser requests stay local."""
import argparse, json, mimetypes
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "site/dist"
ap = argparse.ArgumentParser()
ap.add_argument("--screenshots", type=Path)
args = ap.parse_args()
if args.screenshots:
    args.screenshots.mkdir(parents=True, exist_ok=True)

def local_route(route):
    path = unquote(urlparse(route.request.url).path)
    file = DIST / path.lstrip("/")
    if file.is_dir(): file /= "index.html"
    if file.is_file():
        route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")
    else: route.fulfill(status=404, body="missing")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for scheme in ("light", "dark"):
        for width, height in ((320,700),(390,844),(768,900),(840,900),(1024,768),(1440,900),(1920,1080)):
            page = browser.new_page(viewport={"width":width,"height":height}, color_scheme=scheme)
            page.route("**/*", local_route)
            for path in ("/", "/en/"):
                page.goto("http://goal-lit.test" + path)
                page.evaluate("document.fonts.ready")
                page.locator("img").evaluate_all("""async images => {
                    for (const img of images) img.loading = 'eager';
                    await Promise.all(images.map(img => img.decode()));
                }""")
                result = page.evaluate("""() => {
                    const style = x => getComputedStyle(x);
                    const rect = x => x.getBoundingClientRect();
                    const small = [...document.querySelectorAll('.nav a,.brand,.cta,.story-list-head a,.srow h3 a,.flinks a')].filter(x => rect(x).width < 43.9 || rect(x).height < 43.9).map(x=>x.textContent.trim());
                    return {width:innerWidth, overflow:document.documentElement.scrollWidth > innerWidth, small,
                        band:style(document.body).borderTopWidth, bg:style(document.body).backgroundColor,
                        font:style(document.querySelector('h1')).fontFamily,
                        rows:document.querySelectorAll('ol.rows > li.srow').length,
                        navOverlap: rect(document.querySelector('.brand')).right > rect(document.querySelector('.nav a')).left + 12 && Math.abs(rect(document.querySelector('.brand')).top - rect(document.querySelector('.nav a')).top) < 20,
                        arrow:document.querySelector('.cta').textContent.includes('→')};
                }""")
                assert not result["overflow"], (scheme,path,result)
                assert not result["small"], (scheme,path,result)
                assert not result["navOverlap"], (scheme,path,result)
                assert result["band"] == "4px" and result["arrow"], result
                assert result["rows"] and "Hahmlet" in result["font"], result
                lead_alt = page.locator(".lead-img img").get_attribute("alt")
                assert lead_alt and page.get_by_role("img", name=lead_alt, exact=True).count() == 1, path
                if args.screenshots and path == "/" and width in (390,1440):
                    page.screenshot(path=str(args.screenshots / f"home-{width}-{scheme}.png"), full_page=True)
                print(scheme,width,path,"PASS")
            page.close()
    essays = [post for post in json.loads((ROOT / "site/content/posts.json").read_text(encoding="utf-8"))
              if post.get("type") == "essay"]
    longest_essay = max(essays, key=lambda post: sum(len(paragraph) for paragraph in post["body"]))
    essay_url = f"http://goal-lit.test/posts/{longest_essay['slug']}/"
    # The longest shipped essay: inspect real line geometry, including Korean
    # keep-all words, rather than merely checking the stylesheet declarations.
    for scheme in ("light", "dark"):
        for width in (390,480,600,640,641,1440):
            page = browser.new_page(viewport={"width":width,"height":900}, color_scheme=scheme)
            page.route("**/*", local_route)
            response = page.goto(essay_url)
            assert response and response.ok, essay_url
            assert page.locator(".essay-body p").count(), essay_url
            page.evaluate("document.fonts.ready")
            page.locator("img").evaluate_all("""async images => {
                for (const img of images) img.loading = 'eager';
                await Promise.all(images.map(img => img.decode()));
            }""")
            reading = page.evaluate(r"""() => {
                const paragraphs = [...document.querySelectorAll('.essay-body p')];
                let largestGap = 0;
                for (const p of paragraphs) {
                    const node = p.firstChild;
                    if (!node || node.nodeType !== Node.TEXT_NODE) continue;
                    let previous;
                    for (const word of node.textContent.matchAll(/\S+/g)) {
                        const range = document.createRange();
                        range.setStart(node, word.index);
                        range.setEnd(node, word.index + word[0].length);
                        const rects = [...range.getClientRects()];
                        const first = rects[0], last = rects.at(-1);
                        if (previous && first && Math.abs(first.top - previous.top) < 1)
                            largestGap = Math.max(largestGap, first.left - previous.right);
                        previous = last;
                    }
                }
                const first = paragraphs[0], css = getComputedStyle(first);
                return {overflow:document.documentElement.scrollWidth > innerWidth,
                    measure:first.getBoundingClientRect().width, largestGap,
                    align:css.textAlign, last:css.textAlignLast, font:css.fontFamily,
                    size:css.fontSize, line:css.lineHeight, break:css.wordBreak};
            }""")
            assert not reading["overflow"], reading
            assert reading["measure"] <= 612.1 and reading["largestGap"] < 36, reading
            assert reading["align"] == ("start" if width <= 640 else "justify"), reading
            assert reading["size"] == "18px" and reading["break"] == "keep-all", reading
            assert abs(float(reading["line"].removesuffix("px")) - 34.2) < .1, reading
            if args.screenshots:
                page.locator('.essay-body > p').first.screenshot(path=str(args.screenshots / f"essay-{width}-{scheme}.png"))
            assert page.locator('.read-progress').count() == 0
            page.emulate_media(reduced_motion="no-preference")
            assert page.evaluate("getComputedStyle(document.documentElement).scrollBehavior") == "smooth"
            page.emulate_media(reduced_motion="reduce")
            assert page.evaluate("getComputedStyle(document.documentElement).scrollBehavior") == "auto"
            page.goto("http://goal-lit.test/")
            assert page.locator('.lead-img img').evaluate("x => getComputedStyle(x).transitionDuration") == "0s"
            page.locator('.skip').focus()
            focus = page.locator('.skip').evaluate("x => ({x:x.getBoundingClientRect().left, outline:getComputedStyle(x).outlineStyle})")
            assert focus["x"] >= 0 and focus["outline"] == "solid", focus
            print(scheme,width,"essay, reduced motion and focus PASS",reading)
            page.close()
    browser.close()
