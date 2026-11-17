import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DOC_REGEX = re.compile(r"\b(Luật|Nghị định|Thông tư|Văn bản hợp nhất|Quyết định|Nghị quyết|Chỉ thị|Công văn|Kết luận|Hướng dẫn|Kế hoạch|Thông báo|Quy chế|Quy định|Chương trình|Giấy mời|Điện|Công điện|Nghị quyết liên tịch)\s+(?:số\s*)?([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ0-9\-/]+)", re.I)
FALLBACK_TYPES = ["Nghị quyết liên tịch","Văn bản hợp nhất","Công điện","Nghị định","Thông tư","Quyết định","Nghị quyết","Chỉ thị","Công văn","Kết luận","Hướng dẫn","Kế hoạch","Thông báo","Quy chế","Quy định","Chương trình","Giấy mời","Dự thảo","Luật"]
JUNK_EXACT = ["phổ biến giáo dục pháp luật","tuyên truyền phổ biến pháp luật","xây dựng, phổ biến chính sách, pháp luật","trang chủ","liên hệ","giới thiệu","sơ đồ cổng thông tin","đăng nhập","đăng ký"]
CENTRAL_SIGNALS = ["nđ-cp","nq-cp","qđ-ttg","ct-ttg","vbhn-","/tw","-tw","qh15","qh16","ubtvqh","tt-b","tt-nhnn","tt-ktnn","tt-ttcp","tt-vpcp","qđ-b","qđ-nhnn","chính phủ","thủ tướng","quốc hội","bộ ","ngân hàng nhà nước","kiểm toán nhà nước"]
LOCAL_KEYWORDS = ["ubnd","ủy ban nhân dân","hđnd","hội đồng nhân dân","qđ-ubnd","nq-hđnd","ct-ubnd","kh-ubnd","tỉnh ","thành phố ","sở "]

def canonicalize_url(url):
    try:
        p=urlsplit(str(url).strip())
        q=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid","gclid","ref","source"}]
        return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path or "/",urlencode(q,doseq=True),""))
    except Exception: return str(url).strip()

def clean_title(value): return re.sub(r"\s+"," ",str(value or "")).strip()

def is_draft_title(title):
    low=clean_title(title).casefold()
    return any(x in low for x in ("dự thảo","du thao","lấy ý kiến","lay y kien","hồ sơ dự thảo"))

def extract_doc_info(title):
    title=clean_title(title); low=title.casefold()
    if not title or any(low==j or (len(low)<55 and j in low) for j in JUNK_EXACT): return None,None
    m=DOC_REGEX.search(title)
    if m:
        t=m.group(1).strip()
        return t[0].upper()+t[1:].lower(),m.group(2).upper().rstrip(".,;:)")
    for t in FALLBACK_TYPES:
        if t.casefold() in low and any(x in low for x in ("ban hành","quy định","về việc","sửa đổi","bổ sung","bãi bỏ","phê duyệt","hướng dẫn","số ","2026","lấy ý kiến")):
            n=re.search(r"([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ][A-ZĐƯƠĂÂÊÔ0-9\-/]*)",title,re.I)
            return t,n.group(1).upper().rstrip(".,;:)") if n else "Đang cập nhật"
    return None,None

def parse_date(value):
    if not value: return None
    s=str(value).strip()
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%d-%m-%Y","%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%S","%a, %d %b %Y %H:%M:%S %z"):
        try: return datetime.strptime(s[:35],fmt).replace(tzinfo=None)
        except (ValueError,TypeError): pass
    m=re.search(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?!\d)",s)
    if m:
        try: return datetime(int(m.group(3)),int(m.group(2)),int(m.group(1)))
        except ValueError: pass
    return None

def extract_issue_date(title):
    m=re.search(r"\b(?:ngày|ngay)\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b",title,re.I)
    return parse_date("/".join(m.groups())) if m else None

def resolve_document_date(title, source_date=None):
    """Return the best available date and its evidence basis; never invent a scan date."""
    issue_date = extract_issue_date(clean_title(title))
    if issue_date:
        return issue_date, "issue_date"
    posted_date = parse_date(source_date)
    if posted_date:
        return posted_date, "source_posted_date"
    return None, "unknown"


def is_amendment_title(title):
    low = clean_title(title).casefold()
    return any(term in low for term in (
        "sửa đổi", "sửa đổi, bổ sung", "bổ sung", "thay thế", "bãi bỏ",
        "điều chỉnh", "amendment",
    ))


