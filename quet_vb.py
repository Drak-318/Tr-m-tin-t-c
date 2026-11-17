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

# Từ khóa nhận diện văn bản Địa phương (cấp Tỉnh/Thành phố/Sở/UBND/HĐND)
LOCAL_KEYWORDS = [
    "ubnd", "ủy ban nhân dân", "hđnd", "hội đồng nhân dân", "qđ-ubnd", "nq-hđnd", 
    "ct-ubnd", "kh-ubnd", "tỉnh ", "thành phố ", "tp.", "tp ", "sở "
]

# Từ khóa 7 chủ đề trọng tâm dành riêng cho văn bản Địa phương
LOCAL_TOPIC_KEYWORDS = [
    # 1. Đất đai, nhà ở, bồi thường
    "đất đai", "bảng giá đất", "thu hồi đất", "giao đất", "cho thuê đất", "bồi thường", 
    "tái định cư", "sổ đỏ", "giấy chứng nhận quyền sử dụng đất", "nhà ở", "nhà ở xã hội", 
    "tách thửa", "hợp thửa", "hạn mức đất", "quy hoạch sử dụng đất",
    # 2. Cán bộ, công chức, viên chức, tinh giản
    "cán bộ", "công chức", "viên chức", "người hoạt động không chuyên trách", 
    "tuyển dụng", "nâng ngạch", "thăng hạng", "tinh giản biên chế", "kỷ luật", "đánh giá xếp loại",
    # 3. Thi đua, khen thưởng
    "thi đua", "khen thưởng", "bằng khen", "danh hiệu", "huân chương", "huy chương", "kỷ niệm chương",
    # 4. Lao động, tiền lương, phụ cấp, BHXH
    "tiền lương", "mức lương", "lương tối thiểu", "phụ cấp", "trợ cấp", "chế độ chính sách", 
    "lao động", "việc làm", "bảo hiểm xã hội", "bhxh", "bảo hiểm y tế", "bhyt", "người có công", "an sinh",
    # 5. Thuế, phí, lệ phí, hóa đơn
    "thuế", "lệ phí", "mức thu phí", "miễn giảm", "hóa đơn", "hộ kinh doanh", "tiền sử dụng đất",
    # 6. Giao thông, xử phạt vi phạm hành chính
    "giao thông", "xử phạt", "vi phạm hành chính", "giấy phép lái xe", "đăng kiểm", "bến xe", "vận tải",
    # 7. Giáo dục, y tế, học phí, khám chữa bệnh
    "giáo dục", "học phí", "tuyển sinh", "giáo viên", "y tế", "khám chữa bệnh", "bệnh viện", "dịch bệnh"
]

def extract_doc_info(title):
    m = DOC_REGEX.search(title)
    if m:
        return m.group(1).capitalize(), m.group(2).upper()
    for kw in ["Nghị định", "Thông tư", "Quyết định", "Nghị quyết", "Công văn", "Chỉ thị", "Luật", "Dự thảo"]:
        if kw.lower() in title.lower():
            num_m = re.search(r"([0-9]+/[0-9]{4}/[A-ZĐƯƠĂÂÊÔ0-9\-]+|[0-9]+/[A-ZĐƯƠĂÂÊÔ0-9\-]+)", title, re.I)
            return kw, (num_m.group(1).upper() if num_m else "Đang cập nhật")
    return None, None

def classify_and_filter(title, agency, doc_type, doc_num, group):
    text_check = f"{title} {agency} {doc_num}".lower()
    is_local = (group.lower() == "địa phương") or any(lk in text_check for lk in LOCAL_KEYWORDS)

    if is_local:
        # Văn bản Địa phương: Bắt buộc phải thuộc 1 trong 7 chủ đề quan tâm
        if not any(tk in text_check for tk in LOCAL_TOPIC_KEYWORDS):
            return False, 99
        return True, 20
    else:
        # Văn bản Trung ương: Lấy toàn bộ và xếp ưu tiên lên trên cùng
        type_priority = {
            "Luật": 1, "Nghị quyết": 2, "Nghị định": 3, "Thông tư": 4, 
            "Quyết định": 5, "Chỉ thị": 6, "Công văn": 7
        }.get(doc_type, 8)
        return True, 10 + type_priority

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
        group = src.get("group", "Văn Bản TW")
        found_items = 0
        try:
            r = requests.get(url, headers=HEADERS, timeout=6, verify=False)
            if r.status_code != 200:
                source_status.append({"row": row, "count": 0, "status": f"Lỗi ({r.status_code})"})
                continue

            content_text = r.text
            items = []
            if "<rss" in content_text[:500].lower() or "<feed" in content_text[:500].lower() or "news.google.com/rss" in url:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:25]:
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
                
                keep, priority_score = classify_and_filter(title, name, doc_type, doc_num, group)
                if not keep:
                    continue

                found_items += 1
                if link in existing_links or (doc_num != "Đang cập nhật" and doc_num in existing_numbers):
                    continue
                existing_links.add(link)
                if doc_num != "Đang cập nhật":
                    existing_numbers.add(doc_num)
                fp = f"[{doc_num}] {title[:50].lower()}"
                new_docs.append({
                    "priority": priority_score,
                    "doc_type": doc_type,
                    "agency": name,
                    "title": title,
                    "doc_number": doc_num,
                    "link": link,
                    "fingerprint": fp
                })
            source_status.append({"row": row, "count": found_items, "status": "Hoạt động"})
            print(f"[OK] {name}: thấy {found_items} mục văn bản đạt chuẩn.")
        except Exception as e:
            source_status.append({"row": row, "count": 0, "status": "Lỗi kết nối"})
            print(f"[LỖI] {name}: {str(e)[:60]}")

    # Sắp xếp ưu tiên: Văn bản Trung ương lên đầu, Địa phương xuống dưới
    new_docs.sort(key=lambda x: x["priority"])

    print(f"2. Phát hiện {len(new_docs)} văn bản mới. Đang đồng bộ về Google Sheet...")
    save_resp = requests.post(WEB_APP_URL, json={
        "action": "save_results",
        "new_docs": new_docs[:50],
        "source_status": source_status
    }, timeout=45)
    print("-> Kết quả lưu:", save_resp.text)

if __name__ == "__main__":
    main()
