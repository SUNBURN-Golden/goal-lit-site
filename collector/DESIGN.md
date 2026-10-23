# Goal Lit (꼴릿) 수집기 데몬 & 로컬 작업기 아키텍처 설계서 (`DESIGN.md`)

- **작성일**: 2026-10-23 (KST)
- **브랜드**: `goal-lit` (꼴릿 — 한국 문학·웹소설·웹툰 비평 및 검증 아카이브)
- **설계 원칙**: **"넓게 수집하고, 근거 수준을 나눠 저장하고, 공개할 때 엄격하게 거르는 봇"**
  - 공식 자료가 아니라는 이유로 발견(`discovered`) 단계부터 버리지 않음.
  - 단, ‘발견했다(`discovered`)’와 ‘원문 사실을 확인했다(`source_checked` / `verified_ready`)’는 엄격히 다른 상태로 저장.
  - 서로 다른 출처의 주장이 충돌하면 둘 다 보존하고 `conflict = 1` 및 `conflict_note`를 기록.
  - 개인정보(PII) 필터와 프롬프트 인젝션 무력화(`sanitize_untrusted_text`)는 로컬 저장 및 AI 전달 **전에** 적용.
  - 수집은 데몬으로 자동 실행하되, **사이트 라이브 게시(`build_site.py`)는 자동으로 연결하지 않음** (`publish_pending` 상태에서 에디터 승인 대기).

---

## 1. 시스템 컴포넌트 및 3개 수집 경로 분리 아키텍처

브라우저나 확장프로그램 하나에 모든 작업을 몰아넣지 않고, **자료 읽기 계층(3개 수집 경로)**과 **대기열·중복 제거·PII 필터·정규화·검증을 담당하는 로컬 작업기(`local_worker.py` + `storage.py`)**로 분리한다.

### 1.1 경로 A — 자동 수집기 (`auto_collector.py`)
- **수집 대상**:
  1. 공개 서지·학술·기관 오픈 API 및 메타데이터:
     - 국립중앙도서관 ISBN 서지 검색 (`nl.go.kr`)
     - OpenAlex / Crossref / KCI 학술 논문 공개 초록 메타데이터 (`api.openalex.org`, `api.crossref.org`, `journal.kci.go.kr`)
     - LTI Korea (한국문학번역원 디지털도서관 공개 서지) / The Booker Prizes 공개 아카이브 (`thebookerprizes.com`)
  2. 허용된 언론·문예지 RSS·사이트맵·목록 페이지 (`magazine.changbi.com`, `sisain.co.kr`, `pressian.com`, `segye.com`, `seoul.co.kr`, `etoday.co.kr`, `enewstoday.co.kr`, `newspim.com`, `thecolumnist.kr`, `thescoop.co.kr`, `bosik.kr`, `artinsight.co.kr` 등)
  3. 본문 내 관련 링크 추적: 최대 깊이 `MAX_LINK_DEPTH = 2`까지만 추적하며, 달력·검색 조합·무한 페이지네이션 URL 패턴은 정규식으로 사전 차단.
- **변동성 우선순위**:
  - 신간 출간일, 문학상 수상 결과, 절판/개정판, 연재 완결 여부 등 변동성이 높은 항목(`priority >= 80`)을 신규 탐색(`priority = 50`)보다 먼저 재확인.

### 1.2 경로 B — 브라우저 수집기 (`browser_collector.py`)
- **수집 대상**: 자바스크립트 렌더링이 필요한 공개 페이지 중 `robots.txt` 및 접근 정책상 허용된 승인 도메인 목록(`APPROVED_JS_DOMAINS`: `thebookerprizes.com`, `magazine.changbi.com`, `page.kakao.com`, `novel.munpia.com`, `series.naver.com`[공개 작품 표지 경로에 한함], `comic.naver.com`[`/webtoon/list` 공개 표지 1페이지에 한함])에 한하여 동작.
- **동작 방식**:
  - 승인 도메인 여부 + `robots.txt` 허용 여부를 먼저 검증(`politeness.py`).
  - 필요한 영역(`article`, `main`, `.book-info`, `.work-summary`, 메타태그 등)만 선택적으로 추출하고, 로그인 쿠키·토큰·입력창(`input`, `textarea`)·댓글·개인 프로필 영역은 DOM 추출 단계에서 즉시 제거.
  - 추출 직후 `pii_filter.py`를 통과시켜 정제된 구조화 필드만 `storage.py`에 저장.

