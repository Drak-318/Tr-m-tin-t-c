# -*- coding: utf-8 -*-
"""One-time migration of legacy Google Sheets dedupe keys into GitHub memory."""
import json
from datetime import datetime, timezone
from pathlib import Path

from scanner.config import WEB_APP_URL
from scanner.normalizer import canonicalize_url
from scanner.persistent_memory import load_state, _write_json, DATA_DIR
from scanner.sheets import get_sources_and_memory

MARKER = DATA_DIR / "sheets_bootstrap.json"
STATE_PATH = DATA_DIR / "seen_documents.json"


def main():
    if MARKER.exists():
        marker = json.loads(MARKER.read_text(encoding="utf-8"))
        print(f"[BOOTSTRAP] Đã nhập bộ nhớ Sheets trước đó: {marker.get('urls', 0)} URL; bỏ qua.")
        return
    if not WEB_APP_URL:
        raise RuntimeError("Thiếu SHEETS_WEB_APP_URL; chưa thể nhập bộ nhớ cũ an toàn.")

    _sources, existing_links, _numbers, existing_identities = get_sources_and_memory()
    state = load_state()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added_urls = 0
    for raw_url in existing_links:
        url = canonicalize_url(raw_url)
        if not url:
            continue
        if url not in state["urls"]:
            state["urls"][url] = "legacy_sheet_url:" + url
            added_urls += 1

    added_identities = 0
    for identity in existing_identities:
        identity = str(identity).strip()
        if identity and identity not in state["documents"]:
            state["documents"][identity] = {
                "title": "", "doc_number": "", "agency": "",
                "category": "legacy_sheet_record", "first_seen": now,
                "last_seen": now, "link": "",
                "migrated_from": "Google Sheets",
            }
            added_identities += 1

    _write_json(STATE_PATH, state)
    marker = {
        "completed_at": now,
        "source": "Google Sheets one-time migration",
        "urls": len(existing_links),
        "identities": len(existing_identities),
        "new_urls": added_urls,
        "new_identities": added_identities,
    }
    _write_json(MARKER, marker)
    print("[BOOTSTRAP] " + json.dumps(marker, ensure_ascii=False))


if __name__ == "__main__":
    main()
