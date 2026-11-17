# -*- coding: utf-8 -*-
"""Trạm Tin Tức - full-source scanner, scheduled by GitHub Actions."""

import concurrent.futures
import os
import sys
import time
from datetime import datetime, timezone

from scanner.config import load_source_config, config_for_source
from scanner.collectors import scan_source
from scanner.normalizer import (
    extract_doc_info, classify_and_score, make_fingerprint, canonicalize_url,
)
from scanner.sheets import get_sources_and_memory, save_results_in_batches

MAX_WORKERS = 5
SAVE_BATCH_SIZE = 50

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def append_step_summary(lines):
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

def main():
    started_at = time.monotonic()
    print("=" * 65)
    print(f"TRẠM TIN TỨC | BẮT ĐẦU: {utc_now()}")
    print("=" * 65)

    config_data = load_source_config()
    sources, existing_links, existing_numbers = get_sources_and_memory()
    print(f"[INIT] Tổng nguồn nhận được: {len(sources)}")
    print(f"[INIT] Bộ nhớ URL: {len(existing_links)} | Số hiệu: {len(existing_numbers)}")
    if not sources:
        raise RuntimeError("Google Sheets không trả về nguồn nào có tên và URL.")

    results_by_index = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(scan_source, source, config_for_source(source, config_data)): (i, source)
            for i, source in enumerate(sources)
        }
        for future in concurrent.futures.as_completed(futures):
            index, source = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "items": [], "status": f"Lỗi: {type(exc).__name__}"[:45],
                    "http_status": None, "pages": 0, "duration": 0,
                    "error": str(exc)[:300],
                }
            results_by_index[index] = (source, result)
            print(
                f"[{index + 1}/{len(sources)}] {source.get('name')}: "
                f"{len(result['items'])} mục | {result['status']} | "
                f"{result['duration']}s | HTTP {result['http_status']}"
            )

    new_docs, source_status = [], []
    seen_links, seen_numbers = set(existing_links), set(existing_numbers)
    total_items = recognized_items = failed_sources = 0

    for index in range(len(sources)):
        source, result = results_by_index[index]
        source_name = source.get("name", "Nguồn không tên")
        group = source.get("group", "Văn Bản TW")
        total_items += len(result["items"])
        recognized_for_source = 0

        for item in result["items"]:
            title = item["title"]
            link = canonicalize_url(item["link"])
            doc_type, doc_number = extract_doc_info(title)
            if not doc_type:
                continue
            keep, priority = classify_and_score(
                title, source_name, doc_type, doc_number, group
            )
            if not keep:
                continue

            recognized_for_source += 1
            recognized_items += 1
            if link in seen_links:
                continue
            if doc_number != "Đang cập nhật" and doc_number in seen_numbers:
                continue

            seen_links.add(link)
            if doc_number != "Đang cập nhật":
                seen_numbers.add(doc_number)
            new_docs.append({
                "priority": priority,
                "doc_type": doc_type,
                "agency": source_name,
                "title": title,
                "doc_number": doc_number,
                "link": link,
                "fingerprint": make_fingerprint(doc_number, title),
            })

        if result["error"]:
            failed_sources += 1
        status = result["status"]
        if not result["error"] and recognized_for_source:
            status = "Hoạt động"
        source_status.append({
            "row": source.get("row"),
            "count": recognized_for_source,
            "status": status[:45],
        })

    new_docs.sort(key=lambda doc: (doc["priority"], doc["title"].casefold()))
    print("-" * 65)
    print(f"[RESULT] Tổng mục thu thập: {total_items}")
    print(f"[RESULT] Mục nhận diện là văn bản: {recognized_items}")
    print(f"[RESULT] Văn bản mới sau chống trùng: {len(new_docs)}")
    print(f"[RESULT] Nguồn lỗi: {failed_sources}/{len(sources)}")

    # Always write source statuses, including runs with zero new documents.
    saved = save_results_in_batches(new_docs, source_status, SAVE_BATCH_SIZE)
    duration = round(time.monotonic() - started_at, 2)

    report = [
        "## Kết quả quét Trạm Tin Tức",
        f"- Thời điểm hoàn tất: {utc_now()}",
        f"- Tổng nguồn: **{len(sources)}**",
        f"- Tổng mục thu thập: **{total_items}**",
        f"- Mục nhận diện là văn bản: **{recognized_items}**",
        f"- Văn bản mới gửi Sheets: **{saved}**",
        f"- Nguồn gặp lỗi: **{failed_sources}/{len(sources)}**",
        f"- Thời gian chạy: **{duration} giây**",
        "",
        "| Nguồn | Mục lấy được | Văn bản nhận diện | Trạng thái | Thời gian |",
        "|---|---:|---:|---|---:|",
    ]
    for index in range(len(sources)):
        source, result = results_by_index[index]
        recognized = sum(1 for item in result["items"] if extract_doc_info(item["title"])[0])
        report.append(
            f"| {source.get('name', '')[:50]} | {len(result['items'])} | "
            f"{recognized} | {result['status']} | {result['duration']}s |"
        )
    append_step_summary(report)
    print(f"[DONE] Hoàn tất trong {duration} giây.")
    if failed_sources:
        print("[WARNING] Có nguồn lỗi; xem GitHub Actions Summary và log.")
    print("=" * 65)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
