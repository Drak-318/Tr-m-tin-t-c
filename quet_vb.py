# -*- coding: utf-8 -*-
import re
import json
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import urllib3
from datetime import datetime
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbxwx2aahfkilC3IOWUZtb1jfRuG1dWTNfEsPA0_WDFWB2xzmqBMyEhJloZKpafLnRVi_A/exec"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8"
}

# Bắt chuẩn cả dấu "/" và dấu "-" (VD: 413/2026/NĐ-CP, 113/2026/VBHN-TT-BNNMT, 18-NQ/TW, 3538/QĐ-BYT)
DOC_REGEX = re.compile(
    r"(Luật|Nghị định|Thông tư|Văn bản hợp nhất|Quyết định|Nghị quyết|Chỉ thị|Công văn|Kết luận|Hướng dẫn|Kế hoạch)\s+"
    r"(?:số\s*)?([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ0-9\-\/]+)",
    re.IGNORECASE
)

# DANH SÁCH ĐEN: Chỉ lọc đúng các nút Menu tĩnh (ngắn hoặc không có số hiệu)
JUNK_EXACT = [
    "phổ biến giáo dục pháp luật", "tuyên truyền phổ biến pháp luật",
    "xây dựng, phổ biến chính sách, pháp luật", "trang chủ", "liên hệ",
    "giới thiệu", "sơ đồ cổng thông tin", "đăng nhập", "đăng ký"
]

# Dấu hiệu nhận diện chắc chắn 100% là Văn bản Trung ương (Không bao giờ bị lọc sót)
CENTRAL_SIGNALS = [
    "nđ-cp", "nq-cp", "qđ-ttg", "ct-ttg", "vbhn-", "/tw", "-tw", "qh15", "qh16",
    "ubtvqh", "tt-b", "tt-nhnn", "tt-ktnn", "tt-ttcp", "tt-vpcp", "qđ-b", "qđ-nhnn",
    "chính phủ", "thủ tướng", "quốc hội", "bộ ", "ngân hàng nhà nước", "kiểm toán nhà nước"
]

# Từ khóa nhận diện văn bản Địa phương (chỉ xét khi KHÔNG phải văn bản Trung ương)
LOCAL_KEYWORDS = [
    "ubnd", "ủy ban nhân dân", "hđnd", "hội đồng nhân dân", "qđ-ubnd", "nq-hđnd", 
    "ct-ubnd", "kh-ubnd", "tỉnh ", "thành phố ", "sở "
]

# 7 chủ đề trọng tâm dành riêng cho văn bản Địa phương
LOCAL_TOPIC_KEYWORDS = [
    "đất đai", "bảng giá đất", "thu hồi đất", "giao đất", "cho thuê đất", "bồi thường", 
    "tái định cư", "sổ đỏ", "giấy chứng nhận", "nhà ở", "tách thửa", "hợp thửa", "hạn mức đất", "quy hoạch",
    "cán bộ", "công chức", "viên chức", "không chuyên trách", "tuyển dụng", "nâng ngạch", "thăng hạng", 
    "tinh giản", "kỷ luật", "xếp loại", "thi đua", "khen thưởng", "bằng khen", "danh hiệu",
    "tiền lương", "mức lương", "lương tối thiểu", "phụ cấp", "trợ cấp", "chế độ", "chính sách", 
    "lao động", "việc làm", "bảo hiểm xã hội", "bhxh", "bảo hiểm y tế", "bhyt", "người có công", "an sinh",
    "thuế", "lệ phí", "mức thu", "phí", "miễn giảm", "hóa đơn", "hộ kinh doanh", "giá",
    "giao thông", "xử phạt", "vi phạm hành chính", "lái xe", "đăng kiểm", "vận tải",
    "giáo dục", "học phí", "tuyển sinh", "giáo viên", "y tế", "khám bệnh", "chữa bệnh", "bệnh viện"
]

