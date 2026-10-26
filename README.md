# goal-lit (작업명 LIT-HUB)
한국 문학·웹툰·웹소설 **평론 웹진**(평론 우선, 영상 각색은 부차). 계획 `PLAN.md` · 필명 에디터 `PERSONAS.md` · 데이터 모델 `DATA_MODEL.md` · 사이트 `site/`(정적 빌드, 공개 페이지는 index,follow).
`archive/adaptation-v1/` = 이전 '영상 각색 트래커' 방향의 작품·글·계획·도구 전량(삭제하지 않고 보관, 사이트와 무관). 자세한 설명은 그 폴더의 README.
공개 홍보·계정·발송 없음. 빌드/테스트 명령은 PLAN.md 맨 아래.

Build prerequisites: Python with `fonttools[woff]` and `brotli`. The separately
maintained `data/`, `personas/`, and `research/` inputs must be available at the
repository root (local read-only links are ignored by Git). Never regenerate
editorial content as part of a design build. Run `python site/build_site.py` and
`python tests/test_guards.py` from this checkout.

Fonts are self-hosted under `site/static/fonts/`; see its README for provenance,
licences, and the build-time subset policy.
