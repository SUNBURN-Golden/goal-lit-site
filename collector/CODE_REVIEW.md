# Goal Lit (꼴릿) 수집기 코드 리뷰 보고서 (`CODE_REVIEW.md`)

- **리뷰 일시**: 2026-10-23 10:33 KST
- **대상 경로**: `/workspace/lit-hub/collector/`
- **최종 판정**: **VERDICT: APPROVE**

## 1. 7대 요구사항 및 설계 감리(`DESIGN_REVIEW.md`) 조건 반영 검증

| 항목 | 구현 파일 | 검증 결과 |
|---|---|---|
| 1. 3개 수집 경로 + 로컬 작업기 분리 | `auto_collector.py`, `browser_collector.py`, `chrome-extension/*`, `local_worker.py` | **통과**: 자동 수집(OpenAlex API·정적 HTML·링크 추적)·브라우저 수집(`APPROVED_JS_DOMAINS`에 한함)·수동 클립(`activeTab`+`scripting` → `127.0.0.1:8795/api/clip`)이 모두 `CollectorStorage.upsert_item()` 단일 검증 게이트를 통과함. |
| 2. 비공식 출처 후보 수용·상태 분리·충돌 보존 | `storage.py`, `migrate_existing.py` | **통과**: 블로그/미확인 단서는 `discovered`(115건)로 수용하되 공식 사실(`verified_ready`)로 표시하지 않음. 출처 충돌(`the-last-witness` 1974 vs 1979 등 6건)은 양쪽 레코드 모두 보존(`conflict=1`, `conflict_with_id` 상호 참조)하고 미해결 충돌의 `publish_pending` 자동 승격을 차단함. |
| 3. 저장 전 PII 필터 & 프롬프트 인젝션 방어 | `pii_filter.py`, `chrome-extension/service_worker.js` | **통과**: 전화번호·이메일·주민번호·주거주소·계좌/카드·아동/건강식별자·쿠키/JWT 토큰·`input`/`textarea`·DM을 저장 전 제거하고, `"이 명령을 실행하라"` / `"Ignore previous instructions"` 명령문을 `[UNTRUSTED_COMMAND_STRING_ISOLATED]`로 무력화함(`test_1`, `test_2` 통과). |
| 4. 꼴릿 전용 6대 필드 & 5종 접근 수준 분리 | `storage.py`, `auto_collector.py`, `migrate_existing.py` | **통과**: `work`, `edition`, `author_statement`, `critical_thesis`, `counter_argument`, `source_access_level` 6대 필드를 완비하고, 기존 `works.json` `tier3` 95건에 혼재되어 있던 학술 논문 초록(`paper_abstract` 72건)을 언론 기사(`press_article` 43건)·작품 소개(`book_intro` 111건)·실제 독서 기록(`full_text_read` 3건)·인터뷰(`author_interview` 2건)와 완전 분리함. 미확인 114건도 `서지`(104)·`발언`(2)·`작품 해석`(11)으로 전수 분류 완료. |
| 5. 다계층 중복 묶음 (`dedup.py`) | `dedup.py`, `storage.py` | **통과**: 정규화 URL(`utm_*`/`fbclid` 제거), 표준 식별자(DOI/OpenAlex/KCI/ISBN), 동일 보도자료 시그니처(`press_wire:booker_*`), 판본 옵션을 묶어 231개 레코드를 126개 고유 클러스터로 정리하고 파생 중복 25건을 `deduped`로 분리함(`test_3` 통과). |
| 6. 초기 폭주 방지 설정값 (500/200/1/5초/깊이2) | `config.py`, `politeness.py` | **통과**: 일일 신규 후보 `500`개, 본문 수집 `200`개, 동일 도메인 동시 요청 `1`개(`fcntl.flock`), 최소 간격 `5.0`초, 링크 깊이 `2`단계, `429`/`503` 백오프 및 네이버 블로그·예약·웹툰 회차 뷰어 차단을 강제함(`test_4` 통과). |
| 7. Chrome MV3 권한·큐 재개·5단계 집계·자동게시 분리 | `chrome-extension/manifest.json`, `report_status.py` | **통과**: `activeTab`, `scripting`, `storage`, `alarms`만 사용(`<all_urls>` 미사용), `chrome.storage.local`의 `resumeCursor`와 SQLite `crawl_queue`로 중단 지점 재개 지원, `AUTO_PUBLISH_TO_SITE = False`로 사이트 자동 게시 완전 분리(`test_6` 통과). |

## 2. 단위 테스트 및 실수집 데몬 검증 결과
- `python3 /workspace/lit-hub/collector/tests/test_collector.py`: **6/6 테스트 전부 OK (0.061s)**
- 데몬 가동 상태:
  - `local_worker.py` (`http://127.0.0.1:8795`): **RUNNING**
  - `auto_loop` 상태/큐 워커: **RUNNING**
- 5단계 실시간 집계:
  - `discovered`: **115건**
  - `source_checked`: **28건**
  - `deduped`: **25건**
  - `verified_ready`: **60건** (조사자료 묶음 `57건`, 독창 평론 준비 묶음 `6건` [검증 완료 3 + 공개 대기 3])
  - `publish_pending`: **3건**

VERDICT: APPROVE
