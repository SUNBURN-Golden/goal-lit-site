# Goal Lit fonts

2026-10-26: Hahmlet variable (100–900) and Noto Serif KR static 400/700 replace
the unused Pretendard files. The font-family rollout is in PR2.

Sources: Google Fonts `ofl/hahmlet/Hahmlet[wght].ttf` and
`ofl/notoserifkr/NotoSerifKR[wght].ttf`, retrieved 2026-10-26 from
https://github.com/google/fonts/tree/main/ofl . The corresponding prepared
`OFL-Hahmlet.txt` and `OFL-NotoSerifKR.txt` licences are retained here.
`sources/` holds losslessly WOFF2-compressed full fonts; Noto Serif KR was
instanced with fontTools at weights 400 and 700. No glyphs were removed there.

The builder subsets all three sources against the complete rendered Korean and
English pages, including titles, body paragraphs, entities and text attributes,
plus printable ASCII. It writes only subsets and licences to `dist/assets/fonts`.
Hahmlet has no Hanja; headings fall back to Noto Serif KR for those characters.
The mockup-only subsets were insufficient for the full site, so production
subsets are regenerated on every build. No font CDN is used.
