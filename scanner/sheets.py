import time
import requests

from .config import WEB_APP_URL

API_TOKEN = __import__("os").getenv("SHEETS_API_TOKEN", "").strip()

def _post(payload,timeout=90):
    last_error=None
    for attempt in range(1,4):
        try:
            request_payload=dict(payload)
            if API_TOKEN: request_payload["token"]=API_TOKEN
            response=requests.post(WEB_APP_URL,json=request_payload,timeout=(15,timeout))
            response.raise_for_status()
            try: data=response.json()
            except ValueError as exc: raise RuntimeError(f"Apps Script trả về dữ liệu không phải JSON: {response.text[:300]}") from exc
            if data.get("status")=="error": raise RuntimeError(data.get("message","Apps Script error"))
            return data
        except (requests.Timeout,requests.ConnectionError) as exc:
            last_error=exc
            if attempt<3:
                wait=attempt*5
                print(f"[SHEETS] Kết nối Google Sheets lỗi lần {attempt}/3; thử lại sau {wait}s.")
                time.sleep(wait)
    raise RuntimeError(f"Không thể kết nối Apps Script sau 3 lần thử: {last_error}")

def get_sources_and_memory():
    data=_post({"action":"get_sources"},timeout=90)
    if data.get("status")!="ok": raise RuntimeError(f"Không lấy được danh sách nguồn: {data}")
    sources=[]
    for raw in data.get("sources") or []:
        url=str(raw.get("url") or "").strip()
        if not url: continue
        row=raw.get("row"); name=str(raw.get("name") or "").strip() or f"Nguồn dòng {row or '?'}"
        sources.append({**raw,"name":name,"url":url,"group":str(raw.get("group") or "Văn Bản TW").strip()})
    links=set(str(v).strip() for v in data.get("existingLinks",[]) if v)
    numbers=set(str(v).strip().upper() for v in data.get("existingNumbers",[]) if v)
    identities=set(str(v).strip() for v in data.get("existingIdentities",[]) if v)
    return sources,links,numbers,identities

def save_results_in_batches(new_docs,source_status,batch_size=10):
    batches=[new_docs[i:i+batch_size] for i in range(0,len(new_docs),batch_size)]
    if not batches:
        result=_post({"action":"save_results","new_docs":[],"source_status":source_status,"refresh_radar":False},timeout=90)
        if result.get("status")!="saved": raise RuntimeError(f"Apps Script chưa xác nhận lưu dữ liệu: {result}")
        return int(result.get("added",0))
    added=0
    for index,batch in enumerate(batches):
        is_last=index==len(batches)-1
        statuses=source_status if is_last else []
        result=_post({"action":"save_results","new_docs":batch,"source_status":statuses,"refresh_radar":is_last},timeout=90)
        if result.get("status")!="saved": raise RuntimeError(f"Apps Script chưa xác nhận lưu lô {index+1}: {result}")
        added+=int(result.get("added",len(batch)))
        print(f"[SHEETS] Đã đồng bộ lô {index+1}/{len(batches)}: {len(batch)} văn bản.")
    return added
