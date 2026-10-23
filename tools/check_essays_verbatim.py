#!/usr/bin/env python3
"""Byte-compare each essay in site/content/posts.json with drafts/essays/<slug>.md (title + body paragraphs; summary must be the first sentence)."""
import json, sys
from pathlib import Path
R = Path(__file__).resolve().parents[1]
bad = 0
for p in json.loads((R / "site/content/posts.json").read_text(encoding="utf-8")):
    if p.get("type") != "essay": continue
    md = (R / f"drafts/essays/{p['slug']}.md").read_bytes()
    rebuilt = ("# " + p["title"] + "\n\n" + "\n\n".join(p["body"])).encode("utf-8")
    ok = rebuilt.strip() == md.strip()
    s_ok = p["body"][0].startswith(p["summary"])
    print(f"{p['slug']}: body+title {'IDENTICAL' if ok else 'DIFFERENT'} ({len(rebuilt.strip())}/{len(md.strip())} bytes), summary {'is first-sentence prefix' if s_ok else 'NOT a verbatim prefix'}")
    if not ok:
        a, b = rebuilt.strip(), md.strip(); i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
        print("  first diff at byte", i, a[max(0,i-30):i+30].decode('utf-8','replace'), '|', b[max(0,i-30):i+30].decode('utf-8','replace'))
    bad += (not ok) + (not s_ok)
sys.exit(1 if bad else 0)
