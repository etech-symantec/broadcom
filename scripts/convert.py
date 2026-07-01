#!/usr/bin/env python3
"""
xlsx -> json 변환 스크립트
data/ 폴더 안의 xlsx 파일을 찾아서 docs/data.json 으로 저장한다.
파일 이름은 무관하며, 여러 개일 경우 가장 최근에 수정된 파일을 사용한다.
Tabulator.js 가 바로 소비할 수 있는 형태(레코드 배열)로 출력한다.
"""

import json
import sys
from datetime import datetime, date, timezone
from pathlib import Path

import openpyxl

DATA_DIR = Path("data")
DST = Path("docs/data.json")


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


def main():
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
