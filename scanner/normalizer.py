import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DOC_REGEX = re.compile(
    r"\b(Luật|Nghị định|Thông tư|Văn bản hợp nhất|Quyết định|Nghị quyết|"
    r"Chỉ thị|Công văn|Kết luận|Hướng dẫn|Kế hoạch|Thông báo|Nghị quyết liên tịch)"
    r"\s+(?:số\s*)?([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ0-9\-\/]+)",
    re.IGNORECASE,
)
FALLBACK_TYPES = [
    "Nghị quyết liên tịch", "Nghị định", "Thông tư", "Văn bản hợp nhất",
    "Quyết định", "Nghị quyết", "Công văn", "Chỉ thị", "Kết luận",
    "Hướng dẫn", "Kế hoạch", "Thông báo", "Luật", "Dự thảo",
]
JUNK_EXACT = [
    "phổ biến giáo dục pháp luật", "tuyên truyền phổ biến pháp luật",
    "xây dựng, phổ biến chính sách, pháp luật", "trang chủ", "liên hệ",
    "giới thiệu", "sơ đồ cổng thông tin", "đăng nhập", "đăng ký",
]
CENTRAL_SIGNALS = [
    "nđ-cp", "nq-cp", "qđ-ttg", "ct-ttg", "vbhn-", "/tw", "-tw", "qh15",
    "qh16", "ubtvqh", "tt-b", "tt-nhnn", "tt-ktnn", "tt-ttcp", "tt-vpcp",
    "qđ-b", "qđ-nhnn", "chính phủ", "thủ tướng", "quốc hội", "bộ ",
    "ngân hàng nhà nước", "kiểm toán nhà nước",
]
LOCAL_KEYWORDS = [
    "ubnd", "ủy ban nhân dân", "hđnd", "hội đồng nhân dân", "qđ-ubnd",
    "nq-hđnd", "ct-ubnd", "kh-ubnd", "tỉnh ", "thành phố ", "sở ",
]
LOCAL_TOPIC_KEYWORDS = [
    "đất đai", "bảng giá đất", "thu hồi đất", "giao đất", "cho thuê đất",
    "bồi thường", "tái định cư", "sổ đỏ", "giấy chứng nhận", "nhà ở",
    "tách thửa", "hợp thửa", "hạn mức đất", "quy hoạch", "cán bộ",
    "công chức", "viên chức", "không chuyên trách", "tuyển dụng",
    "nâng ngạch", "thăng hạng", "tinh giản", "kỷ luật", "xếp loại",
    "thi đua", "khen thưởng", "bằng khen", "danh hiệu", "tiền lương",
    "mức lương", "lương tối thiểu", "phụ cấp", "trợ cấp", "chế độ",
    "chính sách", "lao động", "việc làm", "bảo hiểm xã hội", "bhxh",
    "bảo hiểm y tế", "bhyt", "người có công", "an sinh", "thuế",
    "lệ phí", "mức thu", "phí", "miễn giảm", "hóa đơn", "hộ kinh doanh",
    "giá", "giao thông", "xử phạt", "vi phạm hành chính", "lái xe",
    "đăng kiểm", "vận tải", "giáo dục", "học phí", "tuyển sinh",
    "giáo viên", "y tế", "khám bệnh", "chữa bệnh", "bệnh viện",
]

def canonicalize_url(url):
    try:
        parts = urlsplit(str(url).strip())
        query = [
            (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"fbclid", "gclid", "ref", "source"}
        ]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                           parts.path or "/", urlencode(query, doseq=True), ""))
    except Exception:
        return str(url).strip()

def clean_title(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def extract_doc_info(title):
    title = clean_title(title)
    low = title.casefold()
    if not title or any(low == junk or (len(low) < 55 and junk in low) for junk in JUNK_EXACT):
        return None, None
    match = DOC_REGEX.search(title)
    if match:
        doc_type = match.group(1).strip()
        return doc_type[0].upper() + doc_type[1:].lower(), match.group(2).upper().rstrip(".,;:)")
    for doc_type in FALLBACK_TYPES:
        if doc_type.casefold() in low and any(term in low for term in (
            "ban hành", "quy định", "về việc", "sửa đổi", "bổ sung",
            "bãi bỏ", "phê duyệt", "hướng dẫn", "số ", "2026",
        )):
            number_match = re.search(
                r"([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ][A-ZĐƯƠĂÂÊÔ0-9\-\/]*)",
                title, re.IGNORECASE,
            )
            number = number_match.group(1).upper().rstrip(".,;:)") if number_match else "Đang cập nhật"
            return doc_type, number
    return None, None

def extract_issue_date(title):
    match = re.search(r"\b(?:ngày|ngay)\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", title, re.I)
    if not match:
        return None
    try:
        return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None

def is_too_old(title, doc_number="", max_days=60):
    year = str(datetime.now().year)
    number = str(doc_number or "")
    if f"/{year}/" in number or f"/{year}" in number or f"-{year}" in number:
        return False
    issue_date = extract_issue_date(title)
    return bool(issue_date and (datetime.now() - issue_date).days > max_days)

def classify_and_score(title, agency, doc_type, doc_number, group):
    if is_too_old(title, doc_number, max_days=60):
        return False, 99
    text_check = f"{title} {agency} {doc_number}".lower()
    is_central = any(signal in text_check for signal in CENTRAL_SIGNALS) or doc_type in {
        "Luật", "Nghị định", "Thông tư", "Văn bản hợp nhất"
    }
    if is_central and "ubnd" not in doc_number.lower() and "hđnd" not in doc_number.lower():
        priority = {
            "Luật": 1, "Nghị quyết": 2, "Nghị định": 3, "Thông tư": 4,
            "Văn bản hợp nhất": 5, "Quyết định": 6, "Chỉ thị": 7, "Công văn": 8,
        }.get(doc_type, 9)
        return True, 10 + priority
    is_local = str(group or "").strip().lower() == "địa phương" or any(
        keyword in text_check for keyword in LOCAL_KEYWORDS
    )
    if is_local:
        if not any(keyword in text_check for keyword in LOCAL_TOPIC_KEYWORDS):
            return False, 99
        return True, 30
    return True, 20

def make_fingerprint(doc_number, title):
    return f"[{doc_number}] {clean_title(title)[:70].lower()}"