def check_date_is_too_old(title, doc_num="", max_days=60):
    current_year = str(datetime.now().year)
    # 1. Nếu số hiệu văn bản chính đã mang năm hiện tại (VD: /2026/) -> Chắc chắn là văn bản năm nay -> KHÔNG BAO GIỜ CHẶN
    if f"/{current_year}/" in doc_num or f"/{current_year}" in doc_num or f"-{current_year}" in doc_num:
        return False

    # 2. Chỉ tìm ngày ban hành nằm NGAY SAU số hiệu đầu tiên (trước khi xuất hiện tên văn bản thứ 2 được sửa đổi/bổ sung/bãi bỏ)
    # Ví dụ: "Quyết định 171-QĐ/TW, ngày 16/01/2019 về..." -> Bắt ngày 16/01/2019
    # Nhưng: "Quyết định 123/QĐ-UBND bãi bỏ Quyết định 39/2025/QĐ-UBND ngày 31/8/2025" -> Không bắt ngày 31/8/2025 vì nó đi sau VB thứ 2
    first_part = re.split(
        r'sửa đổi|bổ sung|bãi bỏ|thay thế|hướng dẫn|thi hành|kèm theo|thực hiện|đính chính',
        title.lower(), maxsplit=1
    )[0]

    match = re.search(r'(?:ngày|ngay)\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})', first_part)
    if match:
        try:
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            doc_date = datetime(year, month, day)
            if (datetime.now() - doc_date).days > max_days:
                return True
        except:
            pass
    return False

def extract_doc_info(title):
    t_low = title.lower().strip()
    if any(t_low == junk or (len(t_low) < 45 and junk in t_low) for junk in JUNK_EXACT):
        return None, None
        
    m = DOC_REGEX.search(title)
    if m:
        doc_type = m.group(1).capitalize()
        doc_num = m.group(2).upper().rstrip(".,;:")
        return doc_type, doc_num
        
    for kw in ["Nghị định", "Thông tư", "Văn bản hợp nhất", "Quyết định", "Nghị quyết", "Công văn", "Chỉ thị", "Luật", "Dự thảo"]:
        if kw.lower() in t_low:
            if any(act in t_low for act in ["ban hành", "quy định", "về việc", "sửa đổi", "bổ sung", "bãi bỏ", "phê duyệt", "hướng dẫn", "số ", "2026"]):
                # Tránh bắt nhầm ngày tháng (như 28/7) làm số hiệu: bắt buộc phần sau dấu / hoặc - phải có chữ cái (như NĐ-CP, QĐ-UBND, NQ/TW)
                num_m = re.search(r"([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ][A-ZĐƯƠĂÂÊÔ0-9\-\/]*)", title, re.I)
                return kw, (num_m.group(1).upper().rstrip(".,;:") if num_m else "Đang cập nhật")
    return None, None

def classify_and_filter(title, agency, doc_type, doc_num, group):
    if check_date_is_too_old(title, doc_num, max_days=60):
        return False, 99

    text_check = f"{title} {agency} {doc_num}".lower()
    
    # KIỂM TRA TRUNG ƯƠNG TRƯỚC: Nếu có dấu hiệu Trung ương (NĐ-CP, TT-..., Bộ, Chính phủ) thì bảo toàn 100%
    is_central = any(sig in text_check for sig in CENTRAL_SIGNALS) or doc_type in ["Luật", "Nghị định", "Thông tư", "Văn bản hợp nhất"]
    if is_central and "ubnd" not in doc_num.lower() and "hđnd" not in doc_num.lower():
        type_priority = {
            "Luật": 1, "Nghị quyết": 2, "Nghị định": 3, "Thông tư": 4, 
            "Văn bản hợp nhất": 5, "Quyết định": 6, "Chỉ thị": 7, "Công văn": 8
        }.get(doc_type, 9)
        return True, 10 + type_priority

    # NẾU LÀ ĐỊA PHƯƠNG: Lọc theo 7 nhóm chủ đề
    is_local = (group.lower() == "địa phương") or any(lk in text_check for lk in LOCAL_KEYWORDS)
    if is_local:
        if not any(tk in text_check for tk in LOCAL_TOPIC_KEYWORDS):
            return False, 99
        return True, 30

    return True, 20

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
            r = requests.get(url, headers=HEADERS, timeout=8, verify=False)
            if r.status_code != 200:
                source_status.append({"row": row, "count": 0, "status": f"Lỗi ({r.status_code})"})
                continue

            content_text = r.text
            items = []
            if "<rss" in content_text[:500].lower() or "<feed" in content_text[:500].lower() or "news.google.com/rss" in url:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:30]:
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

    new_docs.sort(key=lambda x: x["priority"])

    print(f"2. Phát hiện {len(new_docs)} văn bản mới. Đang đồng bộ về Google Sheet...")
    save_resp = requests.post(WEB_APP_URL, json={
        "action": "save_results",
        "new_docs": new_docs[:60],
        "source_status": source_status
    }, timeout=45)
    print("-> Kết quả lưu:", save_resp.text)

if __name__ == "__main__":
    main()
