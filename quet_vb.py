# -*- coding: utf-8 -*-
"""Trạm Tin Tức - quét toàn bộ nguồn, tối đa 5 nguồn đồng thời."""
import concurrent.futures
import json
from pathlib import Path
import os
import sys
import time
from datetime import datetime, timezone

from scanner.config import load_source_config, config_for_source, WEB_APP_URL
from scanner.collectors import scan_source, verify_document_detail_date
from scanner.normalizer import (
    extract_doc_info, classify_and_score, make_fingerprint, canonicalize_url,
    classify_document, document_identity, is_too_old, has_document_date, resolve_document_date,
)
from scanner.sheets import save_results_in_batches, fetch_source_via_apps_script
from scanner.source_registry import load_sources_from_csv
from scanner.persistent_memory import (load_state, is_seen, record_documents, append_history,
    enqueue_review_documents, enqueue_sheets_export, load_sheets_export_queue, clear_sheets_export_queue, load_review_queue, pending_review_documents, update_review_document)
from scanner.relationship_tracer import collect_local_document_relations, merge_relationships, resolve_reference_candidates

MAX_WORKERS=5
SAVE_BATCH_SIZE=50
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
    sources=load_sources_from_csv()
    if not sources: raise RuntimeError("Không có nguồn đang bật trong danh_sach_nguon.csv trên GitHub.")
    state=load_state()
    print(f"[INIT] Nguồn: GitHub/danh_sach_nguon.csv | Tổng nguồn: {len(sources)} | Đồng thời: {MAX_WORKERS}")
    print(f"[INIT] Bộ nhớ GitHub: {len(state['documents'])} văn bản | {len(state['urls'])} URL")

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
            feed_note=" | Có bổ sung RSS" if result.get("feed_supplement_used") else ""
            print(f"[{i+1}/{len(sources)}] {s.get('name')}: {len(result['items'])} mục | {result['status']} | {result['duration']}s{fallback}{feed_note}{detail}")

    # Trace references from a bounded sample of local authority detail pages.
    local_candidates=[]
    for source,result in results_by_index.values():
        if str(source.get("group","")).strip().casefold() in {"địa phương","công an"}:
            for item in result.get("items",[]):
                item_type,item_number=extract_doc_info(item.get("title",""))
                # Exclude local news posts; trace only identifiable legal-document titles.
                if item_type and item_number and item_number != "Đang cập nhật":
                    local_candidates.append({"title":item.get("title",""),"link":item.get("link",""),
                                             "agency":source.get("name",""),"doc_type":item_type,
                                             "doc_number":item_number})
    local_candidates.sort(key=lambda row: row.get("link",""))
    relation_path=Path("data/document_relationships.json")
    cursor_path=Path("data/relationship_scan_state.json")
    try:
        existing_relations=json.loads(relation_path.read_text(encoding="utf-8")) if relation_path.exists() else []
        if not isinstance(existing_relations,list): existing_relations=[]
        existing_relations=[
            row for row in existing_relations
            if row.get("source_doc_number") and row.get("source_doc_number") != "Đang cập nhật"
        ]
    except Exception:
        existing_relations=[]
    try:
        cursor_state=json.loads(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else {}
        cursor=max(0,int(cursor_state.get("next_candidate",0)))
    except Exception:
        cursor_state={}; cursor=0
    if local_candidates:
        cursor %= len(local_candidates)
        rotated=local_candidates[cursor:]+local_candidates[:cursor]
        selected=rotated[:8]
        next_cursor=(cursor+len(selected)) % len(local_candidates)
    else:
        selected=[]; next_cursor=0
    discovered_relations=collect_local_document_relations(
        selected,
        fallback_fetcher=fetch_source_via_apps_script if WEB_APP_URL else None,
        limit=8,
    )
    known_documents=list(state.get("documents",{}).values())
    for source,result in results_by_index.values():
        for item in result.get("items",[]):
            doc_type,doc_number=extract_doc_info(item.get("title",""))
            if doc_type and doc_number and doc_number != "Đang cập nhật":
                known_documents.append({"title":item.get("title",""),"doc_type":doc_type,
                                        "doc_number":doc_number,"agency":source.get("name",""),
                                        "link":item.get("link","")})
    relation_rows=resolve_reference_candidates(
        merge_relationships(existing_relations,discovered_relations),known_documents
    )
    relation_path.parent.mkdir(parents=True,exist_ok=True)
    relation_path.write_text(json.dumps(relation_rows,ensure_ascii=False,indent=2),encoding="utf-8")
    cursor_path.write_text(json.dumps({"next_candidate":next_cursor},indent=2),encoding="utf-8")
    relation_matched=sum(1 for row in relation_rows if row.get("resolution_status")=="found_in_scan_index")
    relation_ambiguous=sum(1 for row in relation_rows if row.get("resolution_status")=="ambiguous_multiple_matches")
    print(f"[RELATIONS] Kiểm tra {len(selected)} trang địa phương (luân phiên); phát hiện {len(discovered_relations)} quan hệ mới; tổng lưu {len(relation_rows)}; tìm thấy trong kho quét {relation_matched}; số hiệu còn mơ hồ {relation_ambiguous}.")

    new_docs=[]; review_docs=[]; source_status=[]; accepted_for_memory=[]
    existing_review=load_review_queue()
    existing_review_urls=set(existing_review)
    backfilled_review_docs=0
    # Đưa các hồ sơ chưa rõ ngày đã tích lũy từ những lượt quét trước vào
    # bảng kết quả một lần; không để chúng chỉ nằm trong hàng đợi nội bộ.
    for review_url,row in existing_review.items():
        status=row.get("status","pending")
        if row.get("exported_to_sheets"):
            continue
        if status in {"excluded_old","already_seen"}:
            continue
        title=row.get("title","")
        agency=row.get("agency","")
        number=row.get("doc_number","")
        doc_type,_=extract_doc_info(title)
        if not doc_type:
            if "dự thảo" in title.casefold():
                doc_type="Dự thảo"
            else:
                doc_type="Văn bản khác"
        identity=document_identity(number,title,agency,review_url)
        # Do not use the old imported seen-memory to suppress backfill here:
        # the Sheets API will idempotently skip rows already in the final table.
        keep,priority=classify_and_score(title,agency,doc_type,number,"",row.get("verified_date") or None)
        if not keep:
            continue
        verified_date=row.get("verified_date","")
        new_docs.append({"priority":priority,"doc_type":doc_type,"agency":agency,"title":title,
                         "doc_number":number,"link":review_url,"fingerprint":make_fingerprint(number,title),
                         "category":classify_document(title,agency,doc_type,number,review_url),
                         "identity":identity,"published_date":verified_date,
                         "document_date":verified_date,"date_basis":row.get("date_basis","unknown"),
                         "date_status":"Đã xác minh ngày" if verified_date else "Chưa xác minh ngày - giữ lại hậu kiểm"})
        backfilled_review_docs+=1
    if backfilled_review_docs:
        print(f"[BACKFILL] Đưa {backfilled_review_docs} hồ sơ chờ xác minh cũ vào bảng kết quả.")
    totals={"items":0,"recognized":0,"old":0,"unknown_date":0,"duplicate":0,"kept":0,"failed":0,"fallback_sources":0,"feed_supplements":0}
    recognized_by_source={}
    for i in range(len(sources)):
        source,result=results_by_index[i]; name=source.get("name","Nguồn không tên"); group=source.get("group","Văn Bản TW")
        totals["items"]+=len(result["items"])
        if result.get("fallback_used"): totals["fallback_sources"]+=1
        if result.get("feed_supplement_used"): totals["feed_supplements"]+=1
        recognized=0
        for item in result["items"]:
            title=item["title"]; link=canonicalize_url(item["link"]); pub=item.get("published_date")
            doc_type,number=extract_doc_info(title)
            # Structured source rows may provide the official number/type in
            # separate table columns instead of embedding them in the link text.
            doc_type=item.get("doc_type") or doc_type
            number=item.get("doc_number") or number
            if not doc_type: continue
            recognized+=1; totals["recognized"]+=1
            category=classify_document(title,name,doc_type,number,link)
            if not has_document_date(title,pub):
                # Không loại văn bản chỉ vì thiếu ngày. Đưa vào bảng kết quả
                # ngay ở lượt phát hiện đầu tiên và đồng thời lưu hàng đợi
                # GitHub để hậu kiểm/xác minh ngày ở các lượt sau.
                totals["unknown_date"]+=1
                review_docs.append({"agency":name,"title":title,"doc_number":number,"link":link,
                                    "published_date":"","source_published_date":item.get("source_published_date",""),
                                    "date_basis":"unknown","date_source":item.get("date_source",""),
                                    "reason":"Chưa có ngày xác minh; giữ lại để hậu kiểm.","source_group":group})
                if link not in existing_review_urls and not is_seen(state,document_identity(number,title,name,link),link):
                    keep,priority=classify_and_score(title,name,doc_type,number,group,None)
                    if keep:
                        identity=document_identity(number,title,name,link)
                        new_docs.append({"priority":priority,"doc_type":doc_type,"agency":name,"title":title,
                                         "doc_number":number,"link":link,"fingerprint":make_fingerprint(number,title),
                                         "category":category,"identity":identity,"published_date":"",
                                         "document_date":"","date_basis":"unknown",
                                         "date_status":"Chưa xác minh ngày - giữ lại hậu kiểm"})
                        totals["kept"]+=1
                        existing_review_urls.add(link)
                continue
            # Có ngày thì mới áp dụng bộ lọc 60 ngày; ưu tiên ngày ban hành.
            if is_too_old(title,number,MAX_AGE_DAYS,pub):
                totals["old"]+=1; continue
            keep,priority=classify_and_score(title,name,doc_type,number,group,pub)
            if not keep: continue
            totals["kept"]+=1
            identity=document_identity(number,title,name,link)
            if is_seen(state,identity,link):
                totals["duplicate"]+=1; continue
            resolved_date,date_basis=resolve_document_date(title,pub)
            doc={"priority":priority,"doc_type":doc_type,"agency":name,"title":title,"doc_number":number,
                 "link":link,"fingerprint":make_fingerprint(number,title),"category":category,
                 "identity":identity,"published_date":pub or "",
                 "document_date":resolved_date.strftime("%Y-%m-%d") if resolved_date else "",
                 "date_basis":date_basis,"source_published_date":item.get("source_published_date","")}
            new_docs.append(doc); accepted_for_memory.append({**doc,"identity":identity})
        recognized_by_source[i]=recognized
        if result["error"] and not result.get("fallback_used"): totals["failed"]+=1
        status=result["status"]
        if not result["error"] and result["items"]: status="Hoạt động" if recognized else "Đã truy cập, chưa nhận diện văn bản"
        if result.get("fallback_used"): status="Hoạt động qua nguồn dự phòng"
        if source.get("row") is not None: source_status.append({"row":source["row"],"count":recognized,"status":status[:45]})

    # Recheck a small, bounded batch of previously undated documents on their detail pages.
    # This is deliberately limited per run so source collection remains the priority.
    review_candidates=pending_review_documents(limit=40,max_attempts=3,retry_manual_after_days=7)
    detail_stats={"checked":0,"dated":0,"new":0,"old":0,"errors":0}
    def check_review_item(row):
        return row,verify_document_detail_date(row.get("link",""),{"timeout_connect":6,"timeout_read":12})
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for row,result in pool.map(check_review_item,review_candidates):
            detail_stats["checked"]+=1
            attempts=int(row.get("attempts",0))+1
            update={"attempts":attempts,"last_error":result.get("error",""),
                    "date_evidence":result.get("evidence","")}
            if result.get("date"):
                detail_stats["dated"]+=1
                date_value=result["date"]
                basis=result.get("basis","unknown")
                title=row.get("title","")
                number=row.get("doc_number","")
                agency=row.get("agency","")
                doc_type,extracted_number=extract_doc_info(title)
                if (not number or number=="Đang cập nhật") and extracted_number:
                    number=extracted_number
                update.update({"verified_date":date_value,"date_basis":basis,
                               "verification_status":"date_found"})
                if is_too_old(title,number,MAX_AGE_DAYS,date_value):
                    detail_stats["old"]+=1
                    update.update({"status":"excluded_old","verification_status":"excluded_old"})
                elif not doc_type:
                    update.update({"status":"manual_review","verification_status":"needs_manual_review"})
                else:
                    category=classify_document(title,agency,doc_type,number,row.get("link",""))
                    keep,priority=classify_and_score(title,agency,doc_type,number,row.get("source_group",""),date_value)
                    identity=document_identity(number,title,agency,row.get("link",""))
                    if not keep:
                        detail_stats["old"]+=1
                        update.update({"status":"excluded_old","verification_status":"excluded_old"})
                    elif is_seen(state,identity,row.get("link","")):
                        update.update({"status":"already_seen","verification_status":"already_seen"})
                    else:
                        doc={"priority":priority,"doc_type":doc_type,"agency":agency,"title":title,
                             "doc_number":number,"link":canonicalize_url(row.get("link","")),
                             "fingerprint":make_fingerprint(number,title),"category":category,
                             "identity":identity,"published_date":date_value,
                             "document_date":date_value,"date_basis":basis,
                             "date_evidence":result.get("evidence","")}
                        new_docs.append(doc)
                        accepted_for_memory.append(doc)
                        detail_stats["new"]+=1
                        update.update({"status":"verified_included","verification_status":"verified_included"})
            else:
                detail_stats["errors"]+=1 if result.get("error") else 0
                state_name="fetch_error" if result.get("error") else "not_found"
                final_status="manual_review" if attempts>=3 else state_name
                update.update({"status":final_status,"verification_status":"manual_review" if attempts>=3 else state_name})
            update_review_document(row.get("link",""),update)
    if detail_stats["checked"]:
        print(f"[DATE-RECHECK] Kiểm tra {detail_stats['checked']} trang chi tiết | "
              f"Tìm thấy ngày {detail_stats['dated']} | Đưa vào danh sách mới {detail_stats['new']} | "
              f"Quá hạn {detail_stats['old']} | Lỗi/chưa rõ {detail_stats['errors']}.")

    new_docs.sort(key=lambda d:(d["priority"],d["title"].casefold()))
    print(f"[RESULT] Thu thập {totals['items']} | Nhận diện {totals['recognized']} | Quá 60 ngày {totals['old']} | Chưa rõ ngày {totals['unknown_date']} | Trùng {totals['duplicate']} | Gửi mới {len(new_docs)} | Nguồn lỗi {totals['failed']} | Có nguồn dự phòng {totals['fallback_sources']}")
    # Queue export and review work before marking documents as seen. This prevents
    # a crash between memory-write and export-queue-write from losing new records.
    review_total=enqueue_review_documents(review_docs) if review_docs else len(load_review_queue())
    export_payload={"new_docs":new_docs,"source_status":source_status,"review_docs":review_docs}
    if new_docs or source_status or review_docs:
        enqueue_sheets_export(export_payload)
    record_documents(state,accepted_for_memory)
    saved=0
    review_saved=0
    pending_exports=load_sheets_export_queue()
    if WEB_APP_URL and pending_exports:
        try:
            for payload in pending_exports:
                export_result=save_results_in_batches(payload.get("new_docs",[]),payload.get("source_status",[]),SAVE_BATCH_SIZE,payload.get("review_docs",[]))
                saved+=export_result["added"]
                review_saved+=export_result["review_added"]
            clear_sheets_export_queue()
            # GitHub tracks exports; Sheets only receives final output.
            for payload in pending_exports:
                for doc in payload.get("new_docs",[]):
                    if doc.get("date_basis")=="unknown":
                        update_review_document(doc.get("link",""),{
                            "exported_to_sheets":True,
                            "exported_at":datetime.now(timezone.utc).isoformat(timespec="seconds")
                        })
            print(f"[SHEETS] Đã xác nhận xuất {len(pending_exports)} gói dữ liệu: "
                  f"{saved} văn bản mới, {review_saved} hồ sơ xác minh ngày mới.")
        except Exception as exc:
            print(f"[SHEETS] Chưa xuất được dữ liệu; đã giữ hàng đợi trên GitHub để thử lại: {type(exc).__name__}: {exc}")
    else:
        print(f"[SHEETS] Bỏ qua xuất dữ liệu; hàng đợi GitHub còn {len(pending_exports)} gói.")
    duration=round(time.monotonic()-started,2)
    summary={"finished_at":utc_now(),"sources":len(sources),"collected":totals["items"],"recognized":totals["recognized"],
             "older_than_60_days":totals["old"],"unknown_date":totals["unknown_date"],"duplicates":totals["duplicate"],
             "new_to_sheets":saved,"review_to_sheets":review_saved,"pending_sheets_exports":len(load_sheets_export_queue()),"review_queue_total":review_total,
             "failed_sources":totals["failed"],"fallback_sources":totals["fallback_sources"],"feed_supplements":totals["feed_supplements"],
             "relationship_candidates":len(relation_rows),"relationship_matched_in_scan_index":relation_matched,
             "relationship_ambiguous":relation_ambiguous,"duration_seconds":duration}
    append_history(summary)
    report=["## Kết quả quét Trạm Tin Tức",f"- Hoàn tất: **{utc_now()}**",f"- Nguồn: **{len(sources)}**",
            f"- Tổng mục thu thập: **{totals['items']}**",f"- Nhận diện văn bản: **{totals['recognized']}**",
            f"- Loại do quá 60 ngày: **{totals['old']}**",f"- Chuyển sang danh sách cần xác minh ngày: **{totals['unknown_date']}**",
            f"- Loại do trùng: **{totals['duplicate']}**",f"- Văn bản mới được Google Sheets xác nhận: **{saved}**",
             f"- Hồ sơ xác minh ngày mới được Google Sheets xác nhận: **{review_saved}**",
             f"- Gói chờ xuất sang Sheets trên GitHub: **{len(load_sheets_export_queue())}**",
             f"- Hồ sơ chờ xác minh ngày trên GitHub: **{review_total}**",
            f"- Bộ nhớ GitHub: **{len(state['documents'])} văn bản**",f"- Nguồn lỗi: **{totals['failed']}/{len(sources)}**",
            f"- Nguồn có dùng dự phòng: **{totals['fallback_sources']}**",
            f"- Quan hệ văn bản địa phương đã ghi nhận: **{len(relation_rows)}**",
            f"- Dẫn chiếu tìm thấy trong kho quét: **{relation_matched}**",
            f"- Dẫn chiếu có nhiều văn bản trùng số hiệu: **{relation_ambiguous}**",
            f"- Thời gian: **{duration} giây**","",
            "| Nguồn | Mục thu thập | Văn bản nhận diện | Trạng thái |","|---|---:|---:|---|"]
    for i in range(len(sources)):
        s,r=results_by_index[i]; report.append(f"| {s.get('name','')[:50]} | {len(r['items'])} | {recognized_by_source[i]} | {r['status']} |")
    append_step_summary(report); print(f"[DONE] Hoàn tất trong {duration} giây.")

if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}",file=sys.stderr); raise
