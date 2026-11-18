import time
import re
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .normalizer import clean_title, canonicalize_url, extract_doc_info

HEADERS = {"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
           "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language":"vi-VN,vi;q=0.9,en-US;q=0.8"}

class SourceFetchError(RuntimeError):
    def __init__(self, kind, message, http_status=None, url=None):
        super().__init__(message)
        self.kind=kind
        self.http_status=http_status
        self.url=url

def make_session():
    session=requests.Session()
    retry=Retry(total=2,connect=2,read=2,status=2,backoff_factor=0.6,
                status_forcelist=(429,500,502,503,504),
                allowed_methods=frozenset(["GET"]),respect_retry_after_header=True)
    adapter=HTTPAdapter(max_retries=retry,pool_connections=10,pool_maxsize=10)
    session.mount("http://",adapter); session.mount("https://",adapter); session.headers.update(HEADERS)
    return session

def local_name(tag): return tag.rsplit("}",1)[-1].lower()

def parse_feed(content,max_items=200):
    try:
        root=ET.fromstring(content)
    except ET.ParseError as exc:
        raise SourceFetchError("PARSER",f"RSS/Atom không đúng định dạng XML: {exc}") from exc
    results=[]
    date_tags={"pubdate","published","updated","date","created","issued"}
    for node in root.iter():
        if local_name(node.tag) not in {"item","entry"}: continue
        title=link=published=""
        for child in list(node):
            tag=local_name(child.tag)
            if tag=="title" and not title: title="".join(child.itertext()).strip()
            elif tag=="link" and not link: link=(child.attrib.get("href") or child.text or "").strip()
            elif tag in date_tags and not published: published="".join(child.itertext()).strip()
        if title and link:
            results.append({"title":clean_title(title),"link":canonicalize_url(link),"published_date":published or None})
        if len(results)>=max_items: break
    return results

def discover_feed_url(soup,page_url):
    for node in soup.find_all("link",href=True):
        rel=" ".join(node.get("rel",[])).lower(); mime=(node.get("type") or "").lower()
        if "alternate" in rel and any(x in mime for x in ("rss","atom","xml")): return urljoin(page_url,node["href"])
    return None

def _date_from_container(container,soup):
    for node in [container]+container.find_all(["time","meta"],limit=12):
        value=node.get("datetime") or node.get("content") or node.get("data-date") or node.get_text(" ",strip=True)
        if value and any(c.isdigit() for c in value):
            from .normalizer import parse_date
            parsed=parse_date(value)
            if parsed: return parsed.strftime("%Y-%m-%d")
    return None

