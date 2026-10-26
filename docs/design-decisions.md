# Goal Lit design decisions

## 2026-10-26 — owner-approved literary quarterly direction

The current decision uses a cool paper background, oxblood accent, Hahmlet
headings and Noto Serif KR body text across the site and both editions. Fonts
are self-hosted and subset against every generated page. Both colour schemes,
Korean keep-all wrapping, accessible contrast, 44px controls and reduced motion
remain required. Radii are 0 or 2px; images use 0.

Persona glyphs intentionally share the accent token in both colour schemes.
CSS overrides the nine stored persona colours to keep purple out of the UI;
the underlying persona colour data is preserved.

Superseded: the warm ivory/terracotta and system-font/Pretendard rules in
`longblack-structure-spec.md`, retained there with dated supersession markers.
Earlier light-only or home-colour-only constraints do not apply to this rollout.
There is no root DESIGN.md or DECISIONS file at base `c559f2b`; collector/DESIGN.md
describes the collection system and is outside this visual decision.

Held by owner: the body top 4px accent band and CTA `→` arrows. Keep both and
restyle with the new tokens. Their proposed removals in the approved mockup are
not authorized. Preserve breadcrumb separators too.

Editorial text, facts, author biographies and illustrations are unchanged.
Article art retains its existing colours (including the documented hue
exception); UI tokens and persona glyph styling contain no purple.

## Essay reading

Noto Serif KR is 18px with 1.9 line height and a 34em (612px) maximum measure.
Paragraphs justify with the last line aligned to the start; at 420px and below
all lines align to the start to avoid wide Korean word gaps. Block quote rules
use the text-colour rule token. The old 580px reading width is superseded for
essays only. The reference-site measurements remain historical observations.

The scroll-progress animation is retired so the sole animated interaction is
lead-image opacity. Reduced motion disables that transition. The owner's held
4px body band and CTA arrows remain. Surfaces are reserved for focus/skip UI;
reading panels share the page background.
