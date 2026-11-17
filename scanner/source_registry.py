# -*- coding: utf-8 -*-
"""Load the source registry maintained in the repository."""
import csv
from pathlib import Path
from urllib.parse import urlparse

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "danh_sach_nguon.csv"


def load_sources_from_csv(path=REGISTRY_PATH):
    if not path.exists():
        return []

    sources = []
    seen = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"name", "url"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("danh_sach_nguon.csv cần có tối thiểu hai cột name,url")

        for line_no, raw in enumerate(reader, start=2):
            url = (raw.get("url") or "").strip()
            if not url:
                continue
            enabled = (raw.get("enabled") or "true").strip().lower()
            if enabled in {"false", "0", "no", "off", "không"}:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"URL không hợp lệ tại dòng {line_no}: {url}")
            canonical = url.rstrip("/").lower()
            if canonical in seen:
                continue
            seen.add(canonical)
            name = (raw.get("name") or "").strip() or f"Nguồn dòng {line_no}"
            group = (raw.get("group") or "Văn Bản TW").strip()
            sources.append({
                "name": name,
                "url": url,
                "group": group or "Văn Bản TW",
                "row": None,
                "registry_line": line_no,
            })
    return sources