def parse_html_items(html,page_url,config):
    soup=BeautifulSoup(html,"html.parser"); results=[]
    item_selector=config.get("item_selector"); title_selector=config.get("title_selector"); link_selector=config.get("link_selector")
    if item_selector:
        containers=soup.select(item_selector)
        for container in containers:
            title_node=container.select_one(title_selector) if title_selector else container
            link_node=container.select_one(link_selector) if link_selector else (title_node if getattr(title_node,"name",None)=="a" else container.find("a",href=True))
            if not link_node: continue
            title=clean_title(title_node.get_text(" ",strip=True)); href=link_node.get("href","")
            if not title or not href:
                continue
            item={"title":title,"link":canonicalize_url(urljoin(page_url,href)),
                  "published_date":_date_from_container(container,soup)}
            number_selector=config.get("document_number_selector")
            issue_date_selector=config.get("issue_date_selector")
            number_node=container.select_one(number_selector) if number_selector else None
            date_node=container.select_one(issue_date_selector) if issue_date_selector else None
            if number_node:
                number=clean_title(number_node.get_text(" ",strip=True))
                if number:
                    item["doc_number"]=number
                    suffix=re.search(r"-([A-ZĐƯƠĂÂÊÔ]+)(?:/|$)",number,re.I)
                    type_by_suffix={"KL":"Kết luận","NQ":"Nghị quyết","KH":"Kế hoạch","HD":"Hướng dẫn",
                                    "CT":"Chỉ thị","QD":"Quyết định","QĐ":"Quyết định","CV":"Công văn",
                                    "TB":"Thông báo","QC":"Quy chế"}
                    if suffix and suffix.group(1).upper() in type_by_suffix:
                        item["doc_type"]=type_by_suffix[suffix.group(1).upper()]
            if date_node:
                issue_date=clean_title(date_node.get_text(" ",strip=True))
                if issue_date:
                    item["issue_date"]=issue_date
                    item["title"]=f"{title} ngày {issue_date}"
                    item["published_date"]=issue_date
            results.append(item)
        return results,soup
    for anchor in soup.find_all("a",href=True):
        title=clean_title(anchor.get("aria-label") or anchor.get("title") or anchor.get_text(" ",strip=True))
        href=anchor.get("href","").strip()
        if len(title)>=18 and href and not href.startswith(("javascript:","mailto:","#")):
            # On many government portals the clickable title, document number,
            # and date are separate cells in one table row. Read the nearest
            # semantic row/card so the document is not discarded just because
            # its number is outside the anchor text.
            container=anchor.find_parent(["tr","li","article"]) or anchor.parent or anchor
            context_text=clean_title(container.get_text(" ",strip=True)) if getattr(container,"get_text",None) else title
            item={"title":title,"link":canonicalize_url(urljoin(page_url,href)),
                  "published_date":_date_from_container(container,soup)}
            if context_text and len(context_text)<=700:
                context_type,context_number=extract_doc_info(context_text)
                if context_type and context_number and context_number!="Đang cập nhật":
                    item["doc_type"]=context_type
                    item["doc_number"]=context_number
            results.append(item)
    return results,soup

