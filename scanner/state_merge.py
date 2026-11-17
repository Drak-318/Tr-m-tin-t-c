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
    relations = merge_relationships(
        _read(relations_path, []), _read(local_relations_path, [])
    )
    _write(relations_path, relations)

    cursor_path = root / "data/relationship_scan_state.json"
    local_cursor_path = local_root / "data/relationship_scan_state.json"
    if local_cursor_path.exists():
        _write(cursor_path, _read(local_cursor_path, {"next_candidate": 0}))
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
