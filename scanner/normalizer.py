import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DOC_REGEX = re.compile(r"\b(Luật|Nghị định|Thông tư|Văn bản hợp nhất|Quyết định|Nghị quyết|Chỉ thị|Công văn|Kết luận|Hướng dẫn|Kế hoạch|Thông báo|Quy chế|Quy định|Chương trình|Giấy mời|Điện|Công điện|Nghị quyết liên tịch)\s+(?:số\s*)?([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ0-9\-/]+)", re.I)
FALLBACK_TYPES = ["Nghị quyết liên tịch","Văn bản hợp nhất","Công điện","Nghị định","Thông tư","Quyết định","Nghị quyết","Chỉ thị","Công văn","Kết luận","Hướng dẫn","Kế hoạch","Thông báo","Quy chế","Quy định","Chương trình","Giấy mời","Dự thảo","Luật"]
JUNK_EXACT = ["phổ biến giáo dục pháp luật","tuyên truyền phổ biến pháp luật","xây dựng, phổ biến chính sách, pháp luật","trang chủ","liên hệ","giới thiệu","sơ đồ cổng thông tin","đăng nhập","đăng ký"]
CENTRAL_SIGNALS = ["nđ-cp","nq-cp","qđ-ttg","ct-ttg","vbhn-","/tw","-tw","qh15","qh16","ubtvqh","tt-b","tt-nhnn","tt-ktnn","tt-ttcp","tt-vpcp","qđ-b","qđ-nhnn","chính phủ","thủ tướng","quốc hội","bộ ","ngân hàng nhà nước","kiểm toán nhà nước"]
LOCAL_KEYWORDS = ["ubnd","ủy ban nhân dân","hđnd","hội đồng nhân dân","qđ-ubnd","nq-hđnd","ct-ubnd","kh-ubnd","tỉnh ","thành phố ","sở "]

# Local documents are retained only when they concern a policy or issue with
# broad public relevance. These are deliberately topic-based, not document-type
# based: a local resolution or decision can still be important.
LOCAL_RELEVANCE_TOPICS = (
    # Đất đai, quy hoạch, nhà ở và hạ tầng có tác động rộng
    "đất đai", "quyền sử dụng đất", "bồi thường", "tái định cư", "bảng giá đất", "giá đất",
    "quy hoạch sử dụng đất", "kế hoạch sử dụng đất", "đấu giá quyền sử dụng đất",
    "nhà ở xã hội", "nhà ở", "quy hoạch xây dựng", "quy hoạch đô thị",
    "đầu tư công", "giao thông", "hạ tầng", "đấu thầu", "lựa chọn nhà thầu",
    "mua sắm công",
    # Y tế, giáo dục, lao động và an sinh
    "y tế", "khám chữa bệnh", "khám bệnh", "chữa bệnh", "bảo hiểm y tế",
    "viện phí", "giá dịch vụ y tế", "giá dịch vụ khám", "dược",
    "giáo dục", "đào tạo", "tuyển sinh", "học phí", "giáo viên",
    "học sinh", "trường học", "bảo hiểm xã hội", "người lao động",
    "trợ cấp", "an sinh", "tiền lương", "phụ cấp", "vị trí việc làm",
    "tuyển dụng viên chức", "tuyển dụng công chức",
    # Thuế, phí, thủ tục và lĩnh vực công có phạm vi chung
    "thuế", "phí", "lệ phí", "mức thu", "miễn giảm", "thủ tục hành chính",
    "cải cách hành chính", "tổ chức bộ máy", "định mức kinh tế - kỹ thuật",
    "định mức kinh tế kỹ thuật", "phòng chống thiên tai", "ứng phó thiên tai",
    "môi trường", "ô nhiễm", "chất thải", "chuyển đổi số",
)

PERSONAL_OR_ONE_OFF_PATTERNS = (
    r"\bthu hồi đất\b.{0,180}\b(?:ông|bà|hộ gia đình|cá nhân|tổ chức)\b",
    r"\b(?:giao đất|cho thuê đất)\b.{0,180}\b(?:ông|bà|hộ gia đình|cá nhân)\b",
    r"\b(?:thửa đất số|tờ bản đồ số)\b",
)

