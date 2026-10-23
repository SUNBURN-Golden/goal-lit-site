#!/usr/bin/env python3
"""꼴릿(Goal Lit) 수집함 5단계 상태 집계 및 완료 기준 리포트 출력기 (report_status.py).

첫 버전 완료 기준:
브랜드(goal-lit)별로 ① 후보(discovered), ② 원문 확인(source_checked), ③ 중복 제외(deduped),
④ 검증 완료(verified_ready — 조사자료 묶음 vs 독창 평론 준비 묶음 구분),
⑤ 공개 대기(publish_pending — 사이트 자동 게시 미연결) 건수를 구분해 출력한다.
"""
import argparse
import json
from politeness import PolitenessManager
from storage import CollectorStorage


def main() -> int:
    ap = argparse.ArgumentParser(description="Goal Lit 5-stage collector status reporter")
    ap.add_argument("--json", action="store_true", help="JSON 형식으로만 출력")
    args = ap.parse_args()

    storage = CollectorStorage()
    politeness = PolitenessManager(storage.db_path)
    summary = storage.get_status_summary()
    summary["daily_politeness"] = politeness.get_daily_counts()

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    sc = summary["stage_counts"]
    vb = summary["verified_bundle_breakdown"]
    al = summary["source_access_level_breakdown"]
    uc = summary["unverified_3category_breakdown"]
    dp = summary["daily_politeness"]

    print("======================================================================")
    print(f" [Goal Lit (꼴릿) 수집기 5단계 상태 리포트] ({summary['generated_at_kst']})")
    print("======================================================================")
    print(f" • 전체 레코드 수         : {summary['total_records']}건 (고유 중복묶음 클러스터: {summary['unique_clusters']}개)")
    print(f" • 사이트 자동 게시 연결  : {summary['auto_publish_connected']} (에디터 승인 전 자동 배포 차단)")
    print("----------------------------------------------------------------------")
    print(" [1] 5단계 파이프라인 집계 (첫 버전 완료 기준)")
    print(f"   1) 발견 후보 (discovered)       : {sc['discovered']:4d} 건 (비공식/블로그 단서 및 미확인 서지·발언·해석)")
    print(f"   2) 원문 확인 (source_checked)   : {sc['source_checked']:4d} 건 (언론 보도·충돌 대조 원문 확인)")
    print(f"   3) 중복 제외 (deduped)          : {sc['deduped']:4d} 건 (동일 URL·동일 보도자료·논문 중복 클러스터)")
    print(f"   4) 검증 완료 (verified_ready)   : {sc['verified_ready']:4d} 건")
    print(f"      ├─ 조사자료 묶음 (research_bundle)       : {vb['research_bundle']:4d} 건")
    print(f"      └─ 독창 평론 준비 묶음 (critique_ready)  : {vb['critique_ready_bundle']:4d} 건")
    print(f"   5) 공개 대기 (publish_pending)  : {sc['publish_pending']:4d} 건 (사이트 반영 대기, 자동 게시 분리)")
    print("----------------------------------------------------------------------")
    print(" [2] 꼴릿 전용 원문 접근 수준(source_access_level) 5종 분리")
    print(f"   • 작품 소개/공식 서지 (book_intro)     : {al['book_intro']:4d} 건")
    print(f"   • 학술 논문 초록 (paper_abstract)      : {al['paper_abstract']:4d} 건")
    print(f"   • 실제 독서/강독 기록 (full_text_read) : {al['full_text_read']:4d} 건")
    print(f"   • 언론 기사 보도 (press_article)       : {al['press_article']:4d} 건")
    print(f"   • 작가 인터뷰/소감 (author_interview)  : {al['author_interview']:4d} 건")
    print("----------------------------------------------------------------------")
    print(" [3] 미확인(unverified) 항목 3분류 및 출처 충돌 보존 현황")
    print(f"   • 서지 미확인 단서                     : {uc['서지']:4d} 건")
    print(f"   • 발언 미확인 단서                     : {uc['발언']:4d} 건")
    print(f"   • 작품 해석 미확인 단서                : {uc['작품 해석']:4d} 건")
    print(f"   • 출처 간 주장 충돌 보존 (conflict=1)  : {summary['conflict_records_count']:4d} 건")
    print("----------------------------------------------------------------------")
    print(" [4] 금일 폭주 방지 예산 소진 현황 (Politeness & Rate Limits)")
    print(f"   • 일일 신규 발견 (상한 500건)          : {dp['discovered_count']:4d} / 500 건")
    print(f"   • 일일 본문 수집 (상한 200건)          : {dp['fetched_count']:4d} / 200 건")
    print("======================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
