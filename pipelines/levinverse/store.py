from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{number}: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]], key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: str(row.get(key, "")))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(path)


def upsert(path: Path, records: list[dict[str, Any]], key: str) -> int:
    rows = {str(row[key]): row for row in read_jsonl(path)}
    before = len(rows)
    for record in records:
        rows[str(record[key])] = record
    write_jsonl(path, list(rows.values()), key)
    return len(rows) - before
