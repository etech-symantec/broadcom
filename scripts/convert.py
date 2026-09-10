#!/usr/bin/env python3
"""
xlsx -> json 변환 스크립트
data/ 폴더 안의 xlsx 파일을 찾아서 docs/data.json 으로 저장한다.
파일 이름은 무관하며, 여러 개일 경우 가장 최근에 수정된 파일을 사용한다.
Tabulator.js 가 바로 소비할 수 있는 형태(레코드 배열)로 출력한다.
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.parse import urlparse

import openpyxl

DATA_DIR = Path("data")
DST = Path("docs/data.json")

# ---------------------------------------------------------------------------
# status.broadcom.com 모아보기 설정
# ---------------------------------------------------------------------------
STATUS_DST = Path("docs/status.json")
STATUS_API_BASE = "https://status.broadcom.com/api/v1/components"
STATUS_PAGE_BASE = "https://status.broadcom.com/services"

# 모아볼 서비스 목록 (slug 는 status.broadcom.com/services/<slug> 의 마지막 경로)
BROADCOM_STATUS_SERVICES = [
    {"slug": "cloud-secure-web-gateway", "name": "Cloud Secure Web Gateway"},
    {"slug": "cloudsoc-casb", "name": "CloudSOC CASB"},
    {"slug": "dlp-cloud", "name": "DLP Cloud"},
    {"slug": "edge-secure-web-gateway", "name": "Edge Secure Web Gateway"},
    {"slug": "intelligence-services-webfilter", "name": "Intelligence Services / WebFilter"},
    {"slug": "symantec-ztna", "name": "Symantec ZTNA"},
    {"slug": "web-isolation", "name": "Web Isolation"},
]

# status.broadcom.com API 의 state 값 -> 화면 표시용 라벨/CSS 매핑
STATUS_STATE_LABELS = {
    "operational": {"label": "정상", "css": "up"},
    "degraded": {"label": "장애 발생", "css": "down"},
    "under-maintenance": {"label": "점검 중", "css": "warn"},
}


def find_xlsx():
    """data/ 폴더에서 xlsx 파일을 찾아 반환. 여러 개면 가장 최근 수정본을 선택."""
    files = list(DATA_DIR.glob("*.xlsx"))
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime)


def normalize(value):
    """엑셀 셀 값을 JSON-safe 값으로 변환"""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _http_get_json(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; broadcom-status-checker/1.0)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _slug_from_service_url(url):
    """component['url'] (예: https://status.broadcom.com/services/dlp-cloud) 에서 slug만 추출.
    최상위(top-level) 컴포넌트만 url 값을 가지므로, 이 값이 있으면 그 자체로 매칭 키가 된다."""
    if not url:
        return None
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "services":
        return parts[1]
    return None


def fetch_broadcom_status():
    """status.broadcom.com 에서 BROADCOM_STATUS_SERVICES 에 정의된 서비스들의
    현재 상태(state)를 모아서 반환한다. 네트워크 실패 등은 여기서 흡수하고
    실패한 서비스는 state='unknown' 으로 표시한다 (전체 빌드를 막지 않기 위함)."""
    target_slugs = {s["slug"] for s in BROADCOM_STATUS_SERVICES}
    found = {}

    # 1) 가능하면 top-level 컴포넌트만 필터링해서 빠르게 조회
    try:
        payload = _http_get_json(f"{STATUS_API_BASE}?filter[parent_id_null]=true&per_page=100")
        for comp in payload.get("components", []):
            slug = _slug_from_service_url(comp.get("url"))
            if slug in target_slugs and slug not in found:
                found[slug] = comp
    except Exception as e:
        print(f"  -> [경고] status.broadcom.com top-level 컴포넌트 조회 실패: {e}")

    # 2) 필터가 무시되었거나 일부를 못 찾았으면, 전체 컴포넌트를 페이지네이션하며 보강 탐색
    #    (컴포넌트 목록은 부모 -> 자식 순서로 나열되므로 최상위 항목은 앞쪽에 몰려있지 않을 수 있다)
    missing = target_slugs - found.keys()
    page = 1
    max_pages = 40  # 안전장치: 전체 컴포넌트 수가 매우 많아도 무한 루프에 빠지지 않도록 제한
    while missing and page <= max_pages:
        try:
            payload = _http_get_json(f"{STATUS_API_BASE}?page={page}")
        except Exception as e:
            print(f"  -> [경고] status.broadcom.com 컴포넌트 목록(page={page}) 조회 실패: {e}")
            break

        comps = payload.get("components", [])
        if not comps:
            break

        for comp in comps:
            slug = _slug_from_service_url(comp.get("url"))
            if slug in target_slugs and slug not in found:
                found[slug] = comp

        missing = target_slugs - found.keys()
        if not missing or not payload.get("meta", {}).get("next_page"):
            break
        page += 1

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    services = []
    for meta in BROADCOM_STATUS_SERVICES:
        slug = meta["slug"]
        comp = found.get(slug)
        state = comp.get("state") if comp else None
        label_info = STATUS_STATE_LABELS.get(state, {"label": "확인 필요", "css": "unknown"})
        services.append({
            "name": meta["name"],
            "slug": slug,
            "url": (comp.get("url") if comp else None) or f"{STATUS_PAGE_BASE}/{slug}",
            "state": state or "unknown",
            "state_label": label_info["label"],
            "state_css": label_info["css"],
            "component_updated_at": comp.get("updated_at") if comp else None,
        })

    return {"checked_at": checked_at, "services": services}


def _load_existing_status():
    """git 체크아웃에 이미 있는 이전 status.json을 읽어온다 (없으면 None)."""
    if not STATUS_DST.exists():
        return None
    try:
        return json.loads(STATUS_DST.read_text(encoding="utf-8"))
    except Exception:
        return None


def _same_states(old_services, new_services):
    """slug+state 조합만 비교한다. component_updated_at 등 부가 정보는 무시."""
    def key(services):
        return sorted((s.get("slug"), s.get("state")) for s in services or [])
    return key(old_services) == key(new_services)


def update_broadcom_status():
    """status.broadcom.com 모아보기 결과를 docs/status.json 에 기록한다.
    이 단계가 실패하더라도 xlsx -> data.json 변환(메인 파이프라인)은 계속 진행되어야 한다.

    실제 서비스 상태(state)가 이전 저장 내용과 동일하면 파일을 다시 쓰지 않는다.
    (그래야 스케줄러가 자주 돌아도 checked_at 만 바뀌는 불필요한 git commit이 쌓이지 않는다)
    """
    print("status.broadcom.com 서비스 상태 조회 중...")
    try:
        payload = fetch_broadcom_status()
    except Exception as e:
        print(f"  -> [에러] status.broadcom.com 상태 조회 전체 실패: {e}")
        return

    prev = _load_existing_status()
    if prev is not None and _same_states(prev.get("services"), payload["services"]):
        print("  -> 상태 변화 없음: status.json 재작성을 생략합니다 (불필요한 커밋 방지).")
        for svc in payload["services"]:
            print(f"  - {svc['name']}: {svc['state_label']} ({svc['state']})")
        return

    STATUS_DST.parent.mkdir(parents=True, exist_ok=True)
    STATUS_DST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for svc in payload["services"]:
        print(f"  - {svc['name']}: {svc['state_label']} ({svc['state']})")
    print(f"OK: {len(payload['services'])}개 서비스 상태를 {STATUS_DST} 로 저장했습니다.\n")


def main():
    # status.broadcom.com 모아보기는 xlsx 변환과 독립적으로 먼저 실행한다.
    update_broadcom_status()

    src = find_xlsx()
    if src is None:
        print(f"ERROR: {DATA_DIR}/ 폴더에 xlsx 파일이 없습니다.", file=sys.stderr)
        sys.exit(1)
    print(f"대상 파일: {src}")

    wb = openpyxl.load_workbook(src, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        print("ERROR: 시트가 비어 있습니다.", file=sys.stderr)
        sys.exit(1)

    header = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(rows[0])]

    records = []
    for row in rows[1:]:
        # 완전히 빈 행은 건너뜀
        if all(cell is None for cell in row):
            continue
        record = {}
        for key, value in zip(header, row):
            record[key] = normalize(value)
        records.append(record)

    # xlsx 실제 내용(columns/records)이 이전 data.json과 동일하면 generated_at도 갱신하지 않는다.
    # (schedule cron으로 매번 돌아도, 실제로 xlsx가 바뀌지 않았으면 불필요한 git diff/commit이 생기지 않도록)
    prev = None
    if DST.exists():
        try:
            prev = json.loads(DST.read_text(encoding="utf-8"))
        except Exception:
            prev = None

    if prev is not None and prev.get("columns") == header and prev.get("records") == records:
        print(f"OK: xlsx 내용 변화 없음. {DST} 재작성을 생략합니다 (불필요한 커밋 방지).")
        return

    DST.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "columns": header,
        "row_count": len(records),
        "records": records,
    }
    DST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {len(records)}개 행을 {DST} 로 변환했습니다.")


if __name__ == "__main__":
    main()