### 1.3 경로 C — 수동 보충 (`chrome-extension/` + `local_worker.py`)
- **권한 설계 (`manifest.json`, Manifest V3)**:
  - `permissions`: `["activeTab", "scripting", "storage"]` (상시 모든 탭을 읽는 `<all_urls>` 호스트 권한을 기본 요구하지 않고, 사용자가 현재 보고 있는 페이지에서 ‘이 자료 담기’를 눌렀을 때만 `activeTab` + `scripting`으로 작동).
  - 무인 수집이 필요한 승인 도메인에 한해서만 `optional_host_permissions`로 별도 요청 가능하도록 분리.
- **브라우저 내 1차 추출 & 개인정보 배제 (`popup.js` / `service_worker.js`)**:
  - 페이지 전체 HTML을 서버로 덤프하지 않음.
  - 스크립트가 현재 탭에서 본문 핵심 영역(제목, 저자/매체, 발행일, 선택 텍스트 또는 본문 문단 요약, 서지 메타데이터)만 추출하고, `input`/`textarea`/비밀번호/쿠키/토큰/개인 연락처 패턴을 1차 마스킹한 뒤 로컬 작업기(`http://127.0.0.1:8791/api/clip`)로 전송.
- **서비스워커 수명주기 대응 (Queue & Resume)**:
  - Chrome MV3 서비스워커는 유휴 시 언제든 종료될 수 있으므로(`chrome.storage.local` 활용), 전송 대기 큐(`clipQueue`)와 진행 위치(`cursor`)를 `chrome.storage.local` 및 로컬 작업기 SQLite `crawl_queue` 양쪽에 영속 저장하여 중단 지점부터 즉시 재개.

---

## 2. 저장 전 개인정보(PII) 필터 및 프롬프트 인젝션 방어 (`pii_filter.py`)

페이지 전체를 먼저 저장하고 나중에 지우는 방식을 금지하며, **로컬 DB 저장 및 AI 전달 전에** 반드시 `pii_filter.sanitize_and_filter()`를 거친다.

1. **PII 정규식 + 규칙 기반 마스킹/제거 대상**:
   - 개인 전화번호 (`010-XXXX-XXXX`, `+82-10-...`, 일반 유선번호 패턴)
   - 개인 이메일 주소 (`user@domain.com` — 단, 매체 공식 제보/문의 대표 메일도 기본 마스킹 처리하여 개인 연락처 수집 원천 배제)
   - 주민등록번호 및 외국인등록번호 (`\d{6}-[1-8]\d{6}`)
   - 상세 주거 주소 (도로명·지번의 동·호수·상세번지)
   - 아동 개인정보, 개인 건강·병력·금융(계좌번호·카드번호) 정보
   - 로그인 쿠키·세션 토큰(`Bearer ...`, `eyJ...` JWT, `session_id=`, `csrf_token=`)·비밀번호·폼 입력창 값
   - DM·비공개 메일·회원 전용 대화·개인 SNS 프로필 식별자
2. **허용 대상 (최소 공개 직업 정보)**:
   - 작품 저자명(예: 한강, 최규석, 조남주, 이원하), 번역자명(예: 데버러 스미스, 안톤 허, 김치영), 평론가·기자 기명 등 해당 문학 자료를 설명하는 데 필수적인 공개 직업 정보만 출처(`outlet`, `url`)와 함께 최소한으로 기록.
   - 개인 계정이나 연락처를 추적하는 테이블/컬럼은 일절 생성하지 않음.
3. **프롬프트 인젝션 격리 (`sanitize_untrusted_text`)**:
   - 페이지 안의 `"이 명령을 실행하라"`, `"이전 지시를 무시하라"`, `"Ignore previous instructions"`, `"System prompt:"`, `"<script>"`, `"javascript:"` 등의 문구는 봇에 대한 지시가 아닌 **비신뢰 인용 텍스트**로 취급하며, 인젝션 패턴 감지 시 `prompt_injection_detected = 1` 플래그를 기록하고 명령 구문을 무력화(`[UNTRUSTED_TEXT_ISOLATED]`)하여 저장.

