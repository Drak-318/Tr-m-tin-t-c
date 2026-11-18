# -*- coding: utf-8 -*-
"""Discover, validate and persist new document-listing sources.

New URLs are never activated merely because they appear on a page. They must
be same-site listing candidates and pass a live content validation first.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .normalizer import canonicalize_url, clean_title, extract_doc_info

ROOT = Path(__file__).resolve().parent.parent
DISCOVERY_PATH = ROOT / "data" / "discovered_sources.json"
LISTING_TERMS = (
    "van-ban", "vanban", "vbpq", "vbqppl", "he-thong-van-ban",
    "van-ban-phap-luat", "du-thao", "laws", "legal-documents",
    "document-list", "qlvb", "van-ban-quy-pham",
)
EXCLUDED_HOSTS = {"news.google.com", "news.googleusercontent.com"}
MAX_CANDIDATES_PER_SOURCE = 12


def _same_site(candidate_url, origin_url):
    candidate = (urlsplit(candidate_url).hostname or "").lower()
    origin = (urlsplit(origin_url).hostname or "").lower()
    return bool(candidate and origin and (candidate == origin or candidate.endswith("." + origin)))


def extract_source_candidates(html, page_url, source_name="", source_group="Văn Bản TW",
                              limit=MAX_CANDIDATES_PER_SOURCE):
    """Extract likely listing/category links, not individual document links."""
    soup = BeautifulSoup(html or "", "html.parser")
    found = {}
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        label = clean_title(anchor.get("aria-label") or anchor.get("title") or anchor.get_text(" ", strip=True))
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        from urllib.parse import urljoin
        url = canonicalize_url(urljoin(page_url, href))
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname in EXCLUDED_HOSTS:
            continue
        if not _same_site(url, page_url) or canonicalize_url(url) == canonicalize_url(page_url):
            continue
        path = (parsed.path or "").lower()
        label_low = label.casefold()
        if not any(term in path for term in LISTING_TERMS) and not any(
            term.replace("-", " ") in label_low for term in LISTING_TERMS
        ):
            continue
        # A link whose label is already a document title is a detail page, not
        # a reusable source listing.
        if extract_doc_info(label)[0] or re.search(r"\b(?:số|so)\s*\d", label_low):
            continue
        if len(label) > 120:
            continue
        found[url] = {
            "name": clean_title(f"{source_name} - {label}")[:120] if label else f"{source_name} - Danh mục văn bản",
            "url": url,
            "group": source_group or "Văn Bản TW",
            "origin_url": canonicalize_url(page_url),
            "status": "pending",
        }
        if len(found) >= max(0, int(limit)):
            break
    return list(found.values())


def _read(path=DISCOVERY_PATH):
    if not path.exists():
        return {"version": 1, "items": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("discovered_sources.json không đúng cấu trúc")
    data.setdefault("version", 1)
    data.setdefault("items", {})
    return data


def _write(data, path=DISCOVERY_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    temp.replace(path)


def record_candidates(candidates, path=DISCOVERY_PATH, max_total=500):
    data = _read(path)
    items = data.setdefault("items", {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    for candidate in candidates:
        url = canonicalize_url(candidate.get("url", ""))
        if not url:
            continue
        current = items.get(url)
        if current and current.get("status") in {"active", "rejected"}:
            current["last_seen"] = now
            continue
        if current is None:
            current = dict(candidate)
            current.update({"first_seen": now, "attempts": 0})
            items[url] = current
            added += 1
        current["last_seen"] = now
    # Keep all active sources and the newest pending candidates; never evict
    # active entries as they are now part of the scan registry.
    if len(items) > max_total:
        active = {u: row for u, row in items.items() if row.get("status") == "active"}
        pending = [(u, row) for u, row in items.items() if row.get("status") != "active"]
        pending.sort(key=lambda pair: str(pair[1].get("last_seen", "")), reverse=True)
        items = {**active, **dict(pending[:max(0, max_total - len(active))])}
        data["items"] = items
    data["updated_at"] = now
    _write(data, path)
    return added


def pending_candidates(limit=3, path=DISCOVERY_PATH):
    items = _read(path).get("items", {})
    rows = [dict(row, url=url) for url, row in items.items()
            if row.get("status") == "pending" and int(row.get("attempts", 0)) < 3]
    rows.sort(key=lambda row: (int(row.get("attempts", 0)), str(row.get("first_seen", ""))))
    return rows[:max(0, int(limit))]


def update_candidate(url, updates, path=DISCOVERY_PATH):
    canonical = canonicalize_url(url)
    data = _read(path)
    row = data.setdefault("items", {}).get(canonical)
    if row is None:
        return False
    row.update(updates)
    row["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["updated_at"] = row["updated_at"]
    _write(data, path)
    return True


def active_sources(path=DISCOVERY_PATH):
    items = _read(path).get("items", {})
    return [dict(row, url=url, row=None) for url, row in items.items()
            if row.get("status") == "active"]
