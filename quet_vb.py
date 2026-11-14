# -*- coding: utf-8 -*-
import re
import json
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbxwx2aahfkilC3IOWUZtb1jfRuG1dWTNfEsPA0_WDFWB2xzmqBMyEhJloZKpafLnRVi_A/exec"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8"
}

DOC_REGEX = re.compile(r"(Luật|Nghị định|Thông tư|Quyết định|Nghị quyết|Chỉ thị|Công văn|Kết luận|Hướng dẫn)\s+(?:số\s*)?([0-9]+(?:/[0-9]{4})?/[A-ZĐƯƠĂÂÊÔ0-9\-]+)", re.IGNORECASE)

def extract_doc_info(title):
    m = DOC_REGEX.search(title)
    if m:
        return m.group(1).capitalize(), m.group(2).upper()
    for kw in ["Nghị định", "Thông tư", "Quyết định", "Nghị quyết", "Công văn", "Chỉ thị", "Luật", "Dự thảo"]:
        if kw.lower() in title.lower():
            num_m = re.search(r"([0-9]+/[0-9]{4}/[A-ZĐƯƠĂÂÊÔ0-9\-]+|[0-9]+/[A-ZĐƯƠĂÂÊÔ0-9\-]+)", title, re.I)
            return kw, (num_m.group(1).upper() if num_m else "Đang cập nhật")
    return None, None

def main():
    print("1. Đang lấy danh sách nguồn từ Google Sheet...")
    resp = requests.post(WEB_APP_URL, json={"action": "get_sources"}, timeout=30)
    data = resp.json()
    sources = data.get("sources", [])
    existing_links = set(data.get("existingLinks", []))
    existing_numbers = set(data.get("existingNumbers", []))
    print(f"-> Đã tải {len(sources)} nguồn quét và {len(existing_links)} văn bản trong bộ nhớ.")

    new_docs = []
    source_status = []

    for src in sources:
        url = src["url"]
        name = src["name"]
        row = src["row"]
        found_items = 0
        try:
            r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            if r.status_code != 200:
                source_status.append({"row": row, "count": 0, "status": f"Lỗi ({r.status_code})"})
                continue

            content_text = r.text
            items = []
            if "<rss" in content_text[:500].lower() or "<feed" in content_text[:500].lower() or "news.google.com/rss" in url:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:20]:
                    t = item.findtext("title") or ""
                    l = item.findtext("link") or ""
                    items.append((t.strip(), l.strip()))
            else:
                soup = BeautifulSoup(content_text, "html.parser")
                for a in soup.find_all("a", href=True):
                    t = " ".join(a.get_text().split())
                    if len(t) > 25:
                        l = urljoin(url, a["href"])
                        items.append((t, l))

            for title, link in items:
                doc_type, doc_num = extract_doc_info(title)
                if not doc_type:
                    continue
                found_items += 1
                if link in existing_links or (doc_num != "Đang cập nhật" and doc_num in existing_numbers):
                    continue
                existing_links.add(link)
                if doc_num != "Đang cập nhật":
                    existing_numbers.add(doc_num)
                fp = f"[{doc_num}] {title[:50].lower()}"
                new_docs.append({
                    "doc_type": doc_type,
                    "agency": name,
                    "title": title,
                    "doc_number": doc_num,
                    "link": link,
                    "fingerprint": fp
                })
            source_status.append({"row": row, "count": found_items, "status": "Hoạt động"})
            print(f"[OK] {name}: thấy {found_items} mục văn bản.")
        except Exception as e:
            source_status.append({"row": row, "count": 0, "status": "Lỗi kết nối"})
            print(f"[LỖI] {name}: {str(e)[:80]}")

    print(f"2. Phát hiện {len(new_docs)} văn bản mới. Đang đồng bộ về Google Sheet...")
    save_resp = requests.post(WEB_APP_URL, json={
        "action": "save_results",
        "new_docs": new_docs[:50],
        "source_status": source_status
    }, timeout=45)
    print("-> Kết quả lưu:", save_resp.text)

if __name__ == "__main__":
    main()