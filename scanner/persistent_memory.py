# -*- coding: utf-8 -*-
"""GitHub is the source of truth for scan memory, review queue and pending exports."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .normalizer import canonicalize_url

ROOT=Path(__file__).resolve().parent.parent
DATA_DIR=ROOT/"data"
STATE_PATH=DATA_DIR/"seen_documents.json"
HISTORY_PATH=DATA_DIR/"scan_history.json"
REVIEW_QUEUE_PATH=DATA_DIR/"review_queue.json"
EXPORT_QUEUE_PATH=DATA_DIR/"sheets_export_queue.json"
SOURCE_RETRY_QUEUE_PATH=DATA_DIR/"source_retry_queue.json"


def _read_json(path, default):
    if not path.exists():
        return default
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, type(default)) else default
    except Exception as exc:
        raise RuntimeError(f"Không đọc được dữ liệu {path}: {exc}") from exc


def _write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    temp.replace(path)


def load_state():
    state=_read_json(STATE_PATH,{"version":1,"documents":{},"urls":{}})
    state.setdefault("version",1)
    state.setdefault("documents",{})
    state.setdefault("urls",{})
    return state


class RunSeenIndex:
    """Track documents accepted earlier in the same scan, before disk persistence."""
    def __init__(self, state=None):
        state = state or {}
        self.identities = set((state.get("documents") or {}).keys())
        self.urls = {
            canonicalize_url(url)
            for url in (state.get("urls") or {}).keys()
            if canonicalize_url(url)
        }

    def contains(self, identity, url):
        canonical = canonicalize_url(url)
        return bool((identity and identity in self.identities) or (canonical and canonical in self.urls))

    def add(self, identity, url):
        canonical = canonicalize_url(url)
        if identity:
            self.identities.add(identity)
        if canonical:
            self.urls.add(canonical)


def is_seen(state,identity,url):
    canonical=canonicalize_url(url)
    return identity in state["documents"] or canonical in state["urls"]


def record_documents(state,docs):
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for doc in docs:
        identity=doc["identity"]
        url=canonicalize_url(doc["link"])
        state["documents"].setdefault(identity,{
            "title":doc["title"],"doc_number":doc["doc_number"],
            "agency":doc["agency"],"category":doc["category"],
            "first_seen":now,"link":url,
        })
        state["documents"][identity]["last_seen"]=now
        state["urls"][url]=identity
    _write_json(STATE_PATH,state)


def enqueue_review_documents(docs):
    queue=_read_json(REVIEW_QUEUE_PATH,{"version":1,"items":{}})
    items=queue.setdefault("items",{})
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for doc in docs:
        url=canonicalize_url(doc.get("link",""))
        if not url:
            continue
        current=items.get(url,{})
        previous=dict(current)
        current.update({k:v for k,v in doc.items() if v not in (None,"")})
        # A fresh scan can rediscover the same URL without a date. Do not let
        # that weaker listing data erase stronger evidence already verified
        # from the detail page in an earlier pass.
        verified_states={"date_found","excluded_old","already_seen","verified_included","needs_manual_review","manual_review"}
        if previous.get("verification_status") in verified_states:
            for field in ("verified_date","date_basis","date_evidence","last_checked","last_error","verification_status","status"):
                if previous.get(field) not in (None,""):
                    current[field]=previous[field]
        current["link"]=url
        current.setdefault("first_seen",now)
        current["last_seen"]=now
        current["attempts"]=int(current.get("attempts",0))
        if current.get("verification_status") in {"date_found","excluded_old","already_seen","verified_included","needs_manual_review","manual_review"}:
            current["status"]=current.get("status") or current.get("verification_status")
        else:
            current["status"]="pending"
        items[url]=current
    queue["updated_at"]=now
    _write_json(REVIEW_QUEUE_PATH,queue)
    return len(items)


def load_review_queue():
    queue=_read_json(REVIEW_QUEUE_PATH,{"version":1,"items":{}})
    return queue.get("items",{})

def update_review_document(link,updates):
    url=canonicalize_url(link)
    if not url:
        return False
    queue=_read_json(REVIEW_QUEUE_PATH,{"version":1,"items":{}})
    current=queue.setdefault("items",{}).get(url)
    if current is None:
        return False
    current.update(updates)
    current["last_checked"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
    queue["updated_at"]=current["last_checked"]
    _write_json(REVIEW_QUEUE_PATH,queue)
    return True


def pending_review_documents(limit=40,max_attempts=3,retry_manual_after_days=7):
    """Select undated records, including failed records after a retry cooldown."""
    items=load_review_queue()
    eligible=[]
    retry_cutoff=datetime.now(timezone.utc)-timedelta(days=max(1,int(retry_manual_after_days)))

    def is_stale(row):
        raw=row.get("last_checked") or row.get("last_seen") or row.get("first_seen")
        if not raw:
            return True
        try:
            checked=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
            if checked.tzinfo is None:
                checked=checked.replace(tzinfo=timezone.utc)
            return checked < retry_cutoff
        except (TypeError,ValueError):
            return True

    for url,row in items.items():
        status=row.get("status","pending")
        attempts=int(row.get("attempts",0))
        if status in {"pending","fetch_error","not_found"} and attempts<max_attempts:
            eligible.append({**row,"link":url})
        elif status in {"fetch_error","not_found","manual_review"} and is_stale(row):
            # A manual_review caused by a failed fetch is retried after cooldown.
            # needs_manual_review means the page was fetched but its document type
            # remains ambiguous; that record should stay for human review.
            if status!="manual_review" or row.get("verification_status")=="manual_review":
                eligible.append({**row,"link":url,"retry_after_cooldown":True})
    eligible.sort(key=lambda row:(int(row.get("attempts",0)),str(row.get("first_seen",""))))
    return eligible[:max(0,int(limit))]




def enqueue_sheets_export(payload):
    queue=_read_json(EXPORT_QUEUE_PATH,{"version":1,"items":[]})
    items=queue.setdefault("items",[])
    # Each scan is a separate export unit; preserve records until Sheets confirms save.
    items.append({"queued_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),**payload})
    _write_json(EXPORT_QUEUE_PATH,queue)
    return len(items)


def load_sheets_export_queue():
    queue=_read_json(EXPORT_QUEUE_PATH,{"version":1,"items":[]})
    return queue.get("items",[])


def clear_sheets_export_queue():
    _write_json(EXPORT_QUEUE_PATH,{"version":1,"items":[],"updated_at":datetime.now(timezone.utc).isoformat(timespec="seconds")})


def append_history(summary):
    history=_read_json(HISTORY_PATH,[])
    history.append(summary)
    _write_json(HISTORY_PATH,history[-1000:])


def load_source_retry_queue():
    """Return failed source records keyed by canonical source URL."""
    queue=_read_json(SOURCE_RETRY_QUEUE_PATH,{"version":1,"items":{}})
    return queue.get("items",{})


def record_source_scan_result(source,result):
    """Persist source-level failures for automatic retry; resolve recovered sources."""
    url=canonicalize_url(source.get("url",""))
    if not url:
        return len(load_source_retry_queue())
    queue=_read_json(SOURCE_RETRY_QUEUE_PATH,{"version":1,"items":{}})
    items=queue.setdefault("items",{})
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    failed=bool(result.get("error")) and not result.get("fallback_used")
    if failed:
        previous=items.get(url,{})
        same_failure_streak=previous.get("status")=="retry_pending"
        attempts=int(previous.get("attempts",0))+1 if same_failure_streak else 1
        first_failed_at=previous.get("first_failed_at",now) if same_failure_streak else now
        items[url]={
            "name":source.get("name",""),"url":url,"group":source.get("group",""),
            "status":"retry_pending","attempts":attempts,
            "first_failed_at":first_failed_at,"last_failed_at":now,
            "last_error":str(result.get("error",""))[:500],
            "last_status":str(result.get("status",""))[:100],
            "http_status":result.get("http_status"),
            "last_items_collected":len(result.get("items",[])),
        }
    elif url in items:
        previous=items[url]
        items[url]={**previous,"status":"recovered","recovered_at":now,
                    "last_status":str(result.get("status",""))[:100],"last_error":""}
    recovered=sorted(((k,v) for k,v in items.items() if v.get("status")=="recovered"),
                     key=lambda pair:str(pair[1].get("recovered_at","")),reverse=True)
    pending={k:v for k,v in items.items() if v.get("status")!="recovered"}
    queue["items"]={**pending,**dict(recovered[:200])}
    queue["updated_at"]=now
    _write_json(SOURCE_RETRY_QUEUE_PATH,queue)
    return len(pending)


def pending_source_retries(limit=20):
    items=load_source_retry_queue()
    rows=[row for row in items.values() if row.get("status")=="retry_pending"]
    rows.sort(key=lambda row:(str(row.get("last_failed_at","")),int(row.get("attempts",0))))
    return rows[:max(0,int(limit))]

def filter_sources_due_for_retry(sources, now=None):
    """Throttle repeated failures with exponential backoff without deleting sources.

    Healthy/new sources are always scanned. Failed sources are retried after
    5m, 15m, 30m, 1h, 2h, then at most every 6h.
    """
    current=now or datetime.now(timezone.utc)
    retry_items=load_source_retry_queue()
    delays=[5,15,30,60,120,360]
    due=[]
    deferred=[]
    for source in sources:
        url=canonicalize_url(source.get("url",""))
        record=retry_items.get(url,{})
        if record.get("status")!="retry_pending":
            due.append(source)
            continue
        try:
            attempts=max(1,int(record.get("attempts",1)))
            delay=delays[min(attempts-1,len(delays)-1)]
            failed_at=datetime.fromisoformat(str(record.get("last_failed_at","")).replace("Z","+00:00"))
            if failed_at.tzinfo is None:
                failed_at=failed_at.replace(tzinfo=timezone.utc)
            ready_at=failed_at+timedelta(minutes=delay)
            if current >= ready_at:
                due.append(source)
            else:
                deferred.append({**source,"retry_after":ready_at.isoformat(timespec="seconds"),
                                 "retry_delay_minutes":delay,"retry_attempts":attempts})
        except (TypeError,ValueError,OverflowError):
            # Corrupt or legacy retry metadata must never block a source forever.
            due.append(source)
    return due,deferred
