# -*- coding: utf-8 -*-
"""Trạm Tin Tức - quét toàn bộ nguồn, tối đa 5 nguồn cùng lúc."""

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

# Đây là số nguồn chạy ĐỒNG THỜI, không phải giới hạn tổng số nguồn.
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
    print("=" * 70)
    print(f"TRẠM TIN TỨC | BẮT ĐẦU: {utc_now()}")
    print("=" * 70)

    config_data = load_source_config()
    sources, existing_links, existing_numbers = get_sources_and_memory()
    total_sources = len(sources)

    print(f"[INIT] Tổng số nguồn cần quét: {total_sources}")
    print(f"[INIT] Số nguồn chạy đồng thời tối đa: {MAX_WORKERS}")
    print(f"[INIT] Bộ nhớ URL: {len(existing_links)} | Số hiệu: {len(existing_numbers)}")

    if not sources:
        raise RuntimeError(
            "Google Sheets không trả về nguồn nào có URL. "
            "Kiểm tra sheet 'Nguồn Quét Văn Bản', cột B."
        )

    # Đưa TẤT CẢ nguồn vào hàng đợi. ThreadPoolExecutor chỉ giới hạn 5 tác vụ
    # hoạt động cùng lúc; các nguồn còn lại tự lần lượt được xử lý.
    results_by_index = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                scan_source, source, config_for_source(source, config_data)
            ): (i, source)
            for i, source in enumerate(sources)
        }

        for future in concurrent.futures.as_completed(futures):
            index, source = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "items": [],
                    "status": f"Lỗi: {type(exc).__name__}"[:45],
                    "http_status": None,
                    "pages": 0,
                    "duration": 0,
                    "error": str(exc)[:300],
                }
            results_by_index[index] = (source, result)
            print(
                f"[{index + 1}/{total_sources}] {source.get('name')}: "
                f"{len(result['items'])} mục | {result['status']} | "
                f"{result['duration']}s | HTTP {result['http_status']}"
            )

    new_docs, source_status = [], []
    seen_links, seen_numbers = set(existing_links), set(existing_numbers)
    total_items = recognized_items = kept_items = failed_sources = 0
    recognized_by_source = {}

    for index in range(total_sources):
        source, result = results_by_index[index]
        source_name = source.get("name", "Nguồn không tên")
        group = source.get("group", "Văn Bản TW")
        total_items += len(result["items"])
        recognized_for_source = 0
        kept_for_source = 0

        for item in result["items"]:
            title = item["title"]
            link = canonicalize_url(item["link"])
            doc_type, doc_number = extract_doc_info(title)
            if not doc_type:
                continue

            recognized_for_source += 1
            recognized_items += 1
            keep, priority = classify_and_score(
                title, source_name, doc_type, doc_number, group
            )
            if not keep:
                continue

            kept_for_source += 1
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

        kept_items += kept_for_source
        recognized_by_source[index] = recognized_for_source

        if result["error"]:
            failed_sources += 1
        status = result["status"]
        if not result["error"] and result["items"]:
            status = "Hoạt động" if recognized_for_source else "Đã truy cập, chưa nhận diện văn bản"

        source_status.append({
            "row": source.get("row"),
            "count": recognized_for_source,
            "status": status[:45],
        })

    new_docs.sort(key=lambda doc: (doc["priority"], doc["title"].casefold()))

    print("-" * 70)
    print(f"[RESULT] Nguồn đã xử lý: {len(results_by_index)}/{total_sources}")
    print(f"[RESULT] Tổng mục thu thập: {total_items}")
    print(f"[RESULT] Mục nhận diện là văn bản: {recognized_items}")
    print(f"[RESULT] Mục đạt điều kiện phân loại: {kept_items}")
    print(f"[RESULT] Văn bản mới sau chống trùng: {len(new_docs)}")
    print(f"[RESULT] Nguồn lỗi: {failed_sources}/{total_sources}")

    # Gửi toàn bộ kết quả; hàm Sheets tự chia lô 50 văn bản/lần.
    # Trạng thái nguồn vẫn được cập nhật khi không có văn bản mới.
    saved = save_results_in_batches(new_docs, source_status, SAVE_BATCH_SIZE)
    duration = round(time.monotonic() - started_at, 2)

    report = [
        "## Kết quả quét Trạm Tin Tức",
        f"- Thời điểm hoàn tất: {utc_now()}",
        f"- Tổng nguồn trong danh sách: **{total_sources}**",
        f"- Số nguồn xử lý xong: **{len(results_by_index)}/{total_sources}**",
        f"- Số nguồn chạy đồng thời tối đa: **{MAX_WORKERS}**",
        f"- Tổng mục thu thập: **{total_items}**",
        f"- Mục nhận diện là văn bản: **{recognized_items}**",
        f"- Mục đạt điều kiện phân loại: **{kept_items}**",
        f"- Văn bản mới ghi về Google Sheets: **{saved}**",
        f"- Nguồn gặp lỗi: **{failed_sources}/{total_sources}**",
        f"- Thời gian chạy: **{duration} giây**",
        "",
        "| Nguồn | Mục thu thập | Văn bản nhận diện | Trạng thái | Thời gian |",
        "|---|---:|---:|---|---:|",
    ]

    for index in range(total_sources):
        source, result = results_by_index[index]
        report.append(
            f"| {source.get('name', '')[:50]} | {len(result['items'])} | "
            f"{recognized_by_source[index]} | {result['status']} | "
            f"{result['duration']}s |"
        )

    append_step_summary(report)
    print(f"[DONE] Hoàn tất trong {duration} giây.")
    if failed_sources:
        print("[WARNING] Có nguồn lỗi; xem GitHub Actions Summary và log.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[FATAL] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
