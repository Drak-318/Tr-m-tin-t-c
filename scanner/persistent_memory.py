# -*- coding: utf-8 -*-
"""GitHub is the source of truth for scan memory, review queue and pending exports."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .normalizer import canonicalize_url

ROOT=Path(__file__).resolve().parent.parent
DATA_DIR=ROOT/"data"
STATE_PATH=DATA_DIR/"seen_documents.json"
HISTORY_PATH=DATA_DIR/"scan_history.json"
REVIEW_QUEUE_PATH=DATA_DIR/"review_queue.json"
EXPORT_QUEUE_PATH=DATA_DIR/"sheets_export_queue.json"


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
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\\n",encoding="utf-8")
    temp.replace(path)


def load_state():
    state=_read_json(STATE_PATH,{"version":1,"documents":{},"urls":{}})
    state.setdefault("version",1)
    state.setdefault("documents",{})
    state.setdefault("urls",{})
    return state


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
        current.update({k:v for k,v in doc.items() if v not in (None,"")})
        current["link"]=url
        current.setdefault("first_seen",now)
        current["last_seen"]=now
        current["status"]="pending"
        current["attempts"]=int(current.get("attempts",0))
        items[url]=current
    queue["updated_at"]=now
    _write_json(REVIEW_QUEUE_PATH,queue)
    return len(items)


def load_review_queue():
    queue=_read_json(REVIEW_QUEUE_PATH,{"version":1,"items":{}})
    return queue.get("items",{})


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
