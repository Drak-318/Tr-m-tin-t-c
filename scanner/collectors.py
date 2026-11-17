import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .normalizer import clean_title, canonicalize_url

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TramTinTucBot/2.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
}

def make_session():
    session = requests.Session()
    retry = Retry(
        total=2, connect=2, read=2, status=2, backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)
    return session

def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()

def parse_feed(content, max_items=200):
    root = ET.fromstring(content)
    results = []
    for node in root.iter():
        if local_name(node.tag) not in {"item", "entry"}:
            continue
        title, link = "", ""
        for child in list(node):
            tag = local_name(child.tag)
            if tag == "title" and not title:
                title = "".join(child.itertext()).strip()
            elif tag == "link" and not link:
                link = (child.attrib.get("href") or child.text or "").strip()
        if title and link:
            results.append({"title": clean_title(title), "link": canonicalize_url(link)})
        if len(results) >= max_items:
            break
    return results

def discover_feed_url(soup, page_url):
    for node in soup.find_all("link", href=True):
        rel = " ".join(node.get("rel", [])).lower()
        mime = (node.get("type") or "").lower()
        if "alternate" in rel and any(token in mime for token in ("rss", "atom", "xml")):
            return urljoin(page_url, node["href"])
    return None

def parse_html_items(html, page_url, config):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    item_selector = config.get("item_selector")
    title_selector = config.get("title_selector")
    link_selector = config.get("link_selector")
    if item_selector:
        for container in soup.select(item_selector):
            title_node = container.select_one(title_selector) if title_selector else container
            link_node = container.select_one(link_selector) if link_selector else (
                title_node if getattr(title_node, "name", None) == "a"
                else container.find("a", href=True)
            )
            if not link_node:
                continue
            title = clean_title(title_node.get_text(" ", strip=True))
            href = link_node.get("href", "")
            if title and href:
                results.append({"title": title, "link": canonicalize_url(urljoin(page_url, href))})
        return results, soup

    for anchor in soup.find_all("a", href=True):
        title = clean_title(anchor.get("aria-label") or anchor.get("title") or anchor.get_text(" ", strip=True))
        href = anchor.get("href", "").strip()
        if len(title) >= 18 and href and not href.startswith(("javascript:", "mailto:", "#")):
            results.append({"title": title, "link": canonicalize_url(urljoin(page_url, href))})
    return results, soup

def find_next_page(soup, page_url, config):
    selector = config.get("pagination_selector")
    candidates = soup.select(selector) if selector else soup.select('a[rel~="next"]')
    if not candidates and config.get("follow_pagination"):
        candidates = soup.find_all("a", href=True)
    for node in candidates:
        label = clean_title(node.get_text(" ", strip=True)).lower()
        rel = " ".join(node.get("rel", [])).lower()
        if selector or "next" in rel or label in {"sau", "tiếp", "tiếp theo", "next", "›", "»"}:
            href = node.get("href", "")
            if href:
                return canonicalize_url(urljoin(page_url, href))
    return None

def fetch_response(session, url, config):
    timeout = (int(config.get("timeout_connect", 8)), int(config.get("timeout_read", 18)))
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response

def scan_source(source, config):
    started = time.monotonic()
    session = make_session()
    base_url = source["url"].strip()
    mode = str(config.get("mode", "auto")).lower()
    max_items = max(1, int(config.get("max_items", 200)))
    max_pages = max(1, min(int(config.get("max_pages", 1)), 10))
    items, page_count, feed_used = [], 0, False

    try:
        response = fetch_response(session, base_url, config)
        page_count += 1
        content_type = (response.headers.get("Content-Type") or "").lower()
        body_start = response.text[:500].lower()
        is_feed = "xml" in content_type or "rss" in content_type or "<rss" in body_start or "<feed" in body_start

        if mode == "rss" or (mode == "auto" and is_feed):
            items = parse_feed(response.content, max_items=max_items)
            feed_used = True
        elif mode == "auto":
            soup = BeautifulSoup(response.text, "html.parser")
            feed_url = discover_feed_url(soup, response.url)
            if feed_url:
                try:
                    feed_response = fetch_response(session, feed_url, config)
                    items = parse_feed(feed_response.content, max_items=max_items)
                    feed_used = True
                except Exception:
                    items = []

        if not feed_used:
            page_url, html = response.url, response.text
            seen_pages = {canonicalize_url(page_url)}
            while True:
                page_items, soup = parse_html_items(html, page_url, config)
                items.extend(page_items)
                if len(items) >= max_items or page_count >= max_pages:
                    break
                next_url = find_next_page(soup, page_url, config)
                if not next_url or next_url in seen_pages:
                    break
                seen_pages.add(next_url)
                next_response = fetch_response(session, next_url, config)
                page_url, html = next_response.url, next_response.text
                page_count += 1

        unique = {}
        for item in items:
            title = clean_title(item.get("title"))
            link = canonicalize_url(item.get("link"))
            if title and link:
                unique.setdefault(link, {"title": title, "link": link})
        final_items = list(unique.values())[:max_items]
        return {
            "items": final_items,
            "status": "Hoạt động" if final_items else "Không tìm thấy mục",
            "http_status": response.status_code,
            "pages": page_count,
            "duration": round(time.monotonic() - started, 2),
            "error": "",
        }
    except Exception as exc:
        return {
            "items": [], "status": f"Lỗi: {type(exc).__name__}"[:45],
            "http_status": None, "pages": page_count,
            "duration": round(time.monotonic() - started, 2),
            "error": str(exc)[:300],
        }
    finally:
        session.close()
