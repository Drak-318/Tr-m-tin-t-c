# -*- coding: utf-8 -*-
"""Trạm Tin Tức - quét toàn bộ hoặc nhóm nguồn ưu tiên, tối đa 5 nguồn đồng thời."""
import concurrent.futures
import json
from pathlib import Path
import os
import sys
import time
from urllib.parse import quote
from datetime import datetime, timezone

from scanner.config import load_source_config, config_for_source, WEB_APP_URL
from scanner.collectors import (scan_source, verify_document_detail_date,
    search_central_reference_web, is_original_central_document_result)
from scanner.normalizer import (
    is_local_central_rollout,
    extract_doc_info, classify_and_score, make_fingerprint, canonicalize_url,
    classify_document, document_identity, is_too_old, has_document_date, resolve_document_date,
    is_local_scope, extract_central_references, document_type_from_number, issuer_from_document_number,
)
from scanner.sheets import save_results_in_batches, fetch_source_via_apps_script, get_sources_and_memory
from scanner.source_registry import load_sources_from_csv, filter_priority_sources, filter_non_priority_sources
from scanner.source_discovery import record_candidates, pending_candidates, update_candidate
from scanner.persistent_memory import (load_state, RunSeenIndex, record_documents, append_history,
    enqueue_review_documents, enqueue_sheets_export, load_sheets_export_queue, clear_sheets_export_queue, load_review_queue, pending_review_documents, update_review_document, pending_source_retries, record_source_scan_result, filter_sources_due_for_retry)
from scanner.relationship_tracer import collect_local_document_relations, merge_relationships, resolve_reference_candidates

