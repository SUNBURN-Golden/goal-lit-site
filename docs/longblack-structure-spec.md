# 롱블랙 구조 실측 스펙 (구조·치수만, 코드·로고·사진·폰트·문구는 가져오지 않음)
측정: 2026-10-20 01:40 KST, Playwright(Chrome) 공개 페이지 longblack.co 홈·노트 1편, 1440x900 / 390x844. 이전 측정(2026-10-19 magazines.md)과 일치 [측정함].

## 홈
| 항목 | 1440 | 390 |
|---|---|---|
| 콘텐츠 폭 | 1200px 중앙 정렬 (x 200–1400) | 좌우 20px 여백 |
| 대표 글(첫 화면) | 3:2 이미지 680x453 왼쪽 + 같은 높이 글 패널 오른쪽 | 이미지 전폭 390x260(3:2) 위, 글 패널 아래 |
| 대표 글 제목 | 30px/42px 700, 첫 화면에서 가장 큰 글자 | 26px/34px 700 |
| 섹션 제목 | 26px/32px 700, 섹션 간 약 600px 간격 | 22px/28px |
| 카드 그리드 A | 3열, 썸네일 4:3 384x288, 간격 24px, 제목 1줄 + 부제 1–2줄 + 메타 | 2열 또는 1열 |
| 카드 그리드 B | 2열 가로형 행, 썸네일 약 180x135 왼쪽 + 제목·부제 오른쪽 | 1열 |
| 첫 화면 링크 | 약 9–12개 [측정 10/19] | |

## 글(노트) 상세
| 항목 | 1440 | 390 |
|---|---|---|
| 머리 폭 | 720px, 위에 4px 진한 선 | 350px |
| 제목 | 40px/54px 700 | 32px/44px 700 |
| 바이라인 | 작은 글씨 한 줄 + 아래 1px 선 | 동일 |
| 본문 | 18px/34.2px(1.9), 폭 580px, 자간 -0.2px, 한 줄 약 49자 | 18px, 폭 310px |
| 배경 | 흰 종이, 글자 #191919 계열 | |

## Goal Lit 적용
- Superseded 2026-10-26 (owner-approved per-site palette; historical rule): 색: 따뜻한 아이보리 배경 #FAF9F5 + 테라코타 강조 하나(장식 #C96442, 글자·버튼 #B85635). 보라·파스텔 박스는 쓰지 않아요.
- Superseded 2026-10-26 (owner-approved font decision; historical rule): 폰트: 시스템 폰트 스택(Pretendard 서브셋 유지). 롱블랙 폰트 파일은 쓰지 않음.
- Current font decision: self-hosted OFL Hahmlet headings with Noto Serif KR fallback, Noto Serif KR 400/700 body. PR1 supplies complete local sources and build-time subsets; PR2 applies the family stacks. Unused Pretendard sources are retired.
- Current palette: light `#F4F5F6` background, `#1A1B1D` text, `#575B61` muted, `#8E1B2C` accent; dark `#161514`, `#E9E7E3`, `#A7A39D`, `#F08A96` respectively. Accent fills CTAs and draws focus rings. Strong rules use text; decorative hairlines use `#C3C8CE` / `#3A3835`. Focus/skip surfaces use `#EAEDF0` / `#201F1D`; editorial layouts have no card fills.
- This per-site background/accent/heading-font decision applies throughout Goal Lit, including its English edition. It supersedes any earlier system-font, light-only, or home-colour-only restriction. Historical measurements above remain a record of the reference site, not the current Goal Lit layout. See [design decisions](design-decisions.md).