def is_local_scope(group="", agency="", source_url=""):
    """Infer local scope from source metadata as well as its configured group.

    Some local portals were accidentally labelled 'Văn Bản TW' in the CSV;
    the issuing/source agency name therefore acts as a second signal.
    """
    g = clean_title(group).casefold()
    a = clean_title(agency).casefold()
    if g in {"địa phương", "văn bản địa phương", "công an"}:
        return True
    if re.search(r"^(?:ubnd|ủy ban nhân dân|hđnd|hội đồng nhân dân|sở\s|văn phòng ubnd|đảng bộ tỉnh)", a):
        return True
    if a.startswith("công an "):
        return True
    if any(x in a for x in ("tỉnh ", "thành phố ", "tp. ", "quận ", "huyện ", "thị xã ", "xã ", "phường ")):
        return True
    if a.startswith(("đà nẵng ", "hải phòng ", "tp.hcm", "tp. hồ chí minh", "huế -", "thanh khê ")):
        return True
    return False

def is_personal_or_one_off_document(title, doc_type="", doc_number=""):
    """Reject individual administrative outcomes, not generally applicable rules."""
    text = clean_title(f"{title} {doc_type} {doc_number}").casefold()
    kind = clean_title(doc_type).casefold()
    is_decision = kind == "quyết định"

    award_action = re.search(r"\b(?:khen thưởng|truy tặng|tặng bằng khen)\b", text, re.I)
    award_recipient = re.search(r"\b(?:cho ông|cho bà|cho cá nhân|các cá nhân|tập thể|đơn vị)\b", text, re.I)
    if award_action and (is_decision or award_recipient):
        return True

    # A decision imposing a fine on one case is excluded. General decrees or
    # circulars that regulate sanctioning regimes remain in the collection.
    if is_decision and re.search(r"\b(?:xử phạt|phạt tiền)\b", text, re.I):
        return True

    # Individual certificates/appointments are case outcomes, not public policy.
    if is_decision and re.search(
        r"\b(?:bổ nhiệm|điều động|luân chuyển|miễn nhiệm|tiếp nhận)\b.{0,100}\b(?:ông|bà|cá nhân)\b",
        text, re.I
    ):
        return True
    if is_decision and re.search(
        r"\b(?:cấp|cấp lại|thu hồi)\b.{0,100}\b(?:chứng chỉ|bằng(?: tốt nghiệp)?|giấy chứng nhận|giấy phép hành nghề)\b.{0,80}\b(?:cho ông|cho bà|cá nhân|hộ gia đình)\b",
        text, re.I
    ):
        return True

    permit_action = re.search(
        r"\b(?:cấp|cấp lại|gia hạn|điều chỉnh|thu hồi|hủy bỏ)\b.{0,100}"
        r"\b(?:giấy phép|giấy chứng nhận đủ điều kiện|chứng chỉ hành nghề)\b",
        text, re.I
    )
    named_recipient = re.search(
        r"\b(?:cho|đối với|của)\s+(?:ông|bà|cá nhân|hộ gia đình|công ty|doanh nghiệp|tổ chức|"
        r"trung tâm|bệnh viện|trường|hợp tác xã)\b",
        text, re.I
    )
    if permit_action and named_recipient:
        return True

    return any(re.search(pattern, text, re.I) for pattern in PERSONAL_OR_ONE_OFF_PATTERNS)