---

## 3. 꼴릿(Goal Lit) 전용 데이터 스키마 및 5단계 상태 모델 (`storage.py`)

### 3.1 5단계 검증·공개 상태 (`validation_status`)
1. `discovered` (**발견 후보**):
   - 검색 결과, 전문 블로그 단서, 보도 요약, 혹은 기존 `works.json`의 미확인(`unverified`) 항목 중 아직 1차 원문으로 확정되지 않은 조사 단서. 공식가로 단정하거나 사실로 게시하지 않음.
2. `source_checked` (**원문 확인**):
   - 출판사 서지, 국립중앙도서관 ISBN, 학술지 초록, 문학상 공식 아카이브, 언론 기사 본문 등 원문 페이지에서 실제 문구와 근거 위치(`evidence_locator`)를 확인한 상태.
3. `deduped` (**중복 제외**):
   - 동일 URL 재수집, 동일 보도자료 재전송 기사, 번역본/판본 옵션 차이 등으로 인해 대표 레코드(`is_cluster_primary = 1`)의 클러스터(`dedup_cluster_id`)에 묶여 집계에서 분리된 상태.
4. `verified_ready` (**검증 완료**):
   - 원문 확인 + 중복 제거 + PII 필터 + 출처 접근 수준(`source_access_level`) 분류가 끝난 항목.
   - 내부적으로 두 가지 번들 유형(`bundle_type`)으로 세분:
     - `research_bundle` (**조사자료 묶음**): 서지·수상·판매·학술 초록·언론 보도 등 객관적 근거 묶음.
     - `critique_ready_bundle` (**독창 평론 준비 묶음**): 작품 서지(`edition`) + 작가 발언(`author_statement`) + 비평 논점(`critical_thesis`) + 반론(`counter_argument`) + 실제 독서/원문 근거(`full_text_read` 또는 다중 검증 근거)가 연결되어 칼럼 집필·검수에 즉시 쓸 수 있는 묶음.
5. `publish_pending` (**공개 대기**):
   - 검증 완료된 자료 또는 칼럼 근거 묶음 중 사이트(`works.json` / `posts.json`) 반영 후보로 준비되었으나, **자동 게시하지 않고 에디터(준태님) 승인을 기다리는 상태**.

### 3.2 꼴릿 전용 6대 핵심 추출 필드
- `work`: 작품 슬러그(`target_work_slug`), 작품 제목(`title`), 저자(`author`), 갈래(`kind`)
- `edition`: 판본 구분(초판/개정판/영역본/단행본), 출판사(`publisher`), 출간일(`pub_date`), 쪽수(`pages`), 정가(`price`), ISBN(`isbn`), 번역자(`translator`)
- `author_statement`: 작가의 실제 발언·인터뷰 인용·수상 소감·작가의 말 (출처 및 발언 일자 포함)
- `critical_thesis`: 작품에 대한 비평적 논점·핵심 테제 (학술 논문 초록의 연구 테제 또는 꼴릿 칼럼의 비평 테제)
- `counter_argument`: 해당 비평 논점에 맞서는 반론·대조 해석·기존 문단/독자층의 통념
- `source_access_level` (**엄격 구분 5종**):
  1. `book_intro`: 출판사 도서 페이지·국립중앙도서관 서지·플랫폼 작품 소개 페이지
  2. `paper_abstract`: KCI·OpenAlex·Crossref·DOI 학술 논문 초록 및 서평 첫머리 (기존 `works.json` `tier3` 95건 중 혼재되어 있던 학술 초록 56건을 `press_article`과 완전 분리!)
  3. `full_text_read`: 실제 작품 원문 강독·직접 독서 기록 및 텍스트 직접 인용 분석
  4. `press_article`: 신문·잡지·온라인 언론 기사 보도
  5. `author_interview`: 작가 직접 인터뷰·간담회·수상 소감 원문

