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
    ("trien_khai", ("triển khai", "tổ chức thực hiện")),
    ("thuc_hien", ("thực hiện",)),
)


def extract_document_references(text):
    """Return references with a short, auditable context excerpt."""
    content = clean_title(text)
    found = {}
    for match in REFERENCE_RE.finditer(content):
        start, end = match.span()
        context = content[max(0, start - 110):min(len(content), end + 110)]
        # Classify from the lead-in only; later clauses may describe a different cited act.
        folded = content[max(0, start - 110):start].casefold()
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
    for node in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "aside"]):
        node.decompose()
    noise = re.compile(r"sidebar|related|recommend|popular|most[-_ ]?view|footer|header|menu|breadcrumb|widget|banner|advert|comment|social|share|pagination|news[-_ ]?list|list[-_ ]?news", re.I)
    for node in list(soup.find_all(True)):
        # Decomposing a parent can leave its former children in this snapshot.
        if getattr(node, "attrs", None) is None:
            continue
        marker = " ".join([str(node.get("id") or ""), " ".join(node.get("class") or [])])
        if noise.search(marker):
            node.decompose()
    selectors = (
        "article", "main", "[role='main']", ".article-content", ".content-detail",
        ".detail-content", ".news-detail", ".detail-news", ".entry-content",
        ".post-content", ".news-content", ".main-content", "#main-content"
    )
    candidates = soup.select(", ".join(selectors))
    if candidates:
        node = max(candidates, key=lambda item: len(item.get_text(" ", strip=True)))
    else:
        blocks = soup.find_all("div")
        node = max(blocks, key=lambda item: len(item.get_text(" ", strip=True))) if blocks else soup.body or soup
    return node.get_text(" ", strip=True)[:120000]


def fetch_detail_text(url, timeout=(8, 18)):
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
        return ""


def collect_local_document_relations(candidates, limit=8):
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
        body = fetch_detail_text(url)
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


def resolve_reference_candidates(relations, known_documents):
    """Match cited numbers against known records; never resolve by number alone if ambiguous."""
    index = {}
    for document in known_documents or []:
        number = str(document.get("doc_number") or "").strip().upper()
        title = clean_title(document.get("title", ""))
        doc_type, extracted_number = extract_doc_info(title)
        number = number if number and number != "ĐANG CẬP NHẬT" else (extracted_number or "")
        doc_type = document.get("doc_type") or doc_type or ""
        if not number:
            continue
        index.setdefault((number, str(doc_type).casefold()), []).append({
            "title": title,
            "doc_number": number,
            "doc_type": doc_type,
            "agency": clean_title(document.get("agency", "")),
            "link": canonicalize_url(document.get("link", "")),
        })

    resolved = []
    for relation in relations or []:
        key = (
            str(relation.get("referenced_doc_number", "")).strip().upper(),
            str(relation.get("referenced_doc_type", "")).casefold(),
        )
        matches = index.get(key, [])
        # Collapse duplicate records that point to the same canonical URL.
        unique = {}
        for match in matches:
            identity = match["link"] or (match["agency"] + "|" + match["title"])
            unique[identity] = match
        matches = list(unique.values())
        row = dict(relation)
        row["matched_documents"] = matches[:5]
        if len(matches) == 1:
            row["resolution_status"] = "found_in_scan_index"
        elif len(matches) > 1:
            row["resolution_status"] = "ambiguous_multiple_matches"
        else:
            row["resolution_status"] = "not_found_in_scan_index"
        resolved.append(row)
    return resolved