def extract_detail_date(html):
    """Extract a labelled issue date first, then a page publication/update date."""
    from .normalizer import parse_date
    soup=BeautifulSoup(html,"html.parser")
    text=soup.get_text(" ",strip=True)

    # Only labelled dates count as issue dates; do not mistake arbitrary dates
    # in legal references or article body text for the current document's issue date.
    issue_patterns=(
        r"(?:ngày\s*ban\s*hành|ngày\s*ký\s*ban\s*hành|ngày\s*ký|ban\s*hành\s*ngày)\s*[:：]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    )
    for pattern in issue_patterns:
        match=re.search(pattern,text,re.I)
        if match:
            parsed=parse_date(match.group(1))
            if parsed:
                return {"date":parsed.strftime("%Y-%m-%d"),"basis":"issue_date_detail",
                        "evidence":match.group(0)[:180]}

    published_keys={
        "article:published_time","datepublished","dc.date.issued","dcterms.issued",
        "publishdate","pubdate","date",
    }
    updated_keys={"article:modified_time","datemodified","last-modified","og:updated_time"}
    published=[]; updated=[]
    for node in soup.find_all("meta"):
        key=(node.get("property") or node.get("name") or node.get("itemprop") or "").strip().lower()
        value=(node.get("content") or "").strip()
        if not key or not value:
            continue
        if key in published_keys:
            published.append((key,value))
        elif key in updated_keys:
            updated.append((key,value))
    for node in soup.find_all("time"):
        value=(node.get("datetime") or node.get_text(" ",strip=True)).strip()
        if value:
            published.append(("time",value))
    for basis,values in (("source_posted_date_detail",published),("source_updated_date_detail",updated)):
        for key,value in values:
            parsed=parse_date(value)
            if parsed:
                return {"date":parsed.strftime("%Y-%m-%d"),"basis":basis,
                        "evidence":f"{key}={value}"[:180]}

    # Visible labels for publication dates are a last-resort fallback.
    posted_match=re.search(r"(?:ngày\s*đăng|đăng\s*ngày|cập\s*nhật\s*ngày)\s*[:：]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})",text,re.I)
    if posted_match:
        parsed=parse_date(posted_match.group(1))
        if parsed:
            return {"date":parsed.strftime("%Y-%m-%d"),"basis":"source_posted_date_detail",
                    "evidence":posted_match.group(0)[:180]}
    return {"date":"","basis":"unknown","evidence":""}


def verify_document_detail_date(url,config=None):
    """Fetch one document detail page and return date evidence without scan-time fallback."""
    from urllib.parse import urlsplit
    parsed=urlsplit(str(url or ""))
    if parsed.scheme not in {"http","https"} or not parsed.netloc:
        return {"date":"","basis":"fetch_error","evidence":"","error":"URL không hợp lệ"}
    if parsed.hostname in {"news.google.com","news.googleusercontent.com"}:
        return {"date":"","basis":"fetch_error","evidence":"",
                "error":"Liên kết tổng hợp chưa được chuyển về trang nguồn gốc; không dùng ngày Google News."}
    settings=dict(config or {})
    settings.setdefault("timeout_connect",6)
    settings.setdefault("timeout_read",12)
    session=make_session()
    try:
        response=fetch_response(session,url,settings)
        result=extract_detail_date(response.text)
        result["final_url"]=canonicalize_url(response.url)
        return result
    except SourceFetchError as exc:
        return {"date":"","basis":"fetch_error","evidence":"","error":f"{exc.kind}: {exc}"[:350]}
    finally:
        session.close()


def find_next_page(soup,page_url,config):
    selector=config.get("pagination_selector"); candidates=soup.select(selector) if selector else soup.select('a[rel~="next"]')
    if not candidates and config.get("follow_pagination"): candidates=soup.find_all("a",href=True)
    for node in candidates:
        label=clean_title(node.get_text(" ",strip=True)).lower(); rel=" ".join(node.get("rel",[])).lower()
        if selector or "next" in rel or label in {"sau","tiếp","tiếp theo","next","›","»"}:
            href=str(node.get("href","") or "").strip()
            # ASP.NET pager controls may use javascript:__doPostBack rather than a
            # navigable URL. Never pass script pseudo-URLs to requests; keep the
            # successfully parsed current page instead of failing the whole source.
            if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:")):
                continue
            if urlsplit(href).scheme and urlsplit(href).scheme not in {"http", "https"}:
                continue
            return canonicalize_url(urljoin(page_url,href))
    return None

def fetch_response(session,url,config):
    timeout=(int(config.get("timeout_connect",8)),int(config.get("timeout_read",18)))
    try:
        response=session.get(url,timeout=timeout,allow_redirects=True)
        response.raise_for_status()
        return response
    except requests.exceptions.SSLError as exc:
        raise SourceFetchError("SSL",f"Không xác minh được chứng chỉ TLS: {exc}",url=url) from exc
    except requests.exceptions.HTTPError as exc:
        response=getattr(exc,"response",None)
        status=response.status_code if response is not None else None
        raise SourceFetchError("HTTP",f"Website trả HTTP {status}: {exc}",http_status=status,url=url) from exc
    except requests.exceptions.Timeout as exc:
        raise SourceFetchError("TIMEOUT",f"Hết thời gian chờ: {exc}",url=url) from exc
    except requests.exceptions.ConnectionError as exc:
        raise SourceFetchError("CONNECTION",f"Lỗi kết nối: {exc}",url=url) from exc
    except requests.exceptions.RequestException as exc:
        raise SourceFetchError("REQUEST",str(exc),url=url) from exc

def _collect_primary(session,base_url,config,max_items,max_pages,initial_response=None,discovery_sink=None):
    response=initial_response or fetch_response(session,base_url,config); page_count=1; items=[]; feed_used=False
    content_type=(response.headers.get("Content-Type") or "").lower(); body_start=response.text[:500].lower()
    is_feed="rss" in content_type or "atom" in content_type or "<rss" in body_start or "<feed" in body_start
    mode=str(config.get("mode","auto")).lower()
    if mode=="rss" or (mode=="auto" and is_feed):
        items=parse_feed(response.content,max_items); feed_used=True
    elif mode=="auto":
        soup=BeautifulSoup(response.text,"html.parser"); feed_url=discover_feed_url(soup,response.url)
        if feed_url:
            try:
                fr=fetch_response(session,feed_url,config); items=parse_feed(fr.content,max_items); feed_used=True
            except SourceFetchError:
                pass
    if not feed_used:
        page_url,html=response.url,response.text; seen_pages={canonicalize_url(page_url)}
        while True:
            page_items,soup=parse_html_items(html,page_url,config); items.extend(page_items)
            if discovery_sink is not None:
                from .source_discovery import extract_source_candidates
                discovery_sink.extend(extract_source_candidates(
                    html, page_url, config.get("_source_name", ""),
                    config.get("_source_group", "Văn Bản TW")
                ))
            if len(items)>=max_items or page_count>=max_pages: break
            next_url=find_next_page(soup,page_url,config)
            if not next_url or next_url in seen_pages: break
            seen_pages.add(next_url)
            try:
                nr=fetch_response(session,next_url,config)
            except SourceFetchError as exc:
                # Keep documents already collected from earlier pages; the failed
                # page is recorded so the source can be retried on a later run.
                config.setdefault("_partial_errors",[]).append(f"Pagination {exc.kind}: {exc}")
                break
            page_url,html=nr.url,nr.text; page_count+=1
    return items,page_count,response.status_code

def _deduplicate_items(items,max_items):
    unique={}
    for item in items:
        title=clean_title(item.get("title")); link=canonicalize_url(item.get("link"))
        if title and link:
            old=unique.get(link)
            if old is None or (not old.get("published_date") and item.get("published_date")):
                unique[link]={**item,"title":title,"link":link}
    return list(unique.values())[:max_items]

def _resolve_aggregator_links(session,items,config=None):
    from concurrent.futures import ThreadPoolExecutor
    resolved=[item for item in items if urlsplit(item.get("link","")).hostname not in
              {"news.google.com","news.googleusercontent.com"}]
    aggregator_items=[item for item in items if urlsplit(item.get("link","")).hostname in
                      {"news.google.com","news.googleusercontent.com"}][:60]
    settings = dict(config or {})
    allowed_domains = tuple(str(x).lower().lstrip(".") for x in settings.get("allowed_final_domains", []))
    def resolve(item):
        try:
            response=session.get(item.get("link",""),timeout=(4,8),allow_redirects=True)
            final_url=canonicalize_url(response.url)
            host=(urlsplit(final_url).hostname or "").lower()
            allowed = not allowed_domains or any(host == domain or host.endswith("." + domain) for domain in allowed_domains)
            if response.ok and host not in {"news.google.com","news.googleusercontent.com"} and allowed:
                return {**item,"link":final_url,"link_resolved_from_aggregator":True}
        except requests.exceptions.RequestException:
            pass
        return None
    with ThreadPoolExecutor(max_workers=10) as pool:
        for item in pool.map(resolve,aggregator_items):
            if item: resolved.append(item)
    return resolved

def scan_source(source,config,fallback_fetcher=None):
    started=time.monotonic(); session=make_session(); base_url=source["url"].strip()
    config=dict(config or {})
    config["_source_name"]=source.get("name","")
    config["_source_group"]=source.get("group","Văn Bản TW")
    max_items=max(1,int(config.get("max_items",200))); max_pages=max(1,min(int(config.get("max_pages",1)),10))
    items=[]; page_count=0; errors=[]; fallback_used=False; http_status=None
    discovered_candidates=[]
    try:
        try:
            items,page_count,http_status=_collect_primary(session,base_url,config,max_items,max_pages,discovery_sink=discovered_candidates)
            errors.extend(config.get("_partial_errors",[]))
        except SourceFetchError as exc:
            errors.append(f"{exc.kind}: {exc}")
            http_status=exc.http_status
            # Use Google's fetch infrastructure only after a real primary transport failure.
            # An accessible page with zero matches is not treated as a network failure.
            if fallback_fetcher and config.get("apps_script_fallback",True):
                try:
                    remote=fallback_fetcher(base_url,source.get("name",""))
                    remote_status=int(remote.get("http_status",0))
                    if remote.get("status")=="ok" and 200 <= remote_status < 300 and remote.get("body"):
                        initial=SimpleNamespace(
                            url=remote.get("final_url") or base_url,
                            status_code=remote_status,
                            headers={"Content-Type":remote.get("content_type","text/html")},
                            text=remote["body"],
                            content=remote["body"].encode("utf-8",errors="replace"),
                        )
                        items,page_count,http_status=_collect_primary(
                            session,base_url,config,max_items,max_pages,initial_response=initial,discovery_sink=discovered_candidates
                        )
                        if items:
                            fallback_used=True
                            for item in items: item["retrieval_method"]="apps_script"
                    else:
                        errors.append(f"Apps Script: {remote.get('message') or 'Không lấy được nội dung'}")
                except Exception as remote_exc:
                    errors.append(f"Apps Script: {type(remote_exc).__name__}: {remote_exc}")
        # A dedicated Google News RSS discovery source is accepted only after
        # redirects resolve to explicitly allowed official domains. Its feed
        # timestamp is provenance, never an issuance date.
        if urlsplit(base_url).hostname in {"news.google.com", "news.googleusercontent.com"}:
            for item in items:
                item["source_published_date"] = item.get("published_date")
                item["published_date"] = None
                item["date_source"] = "fallback_aggregator"
            items = _resolve_aggregator_links(session, items, config)

        # RSS aggregators supplement incomplete listings, not only completely
        # failed sources. Their publication dates remain provenance only.
        primary_item_count=len(items)
        feed_supplement_used=False
        feed_urls=config.get("fallback_feed_urls",[])[:3]
        if feed_urls and len(items)<max_items:
            feed_budget=min(60,max_items-len(items))
            for feed_url in feed_urls:
                try:
                    response=fetch_response(session,feed_url,config)
                    fallback_items=parse_feed(response.content,feed_budget)
                    if fallback_items:
                        for item in fallback_items:
                            item["source_published_date"]=item.get("published_date")
                            item["published_date"]=None
                            item["date_source"]="fallback_aggregator"
                        fallback_items=_resolve_aggregator_links(session,fallback_items,config)
                        if fallback_items:
                            items.extend(fallback_items)
                            if primary_item_count:
                                feed_supplement_used=True
                            else:
                                fallback_used=True
                            feed_budget=max(0,min(60,max_items-len(items)))
                            if feed_budget<=0:
                                break
                except SourceFetchError as exc:
                    errors.append(f"Fallback {exc.kind}: {exc}")
        final_items=_deduplicate_items(items,max_items)
        if final_items:
            methods={item.get("retrieval_method") for item in final_items if item.get("retrieval_method")}
            status="Hoạt động qua Apps Script" if "apps_script" in methods else (
                "Hoạt động + RSS bổ sung" if feed_supplement_used else
                ("Hoạt động (dự phòng)" if fallback_used else "Hoạt động")
            )
            return {"items":final_items,"status":status,"http_status":http_status,"pages":page_count,
                    "duration":round(time.monotonic()-started,2),"error":"; ".join(errors)[:500],
                    "fallback_used":fallback_used,"feed_supplement_used":feed_supplement_used,
                    "primary_item_count":primary_item_count,"discovered_candidates":discovered_candidates,
                    "retrieval_method":"apps_script" if "apps_script" in methods else (
                        "direct+aggregator" if feed_supplement_used else ("aggregator" if fallback_used else "direct")
                    )}
        if errors:
            primary_kind=errors[0].split(":",1)[0]
            return {"items":[],"status":f"Lỗi: {primary_kind}"[:45],"http_status":http_status,"pages":page_count,
                    "duration":round(time.monotonic()-started,2),"error":"; ".join(errors)[:500],"fallback_used":False,
                    "discovered_candidates":discovered_candidates}
        return {"items":[],"status":"Đã truy cập, chưa tìm thấy mục","http_status":http_status,"pages":page_count,
                "duration":round(time.monotonic()-started,2),"error":"","fallback_used":False,
                "discovered_candidates":discovered_candidates}
    except Exception as exc:
        return {"items":[],"status":f"Lỗi: {type(exc).__name__}"[:45],"http_status":http_status,"pages":page_count,
                "duration":round(time.monotonic()-started,2),"error":str(exc)[:500],"fallback_used":fallback_used,
                "discovered_candidates":discovered_candidates}
    finally: session.close()