### 3.3 미확인(`unverified`) 114개 항목 3분류 체계
기존 `works.json`의 `unverified` 114개 항목은 버리지 않고 모두 수집함 DB에 마이그레이션하되, 성격에 따라 다음 3가지(`unverified_category`)로 정확히 분류한다:
1. `서지` (출판사, 초판/개정판 정확한 출간 월일, 쪽수, ISBN, 단행본 권수, 연재 회차·기간, 누적 판매 부수, 번역가·해외 출판사 표기 등)
2. `발언` (작가 인터뷰 발언, 연재 중단 경위 관련 작가/편집부 입장, 시상 기관/심사평 1차 발언 등)
3. `작품 해석` (문예지·평론지의 본격 평론, 장르적 위상·정설 논의, 작품 변용·각색 비평 등)

---

## 4. 중복 클러스터링 알고리즘 (`dedup.py`)

URL 문자열 일치만 보지 않고 다음 4단계 계층으로 `dedup_cluster_id`를 산출하여 수집량이 커져도 실제 자료량을 부풀리지 않는다:
1. **정규화 URL 일치 (`canonical_url`)**: `utm_*`, `fbclid`, 불필요한 쿼리 파라미터, `http/https`, 말미 슬래시를 정규화한 URL 해시.
2. **식별자 일치 (`doi` / `isbn` / `openalex_id` / `kci_id`)**: 동일 DOI·ISBN·학술지 논문 ID를 가진 자료 묶음.
3. **동일 기사·보도자료·번역본 클러스터링**:
   - 동일 작품(`target_work_slug`)에 대해 동일 날짜(±3일) 내 핵심 수치·수상명·인용구 토큰 유사도(Jaccard / char n-gram >= 0.65)가 높은 연합뉴스 전재 기사·동일 보도자료 기사를 하나의 `dedup_cluster_id`로 묶음.
   -同一 출처 URL에서 여러 개의 세분화된 사실 행(예: `출간` 행과 `구성` 행이 같은 기사 1건을 인용)이 추출된 경우, 사실(fact) 단위는 모두 보존하되 **원문 자료(source document) 단위 중복 집계**에서는 대표 1건(`is_cluster_primary = 1`)만 고유 원문으로 카운트하고 나머지 파생 행은 `deduped` 클러스터 멤버로 표시.
4. **판본 옵션 묶음**: 동일 작품의 양장본/무선본/전자책 등 단순 판본 옵션 차이는 동일 작품 서지 클러스터로 묶어 관리.

---

## 5. 초기 폭주 방지 설정값 및 레이트리밋 상태머신 (`config.py`, `politeness.py`)

- `MAX_DAILY_DISCOVERED = 500` (브랜드당 하루 신규 후보 URL 발견 상한: 500개)
- `MAX_DAILY_FETCHED = 200` (브랜드당 하루 새 본문 수집 상한: 200개)
- `MAX_CONCURRENT_PER_DOMAIN = 1` (같은 도메인 동시 요청: 1개 — 도메인별 파일/인메모리 락)
- `MIN_DOMAIN_INTERVAL_SEC = 5.0` (요청 간격: 기본 최소 5초, 사이트 `robots.txt`의 `Crawl-delay`가 더 길면 `max(5.0, crawl_delay)` 적용)
- `MAX_LINK_DEPTH = 2` (페이지에서 새 링크를 따라가는 깊이: 최대 2단계)
- **무한 크롤 트랩 차단 정규식 (`TRAP_URL_PATTERNS`)**:
  - 달력(`calendar`, `year=\d{4}&month=\d{2}`), 검색 조합(`?q=.*&sort=.*&filter=`), 무한 페이지네이션(`page=([2-9]\d|\d{3,})`), 로그인/결제/회원 전용 경로(`/login`, `/signin`, `/member`, `/pay`, `/cart`, `/viewer`, `/webtoon/detail`) 즉시 차단.
- **오류·차단 응답 감속·중단**:
  - HTTP `429`, `503`, `403` 또는 접근 제한 응답 수신 시 해당 도메인을 즉시 `backoff_until` 상태로 전환하고 재시도 폭주를 중단.
  - 차단을 피하기 위한 계정 회전, 프록시 우회, User-Agent 위장 기능은 **절대 구현하지 않음** (정직한 `GoalLitCollector/1.0 (+https://goallit.soulbound.co.kr)` 식별자 사용).
