# -*- coding: utf-8 -*-
"""Trạm Tin Tức - quét toàn bộ nguồn, tối đa 5 nguồn đồng thời."""
import concurrent.futures
import os
import sys
import time
from datetime import datetime, timezone

from scanner.config import load_source_config, config_for_source, WEB_APP_URL
from scanner.collectors import scan_source
from scanner.normalizer import (
    extract_doc_info, classify_and_score, make_fingerprint, canonicalize_url,
    classify_document, document_identity, is_too_old, has_document_date,
)
from scanner.sheets import get_sources_and_memory, save_results_in_batches, fetch_source_via_apps_script
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
    sheet_sources,existing_links,_existing_numbers,existing_identities=get_sources_and_memory()
    csv_sources=load_sources_from_csv()
    if csv_sources:
        sheet_rows={canonicalize_url(s["url"]):s for s in sheet_sources}
        sources=[]
        for source in csv_sources:
            matched=sheet_rows.get(canonicalize_url(source["url"]))
            sources.append({**source,"row":matched.get("row") if matched else None})
        registry_name="GitHub: danh_sach_nguon.csv (đối chiếu dòng Google Sheets để cập nhật trạng thái)"
    else:
        sources=sheet_sources
        registry_name="Google Sheets (dự phòng)"
    if not sources: raise RuntimeError("Không có nguồn đang bật trong CSV hoặc Google Sheets.")
    state=load_state()
    print(f"[INIT] Nguồn: {registry_name} | Tổng nguồn: {len(sources)} | Đồng thời: {MAX_WORKERS}")
    print(f"[INIT] Bộ nhớ GitHub: {len(state['documents'])} văn bản | {len(state['urls'])} URL | Sheets: {len(existing_links)} URL")

    results_by_index={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures={pool.submit(scan_source,s,config_for_source(s,config_data),fetch_source_via_apps_script if WEB_APP_URL else None):(i,s) for i,s in enumerate(sources)}
        for future in concurrent.futures.as_completed(futures):
            i,s=futures[future]
            try: result=future.result()
            except Exception as exc: result={"items":[],"status":f"Lỗi: {type(exc).__name__}"[:45],"http_status":None,"pages":0,"duration":0,"error":str(exc)[:500],"fallback_used":False}
            results_by_index[i]=(s,result)
            detail=f" | Chi tiết: {result['error']}" if result.get("error") else ""
            fallback=" | Có dùng nguồn dự phòng" if result.get("fallback_used") else ""
            print(f"[{i+1}/{len(sources)}] {s.get('name')}: {len(result['items'])} mục | {result['status']} | {result['duration']}s{fallback}{detail}")

    new_docs=[]; review_docs=[]; source_status=[]; accepted_for_memory=[]
    totals={"items":0,"recognized":0,"old":0,"unknown_date":0,"duplicate":0,"kept":0,"failed":0,"fallback_sources":0}
    recognized_by_source={}
    seen_sheet_links=set(existing_links)
    seen_sheet_identities=set(existing_identities)
    for i in range(len(sources)):
        source,result=results_by_index[i]; name=source.get("name","Nguồn không tên"); group=source.get("group","Văn Bản TW")
        totals["items"]+=len(result["items"])
        if result.get("fallback_used"): totals["fallback_sources"]+=1
        recognized=0
        for item in result["items"]:
            title=item["title"]; link=canonicalize_url(item["link"]); pub=item.get("published_date")
            doc_type,number=extract_doc_info(title)
            if not doc_type: continue
            recognized+=1; totals["recognized"]+=1
            if not has_document_date(title,pub):
                totals["unknown_date"]+=1
                review_docs.append({"agency":name,"title":title,"doc_number":number,"link":link,
                                    "published_date":"","source_published_date":item.get("source_published_date",""),
                                    "reason":"Chưa có ngày ban hành xác minh được; ngày từ nguồn tổng hợp không được dùng thay ngày ban hành."})
                continue
            if is_too_old(title,number,MAX_AGE_DAYS,pub):
                totals["old"]+=1; continue
            category=classify_document(title,name,doc_type,number,link)
            keep,priority=classify_and_score(title,name,doc_type,number,group,pub)
            if not keep: continue
            totals["kept"]+=1
            identity=document_identity(number,title,name,link)
            if link in seen_sheet_links or identity in seen_sheet_identities or is_seen(state,identity,link):
                totals["duplicate"]+=1; continue
            doc={"priority":priority,"doc_type":doc_type,"agency":name,"title":title,"doc_number":number,
                 "link":link,"fingerprint":make_fingerprint(number,title),"category":category,
                 "identity":identity,"published_date":pub or ""}
            new_docs.append(doc); accepted_for_memory.append({**doc,"identity":identity})
            seen_sheet_links.add(link)
            seen_sheet_identities.add(identity)
        recognized_by_source[i]=recognized
        if result["error"] and not result.get("fallback_used"): totals["failed"]+=1
        status=result["status"]
        if not result["error"] and result["items"]: status="Hoạt động" if recognized else "Đã truy cập, chưa nhận diện văn bản"
        if result.get("fallback_used"): status="Hoạt động qua nguồn dự phòng"
        if source.get("row") is not None: source_status.append({"row":source["row"],"count":recognized,"status":status[:45]})

    new_docs.sort(key=lambda d:(d["priority"],d["title"].casefold()))
    print(f"[RESULT] Thu thập {totals['items']} | Nhận diện {totals['recognized']} | Quá 60 ngày {totals['old']} | Chưa rõ ngày {totals['unknown_date']} | Trùng {totals['duplicate']} | Gửi mới {len(new_docs)} | Nguồn lỗi {totals['failed']} | Có nguồn dự phòng {totals['fallback_sources']}")
    saved=save_results_in_batches(new_docs,source_status,SAVE_BATCH_SIZE,review_docs)
    record_documents(state,accepted_for_memory)
    duration=round(time.monotonic()-started,2)
    summary={"finished_at":utc_now(),"sources":len(sources),"collected":totals["items"],"recognized":totals["recognized"],
             "older_than_60_days":totals["old"],"unknown_date":totals["unknown_date"],"duplicates":totals["duplicate"],
             "new_to_sheets":saved,"failed_sources":totals["failed"],"fallback_sources":totals["fallback_sources"],"duration_seconds":duration}
    append_history(summary)
    report=["## Kết quả quét Trạm Tin Tức",f"- Hoàn tất: **{utc_now()}**",f"- Nguồn: **{len(sources)}**",
            f"- Tổng mục thu thập: **{totals['items']}**",f"- Nhận diện văn bản: **{totals['recognized']}**",
            f"- Loại do quá 60 ngày: **{totals['old']}**",f"- Chuyển sang danh sách cần xác minh ngày: **{totals['unknown_date']}**",
            f"- Loại do trùng: **{totals['duplicate']}**",f"- Văn bản mới đồng bộ Google Sheets: **{saved}**",
            f"- Bộ nhớ GitHub: **{len(state['documents'])} văn bản**",f"- Nguồn lỗi: **{totals['failed']}/{len(sources)}**",
            f"- Nguồn có dùng dự phòng: **{totals['fallback_sources']}**",f"- Thời gian: **{duration} giây**","",
            "| Nguồn | Mục thu thập | Văn bản nhận diện | Trạng thái |","|---|---:|---:|---|"]
    for i in range(len(sources)):
        s,r=results_by_index[i]; report.append(f"| {s.get('name','')[:50]} | {len(r['items'])} | {recognized_by_source[i]} | {r['status']} |")
    append_step_summary(report); print(f"[DONE] Hoàn tất trong {duration} giây.")

if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}",file=sys.stderr); raise