def is_relevant_local_document(title, doc_type="", doc_number=""):
    """True only for locally issued items on the user's selected public-interest topics."""
    text = clean_title(f"{title} {doc_type} {doc_number}").casefold()
    if is_personal_or_one_off_document(title, doc_type, doc_number):
        return False
    return any(topic in text for topic in LOCAL_RELEVANCE_TOPICS)


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
    # Prefer the local/issuing document number at the beginning of the title
    # over a central law/circular merely cited later in a rollout dispatch.
    leading_dispatch=re.match(
        r"^\s*(?:công văn|văn bản)\s+(?:số\s*)?([0-9]{1,7}/(?:[0-9]{4}/)?[A-ZĐƯƠĂÂÊÔ0-9-]+)",
        title,re.I
    )
    if leading_dispatch:
        return "Công văn",leading_dispatch.group(1).upper().rstrip(".,;:)")
    # Many portals omit "Công văn" but show the official number followed by V/v.
    letter=re.search(r"(?:văn bản\s+)?(?:số\s*[:：]?\s*)?([0-9]+(?:/[0-9]{4})?/[A-ZĐƯƠĂÂÊÔ0-9-]+)\s+V/v\b",title,re.I)
    if letter:
        return "Công văn",letter.group(1).upper().rstrip(".,;:)")
    m=DOC_REGEX.search(title)
    if m:
        t=m.group(1).strip()
        return t[0].upper()+t[1:].lower(),m.group(2).upper().rstrip(".,;:)")
    for t in FALLBACK_TYPES:
        # Fallback classification is only valid when the document type leads
        # the title. Searching anywhere caused "pháp luật" to become "Luật".
        if re.match(r"^\s*(?:dự thảo\s+)?" + re.escape(t) + r"\b", title, re.I) and any(
            x in low for x in ("ban hành","quy định","về việc","sửa đổi","bổ sung","bãi bỏ","phê duyệt","hướng dẫn","số ","2026","lấy ý kiến")
        ):
            n=re.search(r"([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ][A-ZĐƯƠĂÂÊÔ0-9/-]*)",title,re.I)
            return t,n.group(1).upper().rstrip(".,;:)") if n else "Đang cập nhật"

    # Some portals show only the official number and omit its document type.
    # Infer the type from a known, unambiguous suffix instead of dropping it.
    number_match=re.search(
        r"(?<![0-9])([0-9]+(?:/[0-9]{4})?[/-][A-ZĐƯƠĂÂÊÔ][A-ZĐƯƠĂÂÊÔ0-9/-]*)",
        title,re.I
    )
    if number_match:
        number=number_match.group(1).upper().rstrip(".,;:)")
        components=number.split("/")
        suffix=components[-1] if components else ""
        if suffix.upper()=="TW" and len(components)>1:
            code=components[-2].split("-")[-1].upper()
        else:
            if suffix.isdigit() and len(components)>1:
                suffix=components[-2]
            code=suffix.split("-")[0].upper()
        suffix_types={
            "NĐ":"Nghị định","TT":"Thông tư","QĐ":"Quyết định","QD":"Quyết định",
            "NQ":"Nghị quyết","KL":"Kết luận","KH":"Kế hoạch","HD":"Hướng dẫn",
            "CT":"Chỉ thị","CV":"Công văn","TB":"Thông báo","QC":"Quy chế",
            "CĐ":"Công điện","CD":"Công điện",
        }
        if code in suffix_types:
            return suffix_types[code],number
    # Some government portals list only an administrative dispatch number,
    # e.g. 11560/VPCP-CN, followed by a separate date. Recognize common issuer
    # prefixes as official letters instead of accidentally reading the date.
    dispatch = re.search(
        r"(?<![0-9])([0-9]{1,7}/(?:VPCP|BTC|BTP|BXD|BCT|BNV|BGDĐT|BYT|BCA|BQP|BHXH|TCT|TCHQ|TTCP|TAND|VKSND)(?:-[A-ZĐƯƠĂÂÊÔ0-9]+)+)(?![A-ZĐƯƠĂÂÊÔ0-9])",
        title, re.I
    )
    if dispatch:
        return "Công văn", dispatch.group(1).upper().rstrip(".,;:)")
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
    """Only exclude a document when an actual date signal proves it is old.

    An old year mentioned in a document number is not enough to discard an
    undated candidate: it may be a current amendment, a republication, or an
    item whose detail page still needs human verification.
    """
    current = now or datetime.utcnow()
    d, _basis = resolve_document_date(title, published_date)
    if not d:
        return False
    return (current-d).days > max_days

def classify_document(title,agency="",doc_type="",doc_number="",source_url=""):
    s=f"{title} {agency} {doc_number} {source_url}".casefold()
    if is_draft_title(title): return "Dự thảo"
    if any(x in s for x in ("dangcongsan.vn","dcs.vn","văn kiện đảng","ban chấp hành trung ương","ban bí thư","bộ chính trị","đảng cộng sản")) or re.search(r"(?:NQ|CT|KL|QD|HD)(?:-|/)TW",str(doc_number),re.I): return "Văn bản Đảng"
    if doc_type=="Công văn" or re.search(r"(?:^|/)CV-|/VPCP-|/BTC-|/BTP-|/BXD-",str(doc_number),re.I): return "Công văn"
    if doc_type in {"Luật","Nghị định","Thông tư","Văn bản hợp nhất","Nghị quyết liên tịch"}:
        return "Văn bản quy phạm pháp luật"
    if doc_type=="Nghị quyết" and (
        re.search(r"(?:^|/)(?:NQ-(?:CP|QH|UBTVQH|HĐND|HDND|LT)|QH\d+)(?:$|/)",str(doc_number),re.I)
        or any(x in s for x in ("quốc hội","chính phủ","ủy ban thường vụ quốc hội","hội đồng nhân dân","hđnd"))
    ):
        return "Văn bản quy phạm pháp luật"
    if any(x in s for x in LOCAL_KEYWORDS): return "Văn bản địa phương"
    return "Văn bản khác"

