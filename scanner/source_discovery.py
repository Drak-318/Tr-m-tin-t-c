# -*- coding: utf-8 -*-
"""Discover, validate and persist new document-listing sources.

New URLs are never activated merely because they appear on a page. They must
discover same-site listings and clearly labelled cross-agency portal hubs. Only validated listing pages are activated.
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
AGENCY_LINK_TERMS = (
    "bộ ", "bộ,", "chính phủ", "quốc hội", "trung ương", "cơ quan trung ương",
    "các bộ", "các ngành", "các tỉnh", "tỉnh thành", "địa phương",
    "ủy ban nhân dân", "ubnd", "hội đồng nhân dân", "hđnd",
    "sở ", "ban ngành", "cơ quan chuyên môn", "cục ", "tổng cục",
    "tòa án", "viện kiểm sát", "công an", "bảo hiểm xã hội",
)
CENTRAL_HOSTS = {
    "chinhphu.vn", "vanban.chinhphu.vn", "quochoi.vn", "dangcongsan.vn",
    "moj.gov.vn", "mof.gov.vn", "moet.gov.vn", "moh.gov.vn", "mae.gov.vn",
    "moit.gov.vn", "sbv.gov.vn", "moha.gov.vn", "moc.gov.vn", "mps.gov.vn",
    "baochinhphu.vn", "baohiemxahoi.gov.vn", "vbpl.vn", "phapluat.gov.vn",
}
EXCLUDED_HOSTS = {"news.google.com", "news.googleusercontent.com"}
ALLOWED_OFFICIAL_SUFFIXES = (".gov.vn", ".gov", ".edu.vn", ".mil.vn")
MAX_CANDIDATES_PER_SOURCE = 12


def _same_site(candidate_url, origin_url):
    candidate = (urlsplit(candidate_url).hostname or "").lower()
    origin = (urlsplit(origin_url).hostname or "").lower()
    return bool(candidate and origin and (candidate == origin or candidate.endswith("." + origin)))


def _official_host(host):
    host = (host or "").lower().rstrip(".")
    return host in CENTRAL_HOSTS or any(host.endswith(suffix) for suffix in ALLOWED_OFFICIAL_SUFFIXES)


def _source_group_for_link(host, label, fallback_group):
    host = (host or "").lower()
    label_low = (label or "").casefold()
    if host in CENTRAL_HOSTS or any(term in label_low for term in (
        "chính phủ", "quốc hội", "bộ nội vụ", "bộ tài chính", "bộ tư pháp",
        "bộ giáo dục", "bộ y tế", "bộ công an", "bộ xây dựng",
        "bộ nông nghiệp", "bộ công thương", "trung ương", "tổng cục", "cục thuế",
    )):
        return "Văn Bản TW"
    if host.endswith((".gov.vn", ".edu.vn", ".mil.vn")):
        return "Địa phương"
    return fallback_group or "Văn Bản TW"


def extract_source_candidates(html, page_url, source_name="", source_group="Văn Bản TW",
                              limit=MAX_CANDIDATES_PER_SOURCE):
    """Find same-site legal listings and cross-agency official portal hubs."""
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    found = {}
    origin_host = (urlsplit(page_url).hostname or "").lower()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        label = clean_title(anchor.get("aria-label") or anchor.get("title") or anchor.get_text(" ", strip=True))
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = canonicalize_url(urljoin(page_url, href))
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme not in {"http", "https"} or not host or host in EXCLUDED_HOSTS
                or parsed.username or parsed.password or parsed.port not in {None, 80, 443}
                or canonicalize_url(url) == canonicalize_url(page_url)):
            continue

        same_site = _same_site(url, page_url)
        path = (parsed.path or "").lower()
        label_low = label.casefold()
        is_listing = (
            (same_site or _official_host(host))
            and (
                any(term in path for term in LISTING_TERMS)
                or any(term.replace("-", " ") in label_low for term in LISTING_TERMS)
            )
        )
        is_agency_link = (
            not same_site and _official_host(host)
            and any(term in label_low for term in AGENCY_LINK_TERMS)
        )
        if not is_listing and not is_agency_link:
            continue
        if is_listing and (extract_doc_info(label)[0] or re.search(r"\b(?:số|so)\s*\d", label_low)):
            continue
        if len(label) > 160:
            continue

        kind = "listing" if is_listing else "portal_hub"
        group = source_group if same_site else _source_group_for_link(host, label, source_group)
        key = canonicalize_url(url)
        found[key] = {
            "name": clean_title(f"{source_name} - {label}")[:120] if label else f"{source_name} - Cổng cơ quan",
            "url": key,
            "group": group,
            "origin_url": canonicalize_url(page_url),
            "origin_host": origin_host,
            "anchor_label": label[:160],
            "candidate_kind": kind,
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
