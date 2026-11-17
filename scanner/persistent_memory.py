# -*- coding: utf-8 -*-
"""Persistent cross-run memory for Trạm Tin Tức."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
STATE_PATH=ROOT/"data"/"seen_documents.json"
HISTORY_PATH=ROOT/"data"/"scan_history.json"

def load_state():
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    if not STATE_PATH.exists():
        return {"version":1,"documents":{},"urls":{}}
    try:
        data=json.loads(STATE_PATH.read_text(encoding="utf-8"))
        data.setdefault("documents",{}); data.setdefault("urls",{})
        return data
    except Exception as exc:
        raise RuntimeError(f"Không đọc được bộ nhớ chống trùng {STATE_PATH}: {exc}") from exc

def is_seen(state,identity,url):
    return identity in state["documents"] or url in state["urls"]

def record_documents(state,docs):
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for doc in docs:
        identity=doc["identity"]; url=doc["link"]
        state["documents"].setdefault(identity,{
            "title":doc["title"],"doc_number":doc["doc_number"],
            "agency":doc["agency"],"category":doc["category"],
            "first_seen":now,"link":url,
        })
        state["documents"][identity]["last_seen"]=now
        state["urls"][url]=identity
    STATE_PATH.write_text(json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")

def append_history(summary):
    HISTORY_PATH.parent.mkdir(parents=True,exist_ok=True)
    try: history=json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else []
    except Exception: history=[]
    history.append(summary)
    HISTORY_PATH.write_text(json.dumps(history[-1000:],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
