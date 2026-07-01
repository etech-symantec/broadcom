#!/usr/bin/env python3
"""
xlsx -> json 변환 스크립트
data/products.xlsx 를 읽어서 docs/data.json 으로 저장한다.
Tabulator.js 가 바로 소비할 수 있는 형태(레코드 배열)로 출력한다.
"""

import json
import sys
from datetime import datetime, date, timezone
from pathlib import Path

import openpyxl

SRC = Path("data/products.xlsx")
DST = Path("docs/data.json")


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
    if not SRC.exists():
        print(f"ERROR: {SRC} 파일이 없습니다.", file=sys.stderr)
        sys.exit(1)

    wb = openpyxl.load_workbook(SRC, data_only=True)
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
