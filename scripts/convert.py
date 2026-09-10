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
    "under_maintenance": {"label": "점검 중", "css": "warn"},
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
    최상위(top-level) 컴포넌트만 url 값을 가지므로, 이 값이 있으면 그 자체로 매칭 키가 된다.

    일부 컴포넌트는 /services/<그룹>/<slug> 처럼 경로가 한 단계 더 깊게 내려오는 경우가 있어
    (예: Symantec ZTNA, Web Isolation), 두 번째 조각(parts[1])만 보면 놓칠 수 있다.
    그래서 "services" 다음에 오는 마지막 경로 조각을 slug로 사용한다."""
    if not url:
        return None
    parts = [p for p in urlparse(url).path.split("/") if p]
    if "services" in parts:
        idx = parts.index("services")
        if idx + 1 < len(parts):
            return parts[-1]
    return None


def _name_matches(comp_name, target_name):
    """url 기반 매칭이 실패했을 때를 위한 이름 기반 폴백 (대소문자/양끝 공백 무시)."""
    if not comp_name or not target_name:
        return False
    return comp_name.strip().lower() == target_name.strip().lower()


def fetch_broadcom_status():
    """status.broadcom.com 에서 BROADCOM_STATUS_SERVICES 에 정의된 서비스들의
    현재 상태(state)를 모아서 반환한다.

    Broadcom Status API는 컴포넌트 목록을 한 페이지에 최대 25개까지만 반환하므로,
    per_page=100에 의존하지 않고 페이지를 끝까지 순회한다. 특히 Symantec ZTNA,
    Web Isolation처럼 뒤쪽에 위치한 top-level 서비스도 정상적으로 찾을 수 있다.
    """
    target_slugs = {s["slug"] for s in BROADCOM_STATUS_SERVICES}
    target_names = {s["name"].strip().lower(): s["slug"] for s in BROADCOM_STATUS_SERVICES}
    found = {}
    debug_candidates = []
    seen_debug_keys = set()

    def _record_debug(comp):
        name = (comp.get("name") or "")
        url = (comp.get("url") or "")
        haystack = f"{name} {url}".lower()
        if "ztna" in haystack or "isolation" in haystack:
            key = (comp.get("id"), name, url)
            if key not in seen_debug_keys:
                seen_debug_keys.add(key)
                debug_candidates.append(comp)

    def _match_component(comp):
        """1) 서비스 URL slug, 2) 정확한 서비스명 순으로 매칭한다."""
        _record_debug(comp)

        slug = _slug_from_service_url(comp.get("url"))
        if slug in target_slugs and slug not in found:
            found[slug] = comp
            return

        comp_name = (comp.get("name") or "").strip().lower()
        tslug = target_names.get(comp_name)
        if tslug and tslug not in found:
            found[tslug] = comp

    def _scan_component_pages(top_level_only=False, max_pages=100):
        """Broadcom API의 25개/page 제한을 고려해 페이지를 끝까지 순회한다."""
        page = 1
        scanned = 0
        while page <= max_pages:
            if top_level_only:
                url = f"{STATUS_API_BASE}?filter[parent_id_null]=true&page={page}"
            else:
                url = f"{STATUS_API_BASE}?page={page}"

            try:
                payload = _http_get_json(url)
            except Exception as e:
                scope = "top-level" if top_level_only else "전체"
                print(f"  -> [경고] status.broadcom.com {scope} 컴포넌트 조회 실패(page={page}): {e}")
                break

            comps = payload.get("components", [])
            if not comps:
                break

            scanned += len(comps)
            for comp in comps:
                _match_component(comp)

            if target_slugs.issubset(found.keys()):
                break

            # API가 알려주는 next_page 유무만 종료 판단에 사용하고,
            # 실제 다음 요청 URL은 위에서 직접 구성해 filter가 사라지는 문제를 방지한다.
            if not payload.get("meta", {}).get("next_page"):
                break

            page += 1

        return scanned, page

    # 1) 서비스 자체의 상태를 얻기 위해 top-level 컴포넌트를 먼저 전 페이지 탐색
    scanned_top, last_top_page = _scan_component_pages(top_level_only=True)
    print(f"  -> [디버그] top-level 컴포넌트 {scanned_top}개 스캔 (마지막 page={last_top_page})")

    # 2) 혹시 top-level 이름/URL 구조가 바뀐 서비스가 있으면 전체 트리에서 폴백 탐색
    missing = target_slugs - found.keys()
    if missing:
        scanned_all, last_all_page = _scan_component_pages(top_level_only=False)
        print(f"  -> [디버그] 전체 컴포넌트 {scanned_all}개 스캔 (마지막 page={last_all_page})")

    still_missing = target_slugs - found.keys()
    if still_missing:
        missing_names = [s["name"] for s in BROADCOM_STATUS_SERVICES if s["slug"] in still_missing]
        print(f"  -> [경고] 다음 서비스는 컴포넌트 목록에서 끝내 찾지 못했습니다: {', '.join(missing_names)}")

    if debug_candidates:
        print(f"  -> [디버그] 'ztna'/'isolation' 키워드가 들어간 컴포넌트 {len(debug_candidates)}개 발견:")
        for comp in debug_candidates:
            print(
                f"     id={comp.get('id')!r} name={comp.get('name')!r} "
                f"url={comp.get('url')!r} state={comp.get('state')!r} "
                f"parent_id={comp.get('parent_id')!r}"
            )
    else:
        print("  -> [디버그] 'ztna'/'isolation' 키워드가 들어간 컴포넌트를 API 응답에서 전혀 찾지 못함")

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