def is_too_old(title,doc_number="",max_days=60,published_date=None,now=None):
    current = now or datetime.utcnow()
    number = str(doc_number or "").strip()
    # A year embedded in the current document number is stronger than years
    # mentioned in the title as references to older instruments.
    year_match = re.search(r"(?:^|/)(20\d{2})(?:/|$)", number)
    if year_match:
        number_year = int(year_match.group(1))
        if number_year < current.year:
            if is_draft_title(title):
                return False
            evidence_date, _ = resolve_document_date(title, published_date)
            if is_amendment_title(title) and evidence_date and evidence_date.year == current.year:
                return False
            return True
        if number_year > current.year:
            return False
    d, _basis = resolve_document_date(title, published_date)
    return bool(d and (current-d).days>max_days)

def classify_document(title,agency="",doc_type="",doc_number="",source_url=""):
    s=f"{title} {agency} {doc_number} {source_url}".casefold()
    if is_draft_title(title): return "Dự thảo"
    if any(x in s for x in ("dangcongsan.vn","dcs.vn","văn kiện đảng","ban chấp hành trung ương","ban bí thư","bộ chính trị","đảng cộng sản")) or re.search(r"(?:NQ|CT|KL|QD|HD)(?:-|/)TW",str(doc_number),re.I): return "Văn bản Đảng"
    if doc_type=="Công văn" or re.search(r"(?:^|/)CV-|/VPCP-|/BTC-|/BTP-|/BXD-",str(doc_number),re.I): return "Công văn"
    if doc_type in {"Luật","Nghị định","Thông tư","Văn bản hợp nhất","Nghị quyết liên tịch"}: return "Văn bản quy phạm pháp luật"
    if any(x in s for x in LOCAL_KEYWORDS): return "Văn bản địa phương"
    return "Văn bản khác"

def classify_and_score(title,agency,doc_type,doc_number,group,published_date=None):
    if is_too_old(title,doc_number,60,published_date): return False,99
    c=classify_document(title,agency,doc_type,doc_number)
    if c=="Dự thảo": return True,12
    if c=="Văn bản Đảng": return True,13
    if c=="Công văn": return True,14
    s=f"{title} {agency} {doc_number}".casefold()
    if any(x in s for x in CENTRAL_SIGNALS) or doc_type in {"Luật","Nghị định","Thông tư","Văn bản hợp nhất"}:
        return True,10+{"Luật":1,"Nghị quyết":2,"Nghị định":3,"Thông tư":4,"Văn bản hợp nhất":5,"Quyết định":6,"Chỉ thị":7}.get(doc_type,9)
    if str(group or "").strip().casefold() in {"địa phương","văn bản địa phương"} or any(x in s for x in LOCAL_KEYWORDS): return True,30
    return True,20

def document_identity(doc_number,title,agency="",link=""):
    n=str(doc_number or "").strip().upper()
    if n and n!="ĐANG CẬP NHẬT":
        parts=n.split("/")
        issuer=parts[-1] if len(parts)>1 else ""
        issuer=re.sub(r"\d{4}","",issuer).strip("-")
        local_authority=any(x in issuer for x in ("UBND","HĐND","SNV","STC","SXD","SGD","SYT","CAT","CA"))
        locality=""
        if local_authority:
            context=f"{title} {agency}"
            match=re.search(r"(?:tỉnh|thành phố|TP[.]?|quận|huyện|thị xã)[ ]+([^,;()]+)",context,re.I)
            if match:
                locality=re.sub("[ ]+"," ",match.group(1)).strip().casefold()
        return f"number:{n}|issuer:{issuer or clean_title(title).casefold()[:90]}|locality:{locality}"
    return f"url:{canonicalize_url(link)}"


def make_fingerprint(doc_number,title):
    """Stable compact fingerprint; never used alone when an official number exists."""
    import hashlib
    number=str(doc_number or "").strip().upper()
    normalized=re.sub(r"[^0-9a-zA-ZÀ-ỹ]+"," ",clean_title(title).casefold()).strip()
    raw=(number+"|"+normalized[:240]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def has_document_date(title,published_date=None):
    """True only when an issue date or a source publication date is available."""
    return bool(extract_issue_date(clean_title(title)) or parse_date(published_date))