def classify_and_score(title,agency,doc_type,doc_number,group,published_date=None):
    if is_too_old(title,doc_number,60,published_date): return False,99

    # Individual/case-specific outcomes are not useful to this collection,
    # regardless of whether they come from a central or local portal.
    if is_personal_or_one_off_document(title,doc_type,doc_number):
        return False,98

    local_scope = is_local_scope(group,agency)
    document_signals = f"{title} {doc_number}".casefold()
    central_document = (
        any(x in document_signals for x in CENTRAL_SIGNALS)
        or bool(re.search(r"(?:/NĐ-CP|/NQ-CP|/QĐ-TTG|/CT-TTG|/TT-[A-ZĐ0-9-]+|/QH[0-9]+|/VBHN-[A-Z0-9-]+)$", str(doc_number), re.I))
    )
    # Local portals are discovery channels, not a reason to ingest every
    # provincial dispatch. A central instrument is accepted only when the
    # item itself is titled as that instrument, not merely citing it.
    if local_scope:
        direct_central_title = bool(re.match(
            r"^\s*(?:luật|nghị định|thông tư|nghị quyết|quyết định|chỉ thị|"
            r"văn bản hợp nhất|pháp lệnh)\b", clean_title(title), re.I
        ))
        central_number = bool(re.search(
            r"/(?:NĐ-CP|NQ-(?:CP|QH[0-9]+|UBTVQH[0-9]+)|QĐ-TTg|CT-TTg|TT-[A-ZĐ0-9-]+|VBHN-[A-Z0-9-]+|QH[0-9]+)$",
            str(doc_number), re.I
        ))
        if direct_central_title and central_number and doc_type != "Công văn":
            return True,10
        if not is_relevant_local_document(title,doc_type,doc_number):
            return False,97
        central_reference = bool(re.search(
            r"(?:/NĐ-CP|/NQ-CP|/QĐ-TTg|/CT-TTg|/TT-[A-ZĐ0-9-]+|/QH[0-9]+)",
            clean_title(title), re.I
        ))
        rollout_language = bool(re.search(
            r"\b(?:triển khai|tổ chức thực hiện|hướng dẫn thực hiện|thực hiện)\b",
            clean_title(title), re.I
        ))
        if doc_type == "Công văn" and central_reference and rollout_language:
            return False,96
        return True,30

    c=classify_document(title,agency,doc_type,doc_number)
    if c=="Dự thảo": return True,12
    if c=="Văn bản Đảng": return True,13
    if c=="Công văn": return True,14
    s=f"{title} {agency} {doc_number}".casefold()
    if central_document or any(x in s for x in CENTRAL_SIGNALS) or doc_type in {"Luật","Nghị định","Thông tư","Văn bản hợp nhất"}:
        return True,10+{"Luật":1,"Nghị quyết":2,"Nghị định":3,"Thông tư":4,"Văn bản hợp nhất":5,"Quyết định":6,"Chỉ thị":7}.get(doc_type,9)
    return True,20

def document_identity(doc_number,title,agency="",link=""):
    n=str(doc_number or "").strip().upper()
    # A date-like fragment such as "11/2026" is not a legal-document number.
    # Without an issuing-code suffix, fall back to the canonical URL rather
    # than risking a false duplicate across unrelated documents.
    if n and n!="ĐANG CẬP NHẬT" and re.search(r"/[A-ZĐƯƠĂÂÊÔ]{1,}", n):
        parts=n.split("/")
        issuer=parts[-1] if len(parts)>1 else ""
        issuer=re.sub(r"\d{4}","",issuer).strip("-")
        agency_clean=clean_title(agency).casefold()
        local_authority=(
            any(x in issuer for x in ("UBND","HĐND","SNV","STC","SXD","SGD","SYT","CAT","CA"))
            or bool(re.search(r"^(?:ubnd|ủy ban nhân dân|hđnd|hội đồng nhân dân|sở\s|công an )",agency_clean))
        )
        locality=""
        if local_authority:
            context=f"{title} {agency}"
            match=re.search(r"(?:tỉnh|thành phố|TP[.]?|quận|huyện|thị xã)[ ]+([^,;()]+)",context,re.I)
            if match:
                locality=re.sub("[ ]+"," ",match.group(1)).strip().casefold()
            if not locality:
                host=urlsplit(link).hostname or agency_clean[:90] or "unknown"
                locality="unresolved-source:"+host.casefold()
        if not issuer:
            issuer=agency_clean[:90] or clean_title(title).casefold()[:90]
        return f"number:{n}|issuer:{issuer}|locality:{locality}"
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
