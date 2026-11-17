"""Extract traceable references from local legal-document detail pages.

Detected references are candidates, not confirmed legal relationships. Each record
keeps the exact evidence excerpt and source URL for later human verification.
"""
import re
import time
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from .normalizer import canonicalize_url, clean_title, extract_doc_info

REFERENCE_RE = re.compile(
    r"(?P<type>Luật|Nghị định|Thông tư|Quyết định|Nghị quyết|Chỉ thị|"
    r"Công văn|Kết luận|Hướng dẫn|Kế hoạch|Thông báo|Quy chế|Quy định)"
    r"\s+(?:số\s*)?(?P<number>\d+(?:/\d{4})?[/-][A-ZĐƯƠĂÂÊÔ0-9/-]+)",
    re.IGNORECASE,
)
# More specific legal relationships take precedence over generic "thực hiện".
RELATION_RULES = (
    ("huong_dan", ("hướng dẫn thi hành", "hướng dẫn thực hiện", "hướng dẫn")),
    ("quy_dinh_chi_tiet", ("quy định chi tiết", "quy định cụ thể")),
    ("can_cu", ("căn cứ", "theo quy định tại", "quy định tại")),
    ("trien_khai", ("triển khai", "tổ chức thực hiện", "thực hiện")),
)


def extract_document_references(text):
    """Return references with a short, auditable context excerpt."""
    content = clean_title(text)
    found = {}
    for match in REFERENCE_RE.finditer(content):
        start, end = match.span()
        context = content[max(0, start - 110):min(len(content), end + 110)]
        folded = context.casefold()
        relation = "dan_chieu"
        for label, phrases in RELATION_RULES:
            if any(phrase in folded for phrase in phrases):
                relation = label
                break
        number = match.group("number").upper().rstrip(".,;:)")
        key = (match.group("type").title(), number, relation)
        found[key] = {
            "referenced_doc_type": match.group("type").title(),
            "referenced_doc_number": number,
            "relation_type": relation,
            "evidence_excerpt": context[:280],
        }
    return list(found.values())


def _article_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
        node.decompose()
    candidates = soup.select("article, main, [role='main'], .article-content, .content-detail, .detail-content")
    node = max(candidates, key=lambda item: len(item.get_text(" ", strip=True))) if candidates else soup.body or soup
    return node.get_text(" ", strip=True)[:120000]


def fetch_detail_text(url, fallback_fetcher=None, timeout=(8, 18)):
    """Fetch a document detail page directly, then via the configured Apps Script proxy."""
    host = (urlsplit(url).hostname or "").lower()
    if not host or host in {"news.google.com", "news.googleusercontent.com"}:
        return ""
    try:
        response = requests.get(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TramTinTuc/1.0)",
                     "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8"},
        )
        response.raise_for_status()
        return _article_text(response.text)
    except requests.RequestException:
        if not fallback_fetcher:
            return ""
    try:
        remote = fallback_fetcher(url, "Trang chi tiết văn bản")
        if remote.get("status") == "ok" and 200 <= int(remote.get("http_status", 0)) < 300:
            return _article_text(remote.get("body", ""))
    except Exception:
        pass
    return ""


def collect_local_document_relations(candidates, fallback_fetcher=None, limit=8):
    """Inspect a small number of local-document detail pages per scan."""
    relations = []
    inspected = 0
    for candidate in candidates:
        if inspected >= max(0, int(limit)):
            break
        url = canonicalize_url(candidate.get("link", ""))
        if not url:
            continue
        inspected += 1
        body = fetch_detail_text(url, fallback_fetcher=fallback_fetcher)
        if not body:
            continue
        title = clean_title(candidate.get("title", ""))
        own_type, own_number = extract_doc_info(title)
        for reference in extract_document_references(title + " " + body):
            if own_number and reference["referenced_doc_number"] == own_number:
                continue
            relations.append({
                "source_doc_title": title,
                "source_doc_number": own_number or "",
                "source_agency": clean_title(candidate.get("agency", "")),
                "source_url": url,
                **reference,
                "evidence_url": url,
                "verification_status": "candidate_needs_verification",
            })
        time.sleep(0.15)
    return relations


def merge_relationships(existing, incoming, limit=5000):
    """Merge candidate edges without claiming that a legal relationship is verified."""
    merged = {}
    for row in list(existing or []) + list(incoming or []):
        key = (
            canonicalize_url(row.get("source_url", "")),
            str(row.get("referenced_doc_number", "")).upper(),
            row.get("relation_type", "dan_chieu"),
        )
        if key[0] and key[1]:
            merged[key] = row
    return list(merged.values())[-limit:]
