# -*- coding: utf-8 -*-
"""Trạm Tin Tức - quét toàn bộ nguồn, tối đa 5 nguồn đồng thời."""
import concurrent.futures
import os
import sys
import time
from datetime import datetime, timezone

from scanner.config import load_source_config, config_for_source
from scanner.collectors import scan_source
from scanner.normalizer import (
    extract_doc_info, classify_and_score, make_fingerprint, canonicalize_url,
    classify_document, document_identity, is_too_old,
)
from scanner.sheets import get_sources_and_memory, save_results_in_batches
from scanner.source_registry import load_sources_from_csv
from scanner.persistent_memory import load_state, is_seen, record_documents, append_history

MAX_WORKERS=5
SAVE_BATCH_SIZE=10
MAX_AGE_DAYS=60

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def append_step_summary(lines):
    path=os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path,"a",encoding="utf-8") as f: f.write("\n".join(lines)+"\n")

def main():
    started=time.monotonic()
    print("="*70); print(f"TRẠM TIN TỨC | BẮT ĐẦU: {utc_now()}"); print("="*70)
    config_data=load_source_config()
    sheet_sources,existing_links,_existing_numbers=get_sources_and_memory()
    csv_sources=load_sources_from_csv()
    if csv_sources: sources=csv_sources; registry_name="GitHub: danh_sach_nguon.csv"
    else: sources=sheet_sources; registry_name="Google Sheets (dự phòng)"
    if not sources: raise RuntimeError("Không có nguồn đang bật trong CSV hoặc Google Sheets.")
    state=load_state()
    print(f"[INIT] Nguồn: {registry_name} | Tổng nguồn: {len(sources)} | Đồng thời: {MAX_WORKERS}")
    print(f"[INIT] Bộ nhớ GitHub: {len(state['documents'])} văn bản | {len(state['urls'])} URL | Sheets: {len(existing_links)} URL")

    results_by_index={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures={pool.submit(scan_source,s,config_for_source(s,config_data)):(i,s) for i,s in enumerate(sources)}
        for future in concurrent.futures.as_completed(futures):
            i,s=futures[future]
            try: result=future.result()
            except Exception as exc: result={"items":[],"status":f"Lỗi: {type(exc).__name__}"[:45],"http_status":None,"pages":0,"duration":0,"error":str(exc)[:300]}
            results_by_index[i]=(s,result)
            print(f"[{i+1}/{len(sources)}] {s.get('name')}: {len(result['items'])} mục | {result['status']} | {result['duration']}s")

    new_docs=[]; source_status=[]; accepted_for_memory=[]
    totals={"items":0,"recognized":0,"old":0,"duplicate":0,"kept":0,"failed":0}
    recognized_by_source={}
    seen_sheet_links=set(existing_links)
    for i in range(len(sources)):
        source,result=results_by_index[i]; name=source.get("name","Nguồn không tên"); group=source.get("group","Văn Bản TW")
        totals["items"]+=len(result["items"]); recognized=0
        for item in result["items"]:
            title=item["title"]; link=canonicalize_url(item["link"]); pub=item.get("published_date")
            doc_type,number=extract_doc_info(title)
            if not doc_type: continue
            recognized+=1; totals["recognized"]+=1
            if is_too_old(title,number,MAX_AGE_DAYS,pub):
                totals["old"]+=1; continue
            category=classify_document(title,name,doc_type,number,link)
            keep,priority=classify_and_score(title,name,doc_type,number,group,pub)
            if not keep: continue
            totals["kept"]+=1
            identity=document_identity(number,title,name,link)
            if link in seen_sheet_links or is_seen(state,identity,link):
                totals["duplicate"]+=1; continue
            doc={"priority":priority,"doc_type":doc_type,"agency":name,"title":title,"doc_number":number,
                 "link":link,"fingerprint":make_fingerprint(number,title),"category":category,
                 "published_date":pub or ""}
            new_docs.append(doc); accepted_for_memory.append({**doc,"identity":identity})
            seen_sheet_links.add(link)
        recognized_by_source[i]=recognized
        if result["error"]: totals["failed"]+=1
        status=result["status"]
        if not result["error"] and result["items"]: status="Hoạt động" if recognized else "Đã truy cập, chưa nhận diện văn bản"
        if source.get("row") is not None: source_status.append({"row":source["row"],"count":recognized,"status":status[:45]})

    new_docs.sort(key=lambda d:(d["priority"],d["title"].casefold()))
    print(f"[RESULT] Thu thập {totals['items']} | Nhận diện {totals['recognized']} | Quá 60 ngày {totals['old']} | Trùng {totals['duplicate']} | Gửi mới {len(new_docs)} | Nguồn lỗi {totals['failed']}")
    # Chỉ ghi vào bộ nhớ bền vững sau khi Google Sheets xác nhận đồng bộ thành công.
    saved=save_results_in_batches(new_docs,source_status,SAVE_BATCH_SIZE)
    record_documents(state,accepted_for_memory)
    duration=round(time.monotonic()-started,2)
    summary={"finished_at":utc_now(),"sources":len(sources),"collected":totals["items"],"recognized":totals["recognized"],
             "older_than_60_days":totals["old"],"duplicates":totals["duplicate"],"new_to_sheets":saved,
             "failed_sources":totals["failed"],"duration_seconds":duration}
    append_history(summary)
    report=["## Kết quả quét Trạm Tin Tức",f"- Hoàn tất: **{utc_now()}**",f"- Nguồn: **{len(sources)}**",
            f"- Tổng mục thu thập: **{totals['items']}**",f"- Nhận diện văn bản: **{totals['recognized']}**",
            f"- Loại do quá 60 ngày: **{totals['old']}**",f"- Loại do trùng: **{totals['duplicate']}**",
            f"- Văn bản mới đồng bộ Google Sheets: **{saved}**",f"- Bộ nhớ GitHub: **{len(state['documents'])} văn bản**",
            f"- Nguồn lỗi: **{totals['failed']}/{len(sources)}**",f"- Thời gian: **{duration} giây**","",
            "| Nguồn | Mục thu thập | Văn bản nhận diện | Trạng thái |","|---|---:|---:|---|"]
    for i in range(len(sources)):
        s,r=results_by_index[i]; report.append(f"| {s.get('name','')[:50]} | {len(r['items'])} | {recognized_by_source[i]} | {r['status']} |")
    append_step_summary(report); print(f"[DONE] Hoàn tất trong {duration} giây.")

if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}",file=sys.stderr); raise
