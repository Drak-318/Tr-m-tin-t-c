import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DOC_REGEX = re.compile(
    r"\\b(Luật|Nghị định|Thông tư|Văn bản hợp nhất|Quyết định|Nghị quyết|"
    r"Chỉ thị|Công văn|Kết luận|Hướng dẫn|Kế hoạch|Thông báo|Quy chế|Quy định|"
    r"Chương trình|Giấy mời|Điện|Công điện|Nghị quyết liên tịch)"
    r"\\s+(?:số\\s*)?([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ0-9\\-\\/]+)",
    re.IGNORECASE,
)
FALLBACK_TYPES = [
    "Nghị quyết liên tịch", "Văn bản hợp nhất", "Công điện", "Nghị định",
    "Thông tư", "Quyết định", "Nghị quyết", "Chỉ thị", "Công văn",
    "Kết luận", "Hướng dẫn", "Kế hoạch", "Thông báo", "Quy chế",
    "Quy định", "Chương trình", "Giấy mời", "Dự thảo", "Luật",
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
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "ref", "source"}]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query, doseq=True), ""))
    except Exception:
        return str(url).strip()

def clean_title(value):
    return re.sub(r"\\s+", " ", str(value or "")).strip()

def is_draft_title(title):
    low = clean_title(title).casefold()
    return any(x in low for x in ("dự thảo", "du thao", "lấy ý kiến", "lay y kien", "hồ sơ dự thảo"))

def extract_doc_info(title):
    title = clean_title(title)
    low = title.casefold()
    if not title or any(low == junk or (len(low) < 55 and junk in low) for junk in JUNK_EXACT):
        return None, None
    match = DOC_REGEX.search(title)
    if match:
        raw_type = match.group(1).strip()
        doc_type = raw_type[0].upper() + raw_type[1:].lower()
        return doc_type, match.group(2).upper().rstrip(".,;:)")
    for doc_type in FALLBACK_TYPES:
        if doc_type.casefold() in low and any(term in low for term in (
            "ban hành", "quy định", "về việc", "sửa đổi", "bổ sung",
            "bãi bỏ", "phê duyệt", "hướng dẫn", "số ", "2026", "lấy ý kiến",
        )):
            number_match = re.search(r"([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ][A-ZĐƯƠĂÂÊÔ0-9\\-/]*)", title, re.I)
            number = number_match.group(1).upper().rstrip(".,;:)") if number_match else "Đang cập nhật"
            return doc_type, number
    return None, None

def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(value[:35], fmt).replace(tzinfo=None)
        except (ValueError, TypeError):
            continue
    match = re.search(r"(?<!\\d)(\\d{1,2})[/-](\\d{1,2})[/-](\\d{4})(?!\\d)", value)
    if match:
        try:
            return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            pass
    return None

def extract_issue_date(title):
    match = re.search(r"\\b(?:ngày|ngay)\\s*(\\d{1,2})[/-](\\d{1,2})[/-](\\d{4})\\b", title, re.I)
    return parse_date("/".join(match.groups())) if match else None

def is_too_old(title, doc_number="", max_days=60, published_date=None, now=None):
    today = now or datetime.utcnow()
    # Ngày đăng nguồn ưu tiên để phát hiện bài được đăng lại; ngày ban hành là phương án dự phòng.
    date_value = parse_date(published_date) or extract_issue_date(title)
    if date_value is None:
        return False
    return (today - date_value).days > max_days

def classify_document(title, agency="", doc_type="", doc_number="", source_url=""):
    text_all = f"{title} {agency} {doc_number} {source_url}".casefold()
    if is_draft_title(title):
        return "Dự thảo"
    party_signals = ("dangcongsan.vn", "dcs.vn", "văn kiện đảng", "ban chấp hành trung ương",
                     "ban bí thư", "bộ chính trị", "ban tuyên giáo", "đảng cộng sản")
    if any(x in text_all for x in party_signals) or re.search(r"(?:NQ|CT|KL|QD|HD)-TW", str(doc_number), re.I):
        return "Văn bản Đảng"
    if doc_type == "Công văn" or re.search(r"(?:^|/)CV-|/VPCP-|/BTC-|/BTP-|/BXD-", str(doc_number), re.I):
        return "Công văn"
    if doc_type in {"Luật", "Nghị định", "Thông tư", "Văn bản hợp nhất", "Nghị quyết liên tịch"}:
        return "Văn bản quy phạm pháp luật"
    if any(x in text_all for x in LOCAL_KEYWORDS):
        return "Văn bản địa phương"
    return "Văn bản khác"

def classify_and_score(title, agency, doc_type, doc_number, group, published_date=None):
    if is_too_old(title, doc_number, 60, published_date):
        return False, 99
    category = classify_document(title, agency, doc_type, doc_number)
    if category == "Dự thảo":
        return True, 12
    if category == "Văn bản Đảng":
        return True, 13
    if category == "Công văn":
        return True, 14
    text_check = f"{title} {agency} {doc_number}".casefold()
    is_central = any(signal in text_check for signal in CENTRAL_SIGNALS) or doc_type in {
        "Luật", "Nghị định", "Thông tư", "Văn bản hợp nhất"
    }
    if is_central:
        priority = {"Luật": 1, "Nghị quyết": 2, "Nghị định": 3, "Thông tư": 4,
                    "Văn bản hợp nhất": 5, "Quyết định": 6, "Chỉ thị": 7}.get(doc_type, 9)
        return True, 10 + priority
    is_local = str(group or "").strip().casefold() in {"địa phương", "văn bản địa phương"} or any(
        keyword in text_check for keyword in LOCAL_KEYWORDS
    )
    if is_local:
        return True, 30
    return True, 20

def document_identity(doc_number, title, agency="", link=""):
    number = str(doc_number or "").strip().upper()
    if number and number != "ĐANG CẬP NHẬT":
        # Phần ký hiệu sau dấu / hoặc - thường chỉ cơ quan ban hành (UBND, SNV, STC...).
        suffix = re.split(r"[/]", number)
        issuer = suffix[-1] if len(suffix) > 1 else ""
        issuer = re.sub(r"\\d{4}", "", issuer).strip("-")
        if issuer:
            return f"number:{number}|issuer:{issuer}"
        return f"number:{number}|title:{clean_title(title).casefold()[:100]}"
    return f"url:{canonicalize_url(link)}"