MAX_WORKERS=5  # Tổng ngân sách: priority 2 + full/remaining 3, tối đa 5 nguồn đồng thời.
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
    started_at=utc_now()
    profile=os.getenv("SCAN_PROFILE","full").strip().lower() or "full"
    if profile not in {"full","priority","remaining"}:
        raise RuntimeError(f"SCAN_PROFILE không hợp lệ: {profile}")
    max_workers = 2 if profile == "priority" else 3
    print("="*70); print(f"TRẠM TIN TỨC | BẮT ĐẦU: {started_at} | PROFILE: {profile} | WORKERS: {max_workers}"); print("="*70)
    config_data=load_source_config()
    sources=load_sources_from_csv()
    if not sources: raise RuntimeError("Không có nguồn đang bật trong danh_sach_nguon.csv trên GitHub.")
    priority_path=Path("priority_sources.json")
    if not priority_path.exists():
        raise RuntimeError("Thiếu priority_sources.json; không thể phân chia nhóm nguồn.")
    priority_data=json.loads(priority_path.read_text(encoding="utf-8"))
    priority_urls=priority_data.get("urls",[]) if isinstance(priority_data,dict) else priority_data
    if profile == "priority":
        sources,missing_priority=filter_priority_sources(sources,priority_urls)
        if missing_priority:
            print(f"[PRIORITY-WARNING] {len(missing_priority)} URL ưu tiên chưa có trong danh sách nguồn: " +
                  "; ".join(missing_priority[:8]))
        if not sources:
            raise RuntimeError("Không tìm thấy nguồn ưu tiên hoặc nguồn lỗi cần quét bù.")
    elif profile == "remaining":
        sources=filter_non_priority_sources(sources,priority_urls)
        if not sources:
            raise RuntimeError("Không còn nguồn ngoài nhóm ưu tiên để quét.")

    # Keep every source registered, but throttle repeated failures so 403,
    # timeout and SSL endpoints are not hammered on every 5/30-minute cycle.
    sources,deferred_sources=filter_sources_due_for_retry(sources)
    if deferred_sources:
        print(f"[RETRY-BACKOFF] Tạm hoãn {len(deferred_sources)} nguồn lỗi chưa đến hạn thử lại.")
        for deferred in deferred_sources[:5]:
            print(f"[RETRY-BACKOFF] {deferred.get('name')}: thử lại sau {deferred.get('retry_after')}")
    if not sources:
        print("[RETRY-BACKOFF] Không có nguồn đến hạn trong lượt này; giữ nguyên danh sách và bộ nhớ.")
        return

    state=load_state()
    # Also consult the identities already persisted in the Google Sheets memory
    # tab. This bridges records saved before/without the current GitHub memory.
    if WEB_APP_URL:
        try:
            _sheet_sources, sheet_links, _sheet_numbers, sheet_identities = get_sources_and_memory()
            state.setdefault("documents", {}).update({
                identity: state.get("documents", {}).get(identity, {})
                for identity in sheet_identities if identity
            })
            state.setdefault("urls", {}).update({
                link: state.get("urls", {}).get(link, "sheets-memory")
                for link in sheet_links if link
            })
            print(f"[SHEETS-MEMORY] Đã nạp {len(sheet_identities)} định danh và {len(sheet_links)} URL từ bộ nhớ Google Sheets.")
        except Exception as exc:
            print(f"[SHEETS-MEMORY-WARNING] Không đọc được bộ nhớ Sheets; tiếp tục bằng bộ nhớ GitHub: {str(exc)[:250]}")
    seen_index=RunSeenIndex(state)
    output_index=RunSeenIndex()
    print(f"[INIT] Nguồn: GitHub/danh_sach_nguon.csv | Profile: {profile} | Tổng nguồn: {len(sources)} | Đồng thời: {max_workers}")
    print(f"[INIT] Bộ nhớ GitHub: {len(state['documents'])} văn bản | {len(state['urls'])} URL")

    def scan_one(source):
        source_config=config_for_source(source,config_data)
        if profile == "priority":
            source_config["max_pages"]=min(max(1,int(source_config.get("max_pages",1))),2)
            source_config["max_items"]=min(max(1,int(source_config.get("max_items",200))),120)
            source_config["timeout_connect"]=min(max(3,int(source_config.get("timeout_connect",8))),6)
            source_config["timeout_read"]=min(max(5,int(source_config.get("timeout_read",18))),12)
        return scan_source(source,source_config,fetch_source_via_apps_script if WEB_APP_URL else None)

    results_by_index={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures={pool.submit(scan_one,s):(i,s) for i,s in enumerate(sources)}
        for future in concurrent.futures.as_completed(futures):
            i,s=futures[future]
            try: result=future.result()
            except Exception as exc: result={"items":[],"status":f"Lỗi: {type(exc).__name__}"[:45],"http_status":None,"pages":0,"duration":0,"error":str(exc)[:500],"fallback_used":False}
            results_by_index[i]=(s,result)
            detail=f" | Chi tiết: {result['error']}" if result.get("error") else ""
            fallback=" | Có dùng nguồn dự phòng" if result.get("fallback_used") else ""
            feed_note=" | Có bổ sung RSS" if result.get("feed_supplement_used") else ""
            print(f"[{i+1}/{len(sources)}] {s.get('name')}: {len(result['items'])} mục | {result['status']} | {result['duration']}s{fallback}{feed_note}{detail}")

    # Use local portals as reference-discovery channels: extract exact central
    # instrument numbers from local notices, then search only official central
    # domains for the original instrument. Never export the local rollout letter
    # as a substitute for the cited decree/circular.
    central_reference_stats={"found":0,"queried":0,"matched":0,"ddgs_fallbacks":0,"limit":12}
    if profile in {"full","remaining"}:
        local_references=[]
        known_central_references=set()
        for _source,_result in results_by_index.values():
            # Reset per item: refs only belongs to a local rollout item.
            # Without this, non-rollout items can reuse an old value or raise
            # UnboundLocalError when the first item is not a local rollout.
            refs=[]
            local_source=is_local_scope(
                _source.get("group",""),_source.get("name",""),_source.get("url","")
            )
            for _item in _result.get("items",[]):
                if is_too_old(
                    _item.get("title",""),_item.get("doc_number",""),
                    MAX_AGE_DAYS,_item.get("published_date")
                ):
                    continue
                material=f"{_item.get('title','')} {_item.get('doc_number','')}"
                if local_source and is_local_central_rollout(
                    _item.get("title",""), _item.get("doc_type",""), _item.get("doc_number","")
                ):
                    refs=extract_central_references(material)
                    local_references.extend(refs)
                else:
                    known_central_references.update(refs)
        # Persistent memory prevents repeated lookups for central instruments
        # already collected successfully in an earlier run.
        for stored_document in (state.get("documents") or {}).values():
            known_central_references.update(extract_central_references(
                f"{stored_document.get('title','')} {stored_document.get('doc_number','')}"
            ))
        unique_references=[]
        seen_references=set()
        for ref in local_references:
            if ref not in seen_references and ref not in known_central_references:
                seen_references.add(ref)
                unique_references.append(ref)
        central_reference_stats["found"]=len(unique_references)
        lookup_domains=[
            "quochoi.vn","vanban.chinhphu.vn","chinhphu.vn","vbpl.vn",
            "phapluat.gov.vn","moj.gov.vn","mof.gov.vn","moet.gov.vn",
            "moh.gov.vn","mae.gov.vn","moit.gov.vn","sbv.gov.vn",
            "moha.gov.vn","moc.gov.vn","mps.gov.vn","baochinhphu.vn",
            "sav.gov.vn","baohiemxahoi.gov.vn"
        ]
        for ref in unique_references[:central_reference_stats["limit"]]:
            central_reference_stats["queried"]+=1
            # Search the exact number broadly; final URLs are still restricted
            # to central authorities below. Google News' multi-site OR query
            # missed known official records in the live run.
            query=f'"{ref}" when:60d'
            lookup_url="https://news.google.com/rss/search?q="+quote(query)+"&hl=vi&gl=VN&ceid=VN:vi"
            lookup_source={
                "name":f"Tra cứu văn bản Trung ương theo số hiệu {ref}",
                "url":lookup_url,"group":"Văn Bản TW","row":None
            }
            lookup_config={
                "mode":"rss","max_items":10,"max_pages":1,
                "timeout_connect":5,"timeout_read":12,
                "allowed_final_domains":lookup_domains,
                "apps_script_fallback":False
            }
            lookup_result=scan_source(lookup_source,lookup_config,None)
            matched=[
                item for item in lookup_result.get("items",[])
                if is_original_central_document_result(
                    item.get("title",""),item.get("link",""),ref
                )
            ]
            lookup_method="Google News RSS"
            ddgs_error=""
            if not matched:
                web_items,ddgs_error=search_central_reference_web(
                    ref,lookup_domains,max_results=8
                )
                if web_items:
                    matched=web_items
                    lookup_method="DDGS"
                    central_reference_stats["ddgs_fallbacks"]+=1
            if matched:
                for item in matched:
                    item.setdefault("doc_number",ref)
                    item.setdefault("doc_type",document_type_from_number(ref))
                    item.setdefault("agency",issuer_from_document_number(ref))
                lookup_result["items"]=matched
                lookup_result["status"]=f"Hoạt động qua {lookup_method}"
                lookup_result["error"]=""
                sources.append(lookup_source)
                results_by_index[len(sources)-1]=(lookup_source,lookup_result)
                central_reference_stats["matched"]+=len(matched)
                print(f"[CENTRAL-REFERENCE] {ref}: tìm thấy {len(matched)} kết quả từ nguồn Trung ương qua {lookup_method}.")
            else:
                rss_detail=lookup_result.get("error") or lookup_result.get("status","không có kết quả")
                fallback_detail=f" | DDGS: {ddgs_error}" if ddgs_error else ""
                print(
                    f"[CENTRAL-REFERENCE] {ref}: chưa tìm thấy bản gốc. "
                    f"RSS: {rss_detail}; số mục RSS: {len(lookup_result.get('items',[]))}{fallback_detail}"
                )
        if central_reference_stats["queried"]:
            print(
                "[CENTRAL-REFERENCE] "
                f"Phát hiện {central_reference_stats['found']} số hiệu; "
                f"đã tra cứu {central_reference_stats['queried']}; "
                f"nhận được {central_reference_stats['matched']} kết quả; "
                f"có {central_reference_stats['ddgs_fallbacks']} lượt dùng DDGS."
            )

    if profile in {"full","remaining"}:
        # Learn new listing/category URLs from the pages already scanned. A URL
        # is not activated until a live validation scan finds at least 3 documents.
        discovered_candidates=[]
        for _source, _result in results_by_index.values():
            discovered_candidates.extend(_result.get("discovered_candidates", []))
        discovered_added=record_candidates(discovered_candidates)
        discovery_activated=0
        candidates_to_check=pending_candidates(limit=10)
        discovery_checked=len(candidates_to_check)
    
        def validate_source_candidate(candidate):
            candidate_source={
                "name":candidate.get("name","Nguồn tự phát hiện"),
                "url":candidate["url"],
                "group":candidate.get("group","Văn Bản TW"),
            }
            candidate_config=config_for_source(candidate_source,config_data)
            candidate_config.update({"max_pages":2,"max_items":80,"follow_pagination":True})
            validation=scan_source(candidate_source,candidate_config,None)
            recognized_items=[]
            for candidate_item in validation.get("items",[]):
                candidate_type=candidate_item.get("doc_type") or extract_doc_info(candidate_item.get("title",""))[0]
                candidate_number=candidate_item.get("doc_number") or extract_doc_info(candidate_item.get("title",""))[1]
                if candidate_type and candidate_number and candidate_number!="Đang cập nhật":
                    recognized_items.append(candidate_item)
            return candidate,validation,recognized_items
    
        # Validate candidates concurrently, but never exceed the scanner's global
        # five-worker limit. This drains the discovery queue faster without
        # creating an unbounded burst of requests to public portals.
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for candidate,validation,recognized_items in pool.map(validate_source_candidate,candidates_to_check):
                attempts=int(candidate.get("attempts",0))+1
                child_candidates = validation.get("discovered_candidates", [])
                if len(recognized_items)>=3:
                    update_candidate(candidate["url"],{
                        "status":"active","attempts":attempts,
                        "validated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "validated_document_count":len(recognized_items),
                        "sample_titles":[x.get("title","") for x in recognized_items[:3]],
                        "last_error":"",
                    })
                    discovery_activated+=1
                elif candidate.get("candidate_kind") == "portal_hub" and child_candidates:
                    # A directory/homepage is a discovery bridge, not a scan source.
                    # Extract its same-site document-listing links and queue those.
                    children_added = record_candidates(child_candidates)
                    update_candidate(candidate["url"],{
                        "status":"hub","attempts":attempts,
                        "hub_checked_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "child_candidates_found":len(child_candidates),
                        "child_candidates_added":children_added,
                        "last_error":"",
                    })
                else:
                    reason=validation.get("error") or (
                        f"Chỉ nhận diện {len(recognized_items)} văn bản có số hiệu; cần ít nhất 3."
                    )
                    update_candidate(candidate["url"],{
                        "attempts":attempts,"last_error":str(reason)[:350],
                        "last_validation_status":validation.get("status",""),
                    })
        if discovered_added or discovery_checked:
            print(f"[SOURCE-DISCOVERY] Phát hiện {discovered_added} link danh mục mới | "
                  f"Kiểm tra {discovery_checked} | Kích hoạt {discovery_activated} nguồn. "
                  "Nguồn mới sẽ tham gia từ lượt quét tiếp theo.")
    else:
        discovered_added=0
        discovery_activated=0
        discovery_checked=0
    if profile == "full":
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
    else:
        relation_path=Path("data/document_relationships.json")
        try:
            relation_rows=json.loads(relation_path.read_text(encoding="utf-8")) if relation_path.exists() else []
            if not isinstance(relation_rows,list):
                relation_rows=[]
        except Exception:
            relation_rows=[]
        relation_matched=sum(1 for row in relation_rows if row.get("resolution_status")=="found_in_scan_index")
        relation_ambiguous=sum(1 for row in relation_rows if row.get("resolution_status")=="ambiguous_multiple_matches")
    new_docs=[]; review_docs=[]; source_status=[]; accepted_for_memory=[]
    for source,result in results_by_index.values():
        record_source_scan_result(source,result)
    existing_review=load_review_queue()
    existing_review_urls=set(existing_review)
    # Undated documents are tracked by identity in the review queue as well as
    # by URL, so a second portal cannot re-add the same item on later scans.
    review_identity_seen=set()
    for review_url, review_row in existing_review.items():
        review_identity_seen.add(document_identity(
            review_row.get("doc_number",""), review_row.get("title",""),
            review_row.get("agency",""), review_url
        ))
    existing_review_identity=set(review_identity_seen)
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
        # Do not use old imported seen-memory to suppress backfill here:
        # only prevent the same review identity/URL from being added twice
        # during this particular run.
        if output_index.contains(identity,review_url):
            continue
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
        output_index.add(identity,review_url)
        backfilled_review_docs+=1
    if backfilled_review_docs:
        print(f"[BACKFILL] Đưa {backfilled_review_docs} hồ sơ chờ xác minh cũ vào bảng kết quả.")
    totals={"items":0,"recognized":0,"old":0,"unknown_date":0,"duplicate":0,"kept":0,"failed":0,"fallback_sources":0,"feed_supplements":0,"central_reference_queries":central_reference_stats["queried"],"central_reference_hits":central_reference_stats["matched"]}
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
            agency=item.get("agency") or issuer_from_document_number(number) or name
            recognized+=1; totals["recognized"]+=1
            category=classify_document(title,agency,doc_type,number,link)
            if not has_document_date(title,pub):
                # Keep undated documents for review, but deduplicate by identity
                # across all sources in this run and across prior review-queue URLs.
                totals["unknown_date"]+=1
                identity=document_identity(number,title,agency,link)
                if link not in existing_review_urls and identity not in review_identity_seen:
                    review_docs.append({"agency":agency,"title":title,"doc_number":number,"link":link,
                                    "identity":identity,"published_date":"",
                                    "source_published_date":item.get("source_published_date",""),
                                    "date_basis":"unknown","date_source":item.get("date_source",""),
                                        "reason":"Chưa có ngày xác minh; giữ lại để hậu kiểm.","source_group":group})
                    review_identity_seen.add(identity)
                if (link not in existing_review_urls
                        and not seen_index.contains(identity,link)
                        and not output_index.contains(identity,link)
                        and identity not in existing_review_identity):
                    keep,priority=classify_and_score(title,agency,doc_type,number,group,None)
                    if keep:
                        new_docs.append({"priority":priority,"doc_type":doc_type,"agency":agency,"title":title,
                                         "doc_number":number,"link":link,"fingerprint":make_fingerprint(number,title),
                                         "category":category,"identity":identity,"published_date":"",
                                         "document_date":"","date_basis":"unknown",
                                         "date_status":"Chưa xác minh ngày - giữ lại hậu kiểm"})
                        output_index.add(identity,link)
                        review_identity_seen.add(identity)
                        totals["kept"]+=1
                        existing_review_urls.add(link)
                continue
            # Có ngày thì mới áp dụng bộ lọc 60 ngày; ưu tiên ngày ban hành.
            if is_too_old(title,number,MAX_AGE_DAYS,pub):
                totals["old"]+=1; continue
            keep,priority=classify_and_score(title,agency,doc_type,number,group,pub)
            if not keep: continue
            totals["kept"]+=1
            identity=document_identity(number,title,agency,link)
            if seen_index.contains(identity,link) or output_index.contains(identity,link):
                totals["duplicate"]+=1; continue
            resolved_date,date_basis=resolve_document_date(title,pub)
            doc={"priority":priority,"doc_type":doc_type,"agency":agency,"title":title,"doc_number":number,
                 "link":link,"fingerprint":make_fingerprint(number,title),"category":category,
                 "identity":identity,"published_date":pub or "",
                 "document_date":resolved_date.strftime("%Y-%m-%d") if resolved_date else "",
                 "date_basis":date_basis,"source_published_date":item.get("source_published_date","")}
            new_docs.append(doc); accepted_for_memory.append({**doc,"identity":identity})
            output_index.add(identity,link)
        recognized_by_source[i]=recognized
        if result["error"] and not result.get("fallback_used"): totals["failed"]+=1
        status=result["status"]
        if not result["error"] and result["items"]: status="Hoạt động" if recognized else "Đã truy cập, chưa nhận diện văn bản"
        if result.get("fallback_used"): status="Hoạt động qua nguồn dự phòng"
        if source.get("row") is not None: source_status.append({"row":source["row"],"count":recognized,"status":status[:45]})

    # Recheck a small, bounded batch of previously undated documents on their detail pages.
    # This is deliberately limited per run so source collection remains the priority.
    review_candidates=pending_review_documents(limit=5 if profile == "priority" else 40,max_attempts=3,retry_manual_after_days=7)
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
                    elif seen_index.contains(identity,row.get("link","")) or output_index.contains(identity,row.get("link","")):
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
                        output_index.add(identity,row.get("link",""))
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
    failed_source_details=[]
    for i in range(len(sources)):
        source,result=results_by_index[i]
        if result.get("error") and not result.get("fallback_used"):
            failed_source_details.append({
                "name":source.get("name",""),
                "url":source.get("url",""),
                "status":result.get("status",""),
                "http_status":result.get("http_status"),
                "error":str(result.get("error",""))[:240],
            })
    summary={"started_at":started_at,"finished_at":utc_now(),"scan_profile":profile,
             "trigger":os.getenv("SCAN_TRIGGER",os.getenv("GITHUB_EVENT_NAME","manual")),
             "run_id":os.getenv("GITHUB_RUN_ID",""),"run_attempt":os.getenv("GITHUB_RUN_ATTEMPT",""),
             "sources":len(sources),"successful_sources":len(sources)-totals["failed"],
             "failed_source_details":failed_source_details,
             "collected":totals["items"],"recognized":totals["recognized"],
             "older_than_60_days":totals["old"],"unknown_date":totals["unknown_date"],"duplicates":totals["duplicate"],
             "new_to_sheets":saved,"review_to_sheets":review_saved,"pending_sheets_exports":len(load_sheets_export_queue()),"review_queue_total":review_total,"source_retry_queue_pending":len(pending_source_retries(limit=10000)),
             "source_retries_deferred":len(deferred_sources),
             "failed_sources":totals["failed"],"fallback_sources":totals["fallback_sources"],"feed_supplements":totals["feed_supplements"],
             "relationship_candidates":len(relation_rows),"relationship_matched_in_scan_index":relation_matched,
             "relationship_ambiguous":relation_ambiguous,
             "discovered_source_candidates_added":discovered_added,
             "discovered_sources_checked":discovery_checked,
             "discovered_sources_activated":discovery_activated,
             "discovered_sources_pending":len(pending_candidates(limit=500)),
             "duration_seconds":duration}
    append_history(summary)
    report=["## Kết quả quét Trạm Tin Tức",f"- Profile: **{profile}**",
             f"- Trigger: **{os.getenv('SCAN_TRIGGER',os.getenv('GITHUB_EVENT_NAME','manual'))}**",
             f"- Run ID: **{os.getenv('GITHUB_RUN_ID','local')}**",
             f"- Bắt đầu: **{started_at}**",f"- Hoàn tất: **{utc_now()}**",f"- Nguồn: **{len(sources)}**",
            f"- Tổng mục thu thập: **{totals['items']}**",f"- Nhận diện văn bản: **{totals['recognized']}**",
            f"- Loại do quá 60 ngày: **{totals['old']}**",f"- Chuyển sang danh sách cần xác minh ngày: **{totals['unknown_date']}**",
            f"- Loại do trùng: **{totals['duplicate']}**",f"- Văn bản mới được Google Sheets xác nhận: **{saved}**",
             f"- Hồ sơ xác minh ngày mới được Google Sheets xác nhận: **{review_saved}**",
             f"- Gói chờ xuất sang Sheets trên GitHub: **{len(load_sheets_export_queue())}**",
             f"- Hồ sơ chờ xác minh ngày trên GitHub: **{review_total}**",
            f"- Nguồn đang chờ quét bù: **{len(pending_source_retries(limit=10000))}**",
            f"- Nguồn tạm hoãn theo lịch thử lại: **{len(deferred_sources)}**",
            f"- Bộ nhớ GitHub: **{len(state['documents'])} văn bản**",f"- Nguồn lỗi: **{totals['failed']}/{len(sources)}**",
            f"- Nguồn có dùng dự phòng: **{totals['fallback_sources']}**",
            f"- Nguồn mới phát hiện: **{discovered_added}**",
            f"- Nguồn mới đã kiểm tra: **{discovery_checked}**",
            f"- Nguồn mới được kích hoạt cho lượt sau: **{discovery_activated}**",
            f"- Nguồn mới còn chờ kiểm tra: **{len(pending_candidates(limit=500))}**",
            f"- Quan hệ văn bản địa phương đã ghi nhận: **{len(relation_rows)}**",
            f"- Dẫn chiếu tìm thấy trong kho quét: **{relation_matched}**",
            f"- Dẫn chiếu có nhiều văn bản trùng số hiệu: **{relation_ambiguous}**",
            f"- Thời gian: **{duration} giây**","",
            "| Nguồn | Mục thu thập | Văn bản nhận diện | Trạng thái |","|---|---:|---:|---|"]
    if failed_source_details:
        report.extend(["","### Chi tiết nguồn lỗi"])
        for failure in failed_source_details:
            report.append(
                f"- {failure['name']} | {failure['status']} | HTTP {failure['http_status']} | {failure['error'][:160]}"
            )
    for i in range(len(sources)):
        s,r=results_by_index[i]; report.append(f"| {s.get('name','')[:50]} | {len(r['items'])} | {recognized_by_source[i]} | {r['status']} |")
    append_step_summary(report); print(f"[DONE] Hoàn tất trong {duration} giây.")

if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}",file=sys.stderr); raise
