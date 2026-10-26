"""Check built pages without starting a server; all browser requests stay local."""
import argparse, mimetypes
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
                if args.screenshots and path == "/" and width in (390,1440):
                    page.screenshot(path=str(args.screenshots / f"home-{width}-{scheme}.png"), full_page=True)
                print(scheme,width,path,"PASS")
            page.close()
    browser.close()
