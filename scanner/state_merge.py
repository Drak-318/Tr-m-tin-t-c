"""Conflict-safe merge for scanner state written by overlapping GitHub Actions runs."""
import argparse
import json
from pathlib import Path

from .relationship_tracer import merge_relationships

STATE_FILES = (
    "data/seen_documents.json",
    "data/scan_history.json",
    "data/document_relationships.json",
    "data/relationship_scan_state.json",
    "data/review_queue.json",
    "data/sheets_export_queue.json",
    "data/discovered_sources.json",
)


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def merge_seen_documents(remote, local):
    merged = dict(remote or {})
    merged["version"] = max(int((remote or {}).get("version", 1)), int((local or {}).get("version", 1)))
    documents = dict((remote or {}).get("documents", {}))
    for identity, row in (local or {}).get("documents", {}).items():
        current = documents.get(identity)
        if current is None or str(row.get("last_seen", row.get("first_seen", ""))) >= str(current.get("last_seen", current.get("first_seen", ""))):
            documents[identity] = row
    urls = dict((remote or {}).get("urls", {}))
    urls.update((local or {}).get("urls", {}))
    merged["documents"] = documents
    merged["urls"] = urls
    return merged


def merge_scan_history(remote, local, limit=1000):
    unique = {}
    for row in list(remote or []) + list(local or []):
        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        unique[key] = row
    rows = list(unique.values())
    rows.sort(key=lambda row: str(row.get("finished_at", "")))
    return rows[-limit:]


def merge_state_files(local_dir, repo_root="."):
    local_root = Path(local_dir)
    root = Path(repo_root)
    seen_path = root / "data/seen_documents.json"
    local_seen_path = local_root / "data/seen_documents.json"
    remote_seen = _read(seen_path, {"version": 1, "documents": {}, "urls": {}})
    local_seen = _read(local_seen_path, {"version": 1, "documents": {}, "urls": {}})
    _write(seen_path, merge_seen_documents(remote_seen, local_seen))

    history_path = root / "data/scan_history.json"
    local_history_path = local_root / "data/scan_history.json"
    _write(history_path, merge_scan_history(_read(history_path, []), _read(local_history_path, [])))

    relations_path = root / "data/document_relationships.json"
    local_relations_path = local_root / "data/document_relationships.json"
    remote_relations = [
        row for row in _read(relations_path, [])
        if row.get("source_doc_number") and row.get("source_doc_number") != "Đang cập nhật"
    ]
    local_relations = [
        row for row in _read(local_relations_path, [])
        if row.get("source_doc_number") and row.get("source_doc_number") != "Đang cập nhật"
    ]
    relations = merge_relationships(remote_relations, local_relations)
    _write(relations_path, relations)

    cursor_path = root / "data/relationship_scan_state.json"
    local_cursor_path = local_root / "data/relationship_scan_state.json"
    if local_cursor_path.exists():
        _write(cursor_path, _read(local_cursor_path, {"next_candidate": 0}))

    # Merge review records by canonical URL; keep pending items and accumulated evidence.
    review_path = root / "data/review_queue.json"
    local_review_path = local_root / "data/review_queue.json"
    remote_review = _read(review_path, {"version": 1, "items": {}})
    local_review = _read(local_review_path, {"version": 1, "items": {}})
    review_items = dict(remote_review.get("items", {}))
    for url, row in local_review.get("items", {}).items():
        current = dict(review_items.get(url, {}))
        current.update(row)
        current["attempts"] = max(int(current.get("attempts", 0)), int(row.get("attempts", 0)))
        review_items[url] = current
    _write(review_path, {"version": 1, "items": review_items,
                         "updated_at": max(str(remote_review.get("updated_at", "")), str(local_review.get("updated_at", "")))})

    # Export jobs are retained until Apps Script explicitly confirms them.
    export_path = root / "data/sheets_export_queue.json"
    local_export_path = local_root / "data/sheets_export_queue.json"
    remote_export = _read(export_path, {"version": 1, "items": []})
    local_export = _read(local_export_path, {"version": 1, "items": []})
    # The scanner workflow is serialized; its local queue is a complete snapshot
    # including all pre-run jobs plus this run's additions/acknowledgements.
    # Treat it as authoritative so successfully exported jobs can actually be cleared.
    if local_export_path.exists():
        export_items = list(local_export.get("items", []))
    else:
        export_items = list(remote_export.get("items", []))
    _write(export_path, {"version": 1, "items": export_items})

    # Merge discovered source candidates; active sources take precedence.
    discovered_path = root / "data/discovered_sources.json"
    local_discovered_path = local_root / "data/discovered_sources.json"
    remote_discovered = _read(discovered_path, {"version": 1, "items": {}})
    local_discovered = _read(local_discovered_path, {"version": 1, "items": {}})
    discovered_items = dict(remote_discovered.get("items", {}))
    for url, row in local_discovered.get("items", {}).items():
        current = dict(discovered_items.get(url, {}))
        if current.get("status") != "active" or row.get("status") == "active":
            current.update(row)
        current["attempts"] = max(int(current.get("attempts", 0)), int(row.get("attempts", 0)))
        discovered_items[url] = current
    _write(discovered_path, {"version": 1, "items": discovered_items,
                             "updated_at": max(str(remote_discovered.get("updated_at", "")),
                                               str(local_discovered.get("updated_at", "")))})

    # Preserve the one-time migration marker across the workflow's reset-to-main merge.
    bootstrap_path = root / "data/sheets_bootstrap.json"
    local_bootstrap_path = local_root / "data/sheets_bootstrap.json"
    if local_bootstrap_path.exists():
        _write(bootstrap_path, _read(local_bootstrap_path, {}))

    return {
        "documents": len(merge_seen_documents(remote_seen, local_seen)["documents"]),
        "history": len(merge_scan_history(_read(history_path, []), [])),
        "relationships": len(relations),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    result = merge_state_files(args.local_dir, args.repo_root)
    print("[MEMORY MERGE] " + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
