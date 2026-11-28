/**
 * TRẠM VĂN BẢN PHÁP LUẬT - CỔNG ĐỒNG BỘ V14.0
 * Vai trò: API nhận dữ liệu duy nhất từ GitHub Actions.
 * Không chạy bộ quét nguồn độc lập tại Apps Script để tránh hai bộ quét ghi trùng.
 *
 * Bảng "Văn Bản Mới": A thời điểm nhận | B loại | C nguồn/cơ quan | D tiêu đề
 * E số hiệu | F liên kết | G fingerprint | H nhóm văn bản
 *
 * Bảng "_Bộ Nhớ Văn Bản": A URL | B số hiệu | C tiêu đề | D fingerprint
 * E loại | F thời điểm lưu | G định danh chống trùng
 */

const CONFIG = {
  SHEET_RESULTS: "Văn Bản Mới",
  SHEET_MEMORY: "_Bộ Nhớ Văn Bản",
  SHEET_SOURCES: "Nguồn Quét Văn Bản",
  SHEET_RADAR: "Cảnh Báo VB Thiếu",
  TIMEZONE: "Asia/Ho_Chi_Minh",
  MEMORY_HEADERS: ["URL", "Số hiệu", "Tiêu đề", "Fingerprint", "Loại văn bản", "Thời điểm lưu", "Định danh"],
  RESULT_HEADERS: ["Thời điểm nhận", "Loại văn bản", "Nguồn/Cơ quan", "Tiêu đề", "Số hiệu", "Liên kết", "Fingerprint", "Nhóm văn bản"]
};

// Exact official domains in the GitHub-managed priority registry that may not
// yet exist in the legacy Google Sheets source tab.
const EXTRA_ALLOWED_SOURCE_HOSTS = new Set([
  "vbpl.vn",
  "vbpq.mof.gov.vn",
  "kiemtra-phapche.hcm.edu.vn",
  "snv.lamdong.gov.vn",
  "qppl.thanhhoa.gov.vn",
  "syt.lamdong.gov.vn",
  "stc.lamdong.gov.vn",
  "stp.lamdong.gov.vn",
  "songoaivu.lamdong.gov.vn",
  "snnmt.lamdong.gov.vn",
  "sxd.lamdong.gov.vn",
  "sxd.quangngai.gov.vn",
  "nhandan.vn",
  "news.google.com"
]);

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return jsonOutput_({status: "ok", service: "Tram Tin Tuc API", version: "14.0"});
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonOutput_({status: "error", message: "Thiếu nội dung yêu cầu."});
    }

    const data = JSON.parse(e.postData.contents);
    const expectedToken = PropertiesService.getScriptProperties().getProperty("SHEETS_API_TOKEN");
    if (data.action === "fetch_source" && !expectedToken) {
      return jsonOutput_({status: "error", message: "Chưa cấu hình token xác thực cho chức năng lấy nguồn."});
    }
    if (expectedToken && String(data.token || "") !== expectedToken) {
      return jsonOutput_({status: "error", message: "API token không hợp lệ."});
    }

    // Fetching a public source is read-only; do not hold the spreadsheet write lock.
    if (data.action === "fetch_source") {
      return jsonOutput_(fetchSource_(SpreadsheetApp.getActiveSpreadsheet(), data));
    }

    if (!lock.tryLock(25000)) {
      return jsonOutput_({status: "error", message: "Hệ thống đang xử lý lượt đồng bộ khác. Hãy thử lại."});
    }

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (data.action === "get_sources") {
      return jsonOutput_(getSources_(ss));
    }
    if (data.action === "save_results") {
      return jsonOutput_(saveResults_(ss, data));
    }
    return jsonOutput_({status: "error", message: "Action không được hỗ trợ."});
  } catch (err) {
    return jsonOutput_({status: "error", message: String(err && err.stack ? err.stack : err)});
  } finally {
    try { lock.releaseLock(); } catch (ignored) {}
  }
}

/**
 * Read-only source proxy. Only HTTPS hosts already present in the source registry
 * are allowed; this endpoint cannot be used as an arbitrary URL fetch proxy.
 */
function fetchSource_(ss, data) {
  const rawUrl = String(data.url || "").trim();
  if (!/^https:\/\//i.test(rawUrl)) {
    return {status: "error", message: "Chỉ chấp nhận URL HTTPS."};
  }
  const parsed = rawUrl.match(/^https:\/\/([^\/?#:]+)(?::(\d+))?/i);
  if (!parsed) return {status: "error", message: "URL không hợp lệ."};
  const host = String(parsed[1] || "").toLowerCase();
  if (!host || parsed[2] || host === "localhost" || /^\d+(\.\d+){3}$/.test(host) ||
      host.endsWith(".local") || host.endsWith(".internal")) {
    return {status: "error", message: "Địa chỉ nguồn không được phép."};
  }

  const sourceSheet = ss.getSheetByName(CONFIG.SHEET_SOURCES);
  if (!sourceSheet || sourceSheet.getLastRow() < 2) {
    return {status: "error", message: "Không có danh sách nguồn để xác thực."};
  }
  const values = sourceSheet.getRange(2, 2, sourceSheet.getLastRow() - 1, 1).getDisplayValues();
  const allowedHosts = new Set(EXTRA_ALLOWED_SOURCE_HOSTS);
  values.forEach(row => {
    const match = String(row[0] || "").trim().match(/^https:\/\/([^\/?#:]+)/i);
    if (match) allowedHosts.add(match[1].toLowerCase());
  });
  if (!allowedHosts.has(host)) {
    return {status: "error", message: "Tên miền không nằm trong danh sách nguồn đã cấu hình."};
  }

  try {
    const response = UrlFetchApp.fetch(rawUrl, {
      method: "get",
      followRedirects: true,
      muteHttpExceptions: true,
      validateHttpsCertificates: true,
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; TramTinTuc/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8"
      }
    });
    const statusCode = response.getResponseCode();
    const headers = response.getHeaders();
    const contentType = String(headers["Content-Type"] || headers["content-type"] || "");
    const body = response.getContentText();
    if (body.length > 400000) {
      return {status: "error", http_status: statusCode, message: "Nội dung vượt giới hạn 400 KB; bỏ qua để tránh trả dữ liệu bị cắt."};
    }
    if (statusCode < 200 || statusCode >= 300) {
      return {status: "error", http_status: statusCode, message: "Website nguồn trả HTTP " + statusCode};
    }
    if (!/(text\/html|application\/xhtml|application\/xml|text\/xml|rss|atom)/i.test(contentType) &&
        !/^\s*<(?:!doctype\s+html|html|rss|feed)/i.test(body)) {
      return {status: "error", http_status: statusCode, message: "Kiểu dữ liệu không phải HTML/XML."};
    }
    return {
      status: "ok",
      http_status: statusCode,
      content_type: contentType || "text/html",
      final_url: rawUrl,
      body: body
    };
  } catch (err) {
    return {status: "error", message: "UrlFetchApp: " + String(err && err.message ? err.message : err)};
  }
}

function ensureMemorySheet_(ss) {
  let sheet = ss.getSheetByName(CONFIG.SHEET_MEMORY);
  if (!sheet) sheet = ss.insertSheet(CONFIG.SHEET_MEMORY);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, CONFIG.MEMORY_HEADERS.length).setValues([CONFIG.MEMORY_HEADERS]);
  } else if (!String(sheet.getRange(1, 7).getDisplayValue() || "").trim()) {
    sheet.getRange(1, 7).setValue("Định danh");
  }
  return sheet;
}

function getSources_(ss) {
  const sourceSheet = ss.getSheetByName(CONFIG.SHEET_SOURCES);
  const sources = [];
  if (sourceSheet && sourceSheet.getLastRow() >= 2) {
    const values = sourceSheet.getDataRange().getValues();
    for (let i = 1; i < values.length; i++) {
      const url = String(values[i][1] || "").trim();
      if (!url) continue;
      sources.push({
        row: i + 1,
        name: String(values[i][0] || "").trim() || "Nguồn dòng " + (i + 1),
        url: url,
        group: String(values[i][3] || "Văn Bản TW").trim()
      });
    }
  }

  const memory = ensureMemorySheet_(ss);
  const migrated = backfillLegacyMemory_(ss, memory);
  if (migrated) Logger.log("Đã khôi phục " + migrated + " bản ghi cũ vào bộ nhớ chống trùng.");
  const links = [];
  const numbers = [];
  const identities = [];
  if (memory.getLastRow() >= 2) {
    const rows = memory.getRange(2, 1, memory.getLastRow() - 1, 7).getDisplayValues();
    rows.forEach(row => {
      if (row[0]) links.push(String(row[0]).trim());
      if (row[1]) numbers.push(String(row[1]).trim().toUpperCase());
      if (row[6]) identities.push(String(row[6]).trim());
    });
  }
  return {status: "ok", sources: sources, existingLinks: links, existingNumbers: numbers, existingIdentities: identities, legacyMemoryBackfilled: migrated || 0};
}


/**
 * Rebuild the anti-duplicate memory from the existing results sheet.
 * This is additive only: it never deletes or edits historical result rows.
 */
function backfillLegacyMemory_(ss, memory) {
  const resultSheet = ss.getSheetByName(CONFIG.SHEET_RESULTS);
  if (!resultSheet || resultSheet.getLastRow() < 2) return 0;

  const knownLinks = new Set();
  const knownIdentities = new Set();
  if (memory.getLastRow() >= 2) {
    memory.getRange(2, 1, memory.getLastRow() - 1, 7).getDisplayValues().forEach(row => {
      const link = normalizeUrl_(row[0]);
      const identity = String(row[6] || "").trim();
      if (link) knownLinks.add(link);
      if (identity) knownIdentities.add(identity);
    });
  }

  const lastRow = resultSheet.getLastRow();
  const rows = resultSheet.getRange(2, 1, lastRow - 1, 8).getDisplayValues();
  const now = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, "dd/MM/yyyy HH:mm:ss");
  const additions = [];
  rows.forEach(row => {
    const docType = String(row[1] || "").trim();
    const agency = cleanAgency_(row[2]);
    const title = String(row[3] || "").trim();
    const number = String(row[4] || "").trim();
    const link = normalizeUrl_(row[5]);
    const fingerprint = String(row[6] || "").trim();
    if (!link || knownLinks.has(link)) return;
    const identity = legacyDocumentIdentity_(number, title, agency, link);
    if (knownIdentities.has(identity)) {
      // Preserve the additional URL as an alias so the same legacy item
      // cannot be imported again through another portal.
      additions.push([link, number, title.toLowerCase(), fingerprint, docType, now, identity]);
      knownLinks.add(link);
      return;
    }
    additions.push([link, number, title.toLowerCase(), fingerprint, docType, now, identity]);
    knownLinks.add(link);
    knownIdentities.add(identity);
  });

  if (additions.length) {
    const start = memory.getLastRow() + 1;
    memory.getRange(start, 1, additions.length, 7).setValues(additions);
  }
  return additions.length;
}

/**
 * Keep this identity format aligned with scanner.normalizer.document_identity.
 * Local issuer numbers include locality; uncertain locality falls back to
 * the source host, avoiding unsafe merges across provinces.
 */
function legacyDocumentIdentity_(number, title, agency, link) {
  const n = String(number || "").trim().toUpperCase();
  if (n && n !== "ĐANG CẬP NHẬT" && /\/[A-ZĐƯƠĂÂÊÔ]{1,}/.test(n)) {
    const parts = n.split("/");
    let issuer = parts[parts.length - 1] || "";
    issuer = issuer.replace(/\d{4}/g, "").replace(/^-+|-+$/g, "");
    const agencyClean = String(agency || "").replace(/\s+/g, " ").trim().toLowerCase();
    const localAuthority = /(UBND|HĐND|SNV|STC|SXD|SGD|SYT|CAT|CA)/.test(issuer) ||
      /^(ubnd|ủy ban nhân dân|hđnd|hội đồng nhân dân|sở\s|công an )/.test(agencyClean);
    let locality = "";
    if (localAuthority) {
      const context = String(title || "") + " " + String(agency || "");
      const match = context.match(/(?:tỉnh|thành phố|TP[.]?|quận|huyện|thị xã)[ ]+([^,;()]+)/i);
      if (match) locality = match[1].replace(/\s+/g, " ").trim().toLowerCase();
      if (!locality) {
        let host = "";
        try { host = new URL(link).hostname; } catch (ignored) {}
        locality = "unresolved-source:" + (host || agencyClean || "unknown").toLowerCase();
      }
    }
    if (!issuer) issuer = agencyClean || String(title || "").trim().toLowerCase().slice(0, 90);
    return "number:" + n + "|issuer:" + issuer + "|locality:" + locality;
  }
  return "url:" + link;
}

function formatBatchRows_(sheet, startRow, numRows, batchIndex) {
  if (!sheet || numRows <= 0) return;
  const range = sheet.getRange(startRow, 1, numRows, 8);
  range.setFontFamily("Times New Roman").setFontSize(11).setFontWeight("normal")
    .setFontColor("#000000").setBackground("#ffffff").setVerticalAlignment("middle")
    .setWrap(true).setBorder(true, true, true, true, true, true, "#d9d9d9", SpreadsheetApp.BorderStyle.SOLID);

  const isEven = batchIndex % 2 === 0;
  const timeBg = isEven ? "#d9ead3" : "#cfe2f3";
  const agencyBg = isEven ? "#fce8e6" : "#ede7f6";
  const colA = sheet.getRange(startRow, 1, numRows, 1);
  colA.setBackground(timeBg).setHorizontalAlignment("center");
  if (numRows > 1) {
    colA.breakApart();
    colA.mergeVertically();
  }
  sheet.getRange(startRow, 2, numRows, 1).setHorizontalAlignment("left");
  sheet.getRange(startRow, 3, numRows, 1).setBackground(agencyBg).setFontColor("#1155cc").setHorizontalAlignment("center");
  sheet.getRange(startRow, 4, numRows, 1).setHorizontalAlignment("left");
  sheet.getRange(startRow, 5, numRows, 1).setHorizontalAlignment("center");
  sheet.getRange(startRow, 6, numRows, 1).setFontColor("#1155cc").setHorizontalAlignment("left").setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP);
  sheet.getRange(startRow, 7, numRows, 1).setHorizontalAlignment("left").setFontSize(9);
  sheet.getRange(startRow, 8, numRows, 1).setHorizontalAlignment("center").setFontSize(10);
}

function saveResults_(ss, data) {
  const resultSheet = ss.getSheetByName(CONFIG.SHEET_RESULTS);
  if (!resultSheet) throw new Error('Không tìm thấy sheet "' + CONFIG.SHEET_RESULTS + '".');
  if (!String(resultSheet.getRange(1, 8).getDisplayValue() || "").trim()) resultSheet.getRange(1, 8).setValue("Nhóm văn bản");
  const memory = ensureMemorySheet_(ss);
  const migrated = backfillLegacyMemory_(ss, memory);
  if (migrated) Logger.log("Đã khôi phục " + migrated + " bản ghi cũ trước khi chống trùng.");
  const now = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, "dd/MM/yyyy HH:mm:ss");
  const incoming = Array.isArray(data.new_docs) ? data.new_docs : [];
  const existing = new Set();
  const existingLinks = new Set();

  if (memory.getLastRow() >= 2) {
    const saved = memory.getRange(2, 1, memory.getLastRow() - 1, 7).getDisplayValues();
    saved.forEach(row => {
      if (row[0]) existingLinks.add(normalizeUrl_(row[0]));
      if (row[6]) existing.add(String(row[6]).trim());
    });
  }

  const resultLinks = new Set();
  if (resultSheet.getLastRow() >= 2) {
    resultSheet.getRange(2, 6, resultSheet.getLastRow() - 1, 1).getDisplayValues().forEach(row => {
      const link = normalizeUrl_(row[0]);
      if (link) resultLinks.add(link);
    });
  }

  // Repair-safe two-table write: if a previous request wrote memory but failed
  // before writing the visible result (or vice versa), a retry repairs only the
  // missing side instead of losing the document or creating a duplicate row.
  const fresh = [];
  incoming.forEach(doc => {
    const link = normalizeUrl_(doc.link || "");
    const identity = String(doc.identity || "").trim() || ("url:" + link);
    if (!link) return;
    const memoryHasLink = existingLinks.has(link);
    const identityExistsElsewhere = existing.has(identity) && !memoryHasLink;
    const addMemory = !memoryHasLink && !existing.has(identity);
    const addResult = !resultLinks.has(link) && !identityExistsElsewhere;
    if (!addMemory && !addResult) return;
    fresh.push({doc: doc, link: link, identity: identity, addMemory: addMemory, addResult: addResult});
    if (addMemory) {
      existingLinks.add(link);
      existing.add(identity);
    }
    if (addResult) resultLinks.add(link);
  });

  if (fresh.length) {
    const resultItems = fresh.filter(item => item.addResult);
    const memoryItems = fresh.filter(item => item.addMemory);
    if (memoryItems.length) {
      const memoryRows = memoryItems.map(item => {
        const d = item.doc;
        return [item.link, String(d.doc_number || ""), String(d.title || "").toLowerCase(),
          String(d.fingerprint || ""), String(d.doc_type || ""), now, item.identity];
      });
      const memStart = memory.getLastRow() + 1;
      memory.getRange(memStart, 1, memoryRows.length, 7).setValues(memoryRows);
    }
    if (resultItems.length) {
      const resultRows = resultItems.map(item => {
        const d = item.doc;
        return [now, String(d.doc_type || ""), cleanAgency_(d.agency), String(d.title || ""),
          String(d.doc_number || ""), String(d.link || ""), String(d.fingerprint || ""),
          String(d.category || "Văn bản khác")];
      });
      const previousBg = resultSheet.getLastRow() >= 2 ? resultSheet.getRange(2, 1).getBackground() : "#cfe2f3";
      const batchIndex = previousBg === "#d9ead3" ? 1 : 0;
      resultSheet.insertRowsAfter(1, resultRows.length);
      resultSheet.getRange(2, 1, resultRows.length, 8).setValues(resultRows);
      formatBatchRows_(resultSheet, 2, resultRows.length, batchIndex);
    }
  }

  const sourceStatus = Array.isArray(data.source_status) ? data.source_status : [];
  const sourceSheet = ss.getSheetByName(CONFIG.SHEET_SOURCES);
  if (sourceSheet && sourceStatus.length) {
    sourceStatus.forEach(st => {
      const row = Number(st.row);
      if (row >= 2) sourceSheet.getRange(row, 5, 1, 3)
        .setValues([[Number(st.count || 0), now, String(st.status || "")]]);
    });
  }

  const reviewDocs = Array.isArray(data.review_docs) ? data.review_docs : [];
  const reviewAdded = saveReviewDocs_(ss, reviewDocs, now);
  if (data.refresh_radar === true && fresh.length) updateMissingDocumentRadar_(ss);
  SpreadsheetApp.flush();
  return {status: "saved", added: fresh.filter(item => item.addResult).length,
    repaired_memory_only: fresh.filter(item => item.addMemory && !item.addResult).length,
    repaired_result_only: fresh.filter(item => item.addResult && !item.addMemory).length,
    skipped_duplicates: incoming.length - fresh.filter(item => item.addResult).length,
    sent_to_date_review: reviewAdded};
}


function saveReviewDocs_(ss, docs, now) {
  if (!docs || !docs.length) return 0;
  const name = "Cần xác minh ngày";
  let sheet = ss.getSheetByName(name);
  if (!sheet) sheet = ss.insertSheet(name);
  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, 7).setValues([[
      "Thời điểm phát hiện", "Nguồn", "Tiêu đề", "Số hiệu",
      "Liên kết", "Ngày đăng nguồn", "Lý do cần xác minh"
    ]]).setFontWeight("bold").setBackground("#fce8b2").setWrap(true);
  }
  const seen = new Set();
  if (sheet.getLastRow() >= 2) {
    sheet.getRange(2, 5, sheet.getLastRow() - 1, 1).getDisplayValues().forEach(r => {
      if (r[0]) seen.add(normalizeUrl_(r[0]));
    });
  }
  const rows = [];
  docs.forEach(d => {
    const link = normalizeUrl_(d.link || "");
    if (!link || seen.has(link)) return;
    seen.add(link);
    rows.push([now, String(d.agency || ""), String(d.title || ""),
      String(d.doc_number || ""), String(d.link || ""),
      String(d.published_date || ""), String(d.reason || "Không xác định được ngày.")]);
  });
  if (rows.length) {
    const start = sheet.getLastRow() + 1;
    sheet.getRange(start, 1, rows.length, 7).setValues(rows)
      .setWrap(true).setVerticalAlignment("middle");
    sheet.getRange(start, 5, rows.length, 1).setFontColor("#1155cc");
  }
  return rows.length;
}

function cleanAgency_(value) {
  return String(value || "").replace(/^Nguồn tự thêm\s*\((.*)\)$/i, "$1").trim();
}

function normalizeUrl_(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    parsed.hash = "";
    Array.from(parsed.searchParams.keys()).forEach(key => {
      const lower = key.toLowerCase();
      if (lower.indexOf("utm_") === 0 || ["fbclid", "gclid", "ref", "source"].indexOf(lower) !== -1) {
        parsed.searchParams.delete(key);
      }
    });
    const path = parsed.pathname.replace(/\/+$/, "") || "/";
    return parsed.protocol.toLowerCase() + "//" + parsed.host.toLowerCase() +
      path + (parsed.searchParams.toString() ? "?" + parsed.searchParams.toString() : "");
  } catch (ignored) {
    return raw.replace(/#.*$/, "").replace(/\/$/, "");
  }
}

function updateMissingDocumentRadar_(ss) {
  const memory = ss.getSheetByName(CONFIG.SHEET_MEMORY);
  if (!memory || memory.getLastRow() < 2) return;
  const values = memory.getRange(2, 1, memory.getLastRow() - 1, 7).getDisplayValues();
  const yearNow = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, "yyyy");
  const groups = {};

  values.forEach(row => {
    const number = String(row[1] || "").trim().toUpperCase();
    const type = String(row[4] || "").trim();
    const title = String(row[2] || "").toUpperCase();
    if (!number || number === "ĐANG CẬP NHẬT") return;
    if (number.indexOf("TT-BCA") !== -1 || number.indexOf("TT-BQP") !== -1) return;

    let match = number.match(/^(\d+)\/(\d{4})\/(NĐ-CP|TT-[A-ZĐƯƠĂÂÊÔ0-9-]+)$/);
    if (!match && (type === "Nghị định" || title.indexOf("NGHỊ ĐỊNH") !== -1)) {
      match = number.match(/^(\d+)\/(\d{4})$/);
      if (match) match[3] = "NĐ-CP";
    }
    if (!match || match[2] !== yearNow) return;
    const symbol = match[3];
    const num = Number(match[1]);
    if (!groups[symbol]) groups[symbol] = new Set();
    groups[symbol].add(num);
  });

  const output = [];
  Object.keys(groups).forEach(symbol => {
    const nums = Array.from(groups[symbol]).sort((a, b) => a - b);
    if (!nums.length) return;
    const maxNum = nums[nums.length - 1];
    const start = Math.max(1, maxNum - 10);
    const recent = nums.filter(n => n >= start);
    const actualStart = recent.length >= 2 ? recent[0] : start;
    const missing = [];
    for (let n = actualStart; n < maxNum; n++) if (!groups[symbol].has(n)) missing.push(n);
    const label = symbol === "NĐ-CP" ? "Nghị định Chính phủ (NĐ-CP)" : "Thông tư " + symbol.replace("TT-", "") + " (" + symbol + ")";
    output.push([label, maxNum, recent.join(", "), missing.length ? missing.join(", ") : "Đủ liền mạch",
      Utilities.formatDate(new Date(), CONFIG.TIMEZONE, "dd/MM/yyyy HH:mm")]);
  });

  let warn = ss.getSheetByName(CONFIG.SHEET_RADAR);
  if (!warn) warn = ss.insertSheet(CONFIG.SHEET_RADAR);
  warn.clear();
  warn.getRange(1, 1, 1, 5).setValues([["Cơ quan ban hành", "Số VB lớn nhất đã quét (" + yearNow + ")", "Các số đã có gần đây", "Các số đang bị khuyết (Trong 10 số mới nhất)", "Cập nhật lúc"]])
    .setFontWeight("bold").setBackground("#405f90").setFontColor("#ffffff")
    .setHorizontalAlignment("center").setVerticalAlignment("middle").setWrap(true);
  if (output.length) {
    output.sort((a, b) => a[0].localeCompare(b[0]));
    warn.getRange(2, 3, output.length, 2).setNumberFormat("@");
    warn.getRange(2, 1, output.length, 5).setValues(output);
    warn.getRange(2, 1, output.length, 5).setVerticalAlignment("middle")
      .setBorder(true, true, true, true, true, true, "#c4c7d0", SpreadsheetApp.BorderStyle.SOLID);
    warn.getRange(2, 2, output.length, 1).setHorizontalAlignment("center").setFontWeight("bold").setFontColor("#1155cc");
    warn.getRange(2, 4, output.length, 1).setFontWeight("bold").setFontColor("#d93025");
    warn.getRange(2, 5, output.length, 1).setHorizontalAlignment("center");
  }
}

/**
 * Chạy thủ công một lần nếu muốn tắt hẳn bộ quét nhanh cũ.
 * GitHub Actions quét văn bản; Apps Script chỉ làm API và thanh tra lịch chạy.
 */
function tatBoQuetCu() {
  const handlers = ["quetNhanhTrungUongTuSheet", "caiDatHenGio15Phut"];
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (handlers.indexOf(trigger.getHandlerFunction()) !== -1) ScriptApp.deleteTrigger(trigger);
  });
  Logger.log("Đã xóa trigger quét nhanh cũ. GitHub Actions là bộ quét duy nhất.");
}


/* ============================================================
 * THANH TRA DOC LAP - GITHUB ACTIONS FAILSAFE
 * Chay bang time trigger cua Google Apps Script, doc lap voi
 * lich schedule cua GitHub Actions.
 * Script Properties can co GITHUB_PAT (fine-grained):
 * Actions: Read and write; repository access: this repository.
 * ============================================================ */

const INSPECTOR_CONFIG = {
  REPOSITORY: "Drak-318/Tr-m-tin-t-c",
  WORKFLOW: "auto_scan.yml",
  BRANCH: "main",
  AUDIT_SHEET: "Thanh tra he thong",
  PRIORITY_STALE_MINUTES: 12,
  FULL_STALE_MINUTES: 42,
  POST_COMPLETION_COOLDOWN_MINUTES: 5,
  DISPATCH_ACK_TIMEOUT_MINUTES: 15,
  RUNS_TO_INSPECT: 18,
  AUDIT_MAX_ROWS: 5000
};

/**
 * Chay mot lan de cai dat thanh tra moi 5 phut.
 * Ham nay khong xoa trigger quet/trigger khac.
 */
function caiDatThanhTraDocLap() {
  const handler = "thanhTraTramTinTuc";
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === handler) ScriptApp.deleteTrigger(trigger);
  });
  ScriptApp.newTrigger(handler).timeBased().everyMinutes(5).create();
  ghiNhatKyThanhTra_("SETUP", "", "", "INSTALLED", "Da cai trigger thanh tra doc lap moi 5 phut.");
  Logger.log("Da cai dat Thanh tra Tram Tin Tuc moi 5 phut.");
}

/** Kiem tra ket noi/token va tinh trang workflow ngay lap tuc. */
function kiemTraThanhTraThuCong() {
  return thanhTraTramTinTuc();
}

/**
 * Vong thanh tra chinh. Khong gui lenh neu da co job queued/in_progress.
 * Moi dispatch chi duoc gui lai khi het han xac nhan 15 phut; moi job moi
 * phai hoan tat va qua cooldown 5 phut truoc khi duoc xem xet chay tiep.
 */
function thanhTraTramTinTuc() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    Logger.log("Bo qua: mot vong thanh tra khac dang chay.");
    return {status: "busy"};
  }

  try {
    const props = PropertiesService.getScriptProperties();
    const token = props.getProperty("GITHUB_PAT");
    if (!token) throw new Error("Thieu Script Property GITHUB_PAT. Hay them Fine-grained PAT trong Apps Script > Project Settings > Script properties.");

    const snapshot = docTrangThaiGitHub_(token);
    const now = Date.now();
    const priority = phucHoiMocThoiGianJob_(
      tinhTuoiJob_(snapshot.jobs, "priority-scan", now), props, "PRIORITY", now
    );
    const full = phucHoiMocThoiGianJob_(
      tinhTuoiJob_(snapshot.jobs, "scan", now), props, "FULL", now
    );

    const priorityActive = priority.active;
    const fullActive = full.active;
    const priorityAge = priority.ageMinutes;
    const fullAge = full.ageMinutes;

    let action = "HEALTHY";
    let reason = "Cac luot quet van trong nguong cho phep.";
    let dispatchResult = "";

    // Full scan bao gom priority scan, nen neu ca hai deu qua han
    // thi chi dispatch full de tranh tao hai luot chay trung.
    const fullStale = !fullActive && fullAge > INSPECTOR_CONFIG.FULL_STALE_MINUTES;
    const priorityStale = !priorityActive && priorityAge > INSPECTOR_CONFIG.PRIORITY_STALE_MINUTES;

    if (priorityActive || fullActive) {
      action = "SCAN_ACTIVE";
      reason = "Co job dang queued/in_progress; chi theo doi, khong gui lenh moi.";
    } else if (fullStale) {
      const completionCooldown = conSauHoanTat_(full.lastCompletedAt, now);
      const awaitingGitHub = conTrongCooldown_(props, "LAST_FULL_DISPATCH_AT", now,
        INSPECTOR_CONFIG.DISPATCH_ACK_TIMEOUT_MINUTES);
      if (completionCooldown) {
        action = "WAIT_FULL_COOLDOWN";
        reason = "Luot quet toan bo vua ket thuc; cho du 5 phut tinh tu thoi diem hoan tat.";
      } else if (awaitingGitHub) {
        action = "WAIT_FULL_ACK";
        reason = "Da gui yeu cau; cho GitHub tao job, chua gui lai de tranh trung lenh.";
      } else {
        dispatchResult = guiLenhQuetGitHub_(token, "full");
        props.setProperty("LAST_FULL_DISPATCH_AT", String(now));
        action = "DISPATCH_FULL";
        reason = "Khong co luot quet toan bo thanh cong trong " + Math.round(fullAge) +
          " phut; khong con job hoat dong va da qua thoi gian cho an toan.";
      }
    } else if (priorityStale) {
      const completionCooldown = conSauHoanTat_(priority.lastCompletedAt, now);
      const awaitingGitHub = conTrongCooldown_(props, "LAST_PRIORITY_DISPATCH_AT", now,
        INSPECTOR_CONFIG.DISPATCH_ACK_TIMEOUT_MINUTES);
      if (completionCooldown) {
        action = "WAIT_PRIORITY_COOLDOWN";
        reason = "Luot quet uu tien vua ket thuc; cho du 5 phut tinh tu thoi diem hoan tat.";
      } else if (awaitingGitHub) {
        action = "WAIT_PRIORITY_ACK";
        reason = "Da gui yeu cau uu tien; cho GitHub tao job, chua gui lai.";
      } else {
        dispatchResult = guiLenhQuetGitHub_(token, "priority");
        props.setProperty("LAST_PRIORITY_DISPATCH_AT", String(now));
        action = "DISPATCH_PRIORITY";
        reason = "Khong co luot quet uu tien thanh cong trong " + Math.round(priorityAge) +
          " phut; khong con job hoat dong va da qua thoi gian cho an toan.";
      }
    } else {
      reason = "Priority: " + dinhDangTuoi_(priorityAge) + "; full: " + dinhDangTuoi_(fullAge) + ".";
    }

    const record = {
      checked_at: new Date(now).toISOString(),
      action: action,
      reason: reason,
      priority_age_minutes: Number.isFinite(priorityAge) ? Math.round(priorityAge) : null,
      full_age_minutes: Number.isFinite(fullAge) ? Math.round(fullAge) : null,
      priority_active: priorityActive,
      full_active: fullActive,
      dispatch_result: dispatchResult,
      latest_priority_success: priority.lastSuccess || null,
      latest_full_success: full.lastSuccess || null
    };
    props.setProperty("INSPECTOR_LAST_HEALTH", JSON.stringify(record));
    ghiNhatKyThanhTra_(action, dinhDangTuoi_(priorityAge), dinhDangTuoi_(fullAge), dispatchResult, reason);
    Logger.log(JSON.stringify(record));
    return record;
  } catch (error) {
    const message = String(error && error.stack ? error.stack : error);
    PropertiesService.getScriptProperties().setProperty("INSPECTOR_LAST_ERROR", message.slice(0, 4000));
    ghiNhatKyThanhTra_("ERROR", "", "", "", message.slice(0, 1500));
    throw error;
  } finally {
    lock.releaseLock();
  }
}

function docTrangThaiGitHub_(token) {
  const base = "https://api.github.com/repos/" + INSPECTOR_CONFIG.REPOSITORY;
  const headers = {
    "Authorization": "Bearer " + token,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
  };
  const runsUrl = base + "/actions/workflows/" + INSPECTOR_CONFIG.WORKFLOW +
    "/runs?branch=" + encodeURIComponent(INSPECTOR_CONFIG.BRANCH) +
    "&per_page=" + INSPECTOR_CONFIG.RUNS_TO_INSPECT;
  const runsResponse = UrlFetchApp.fetch(runsUrl, {method: "get", headers: headers, muteHttpExceptions: true});
  kiemTraPhanHoiGitHub_(runsResponse, "Doc workflow runs");
  const runs = (JSON.parse(runsResponse.getContentText()).workflow_runs || []).slice(0, INSPECTOR_CONFIG.RUNS_TO_INSPECT);
  if (!runs.length) return {jobs: []};

  const requests = runs.map(function(run) {
    return {
      url: base + "/actions/runs/" + run.id + "/jobs?per_page=30",
      method: "get",
      headers: headers,
      muteHttpExceptions: true
    };
  });
  const responses = UrlFetchApp.fetchAll(requests);
  const jobs = [];
  responses.forEach(function(response, index) {
    kiemTraPhanHoiGitHub_(response, "Doc jobs cua run " + runs[index].run_number);
    const data = JSON.parse(response.getContentText());
    (data.jobs || []).forEach(function(job) {
      jobs.push({
        name: job.name,
        status: job.status,
        conclusion: job.conclusion,
        started_at: job.started_at,
        completed_at: job.completed_at,
        run_id: runs[index].id,
        run_number: runs[index].run_number,
        event: runs[index].event
      });
    });
  });
  return {jobs: jobs};
}

function tinhTuoiJob_(jobs, jobName, now) {
  const matching = jobs.filter(function(job) { return job.name === jobName; });
  const active = matching.some(function(job) {
    return job.status === "queued" || job.status === "in_progress" || job.status === "pending";
  });
  const completed = matching.filter(function(job) {
    return job.completed_at && job.conclusion;
  }).sort(function(a, b) {
    return new Date(b.completed_at).getTime() - new Date(a.completed_at).getTime();
  });
  const successes = completed.filter(function(job) { return job.conclusion === "success"; });
  const lastSuccess = successes.length ? successes[0].completed_at : null;
  const lastCompletedAt = completed.length ? completed[0].completed_at : null;
  return {
    active: active,
    ageMinutes: lastSuccess ? Math.max(0, (now - new Date(lastSuccess).getTime()) / 60000) : Infinity,
    lastSuccess: lastSuccess,
    lastCompletedAt: lastCompletedAt
  };
}

function phucHoiMocThoiGianJob_(state, props, prefix, now) {
  // Keep the last observed timestamps in Script Properties. The inspector
  // reads only the latest N workflow runs; frequent priority/push runs can
  // otherwise push an older full-scan completion out of that window.
  const successKey = "INSPECTOR_" + prefix + "_LAST_SUCCESS_AT";
  const completedKey = "INSPECTOR_" + prefix + "_LAST_COMPLETED_AT";
  const storedSuccess = props.getProperty(successKey);
  const storedCompleted = props.getProperty(completedKey);
  const newest = function(a, b) {
    if (!a) return b || null;
    if (!b) return a;
    return new Date(a).getTime() >= new Date(b).getTime() ? a : b;
  };
  state.lastSuccess = newest(state.lastSuccess, storedSuccess);
  state.lastCompletedAt = newest(state.lastCompletedAt, storedCompleted);
  if (state.lastSuccess) props.setProperty(successKey, state.lastSuccess);
  if (state.lastCompletedAt) props.setProperty(completedKey, state.lastCompletedAt);

  // A completed job newer than the last dispatch is the acknowledgement.
  // Clear the pending-dispatch marker so a finished run is not mistaken for
  // an unacknowledged request when the next cooldown expires.
  const dispatchKey = "LAST_" + prefix + "_DISPATCH_AT";
  const dispatchAt = Number(props.getProperty(dispatchKey) || 0);
  const completedMs = state.lastCompletedAt ? new Date(state.lastCompletedAt).getTime() : 0;
  if (dispatchAt > 0 && completedMs >= dispatchAt) {
    props.deleteProperty(dispatchKey);
  }

  state.ageMinutes = state.lastSuccess
    ? Math.max(0, (now - new Date(state.lastSuccess).getTime()) / 60000)
    : Infinity;
  return state;
}

function guiLenhQuetGitHub_(token, profile) {
  const url = "https://api.github.com/repos/" + INSPECTOR_CONFIG.REPOSITORY +
    "/actions/workflows/" + INSPECTOR_CONFIG.WORKFLOW + "/dispatches";
  const response = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    headers: {
      "Authorization": "Bearer " + token,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"
    },
    payload: JSON.stringify({ref: INSPECTOR_CONFIG.BRANCH, inputs: {profile: profile}}),
    muteHttpExceptions: true
  });
  const code = response.getResponseCode();
  if (code !== 204) {
    throw new Error("GitHub dispatch " + profile + " that bai, HTTP " + code + ": " + response.getContentText().slice(0, 1200));
  }
  return "GitHub da tiep nhan lenh " + profile + " (HTTP 204); thanh tra se xac minh job o vong tiep theo.";
}

function kiemTraPhanHoiGitHub_(response, operation) {
  const code = response.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error(operation + " that bai, HTTP " + code + ": " + response.getContentText().slice(0, 1200));
  }
}

function conTrongCooldown_(props, key, now, minutes) {
  const last = Number(props.getProperty(key) || 0);
  const windowMinutes = Number(minutes || INSPECTOR_CONFIG.DISPATCH_ACK_TIMEOUT_MINUTES);
  return last > 0 && (now - last) < windowMinutes * 60000;
}

function conSauHoanTat_(completedAt, now) {
  if (!completedAt) return false;
  const completedMs = new Date(completedAt).getTime();
  if (!Number.isFinite(completedMs)) return false;
  return (now - completedMs) < INSPECTOR_CONFIG.POST_COMPLETION_COOLDOWN_MINUTES * 60000;
}

function dinhDangTuoi_(age) {
  return Number.isFinite(age) ? Math.round(age) + " phut" : "chua co luot thanh cong";
}

function ghiNhatKyThanhTra_(action, priorityAge, fullAge, dispatchResult, reason) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (!ss) return;
    let sheet = ss.getSheetByName(INSPECTOR_CONFIG.AUDIT_SHEET);
    if (!sheet) {
      sheet = ss.insertSheet(INSPECTOR_CONFIG.AUDIT_SHEET);
      sheet.appendRow(["Thoi diem", "Hanh dong", "Tuoi quet uu tien", "Tuoi quet toan bo", "Ket qua lenh", "Ly do"]);
      sheet.setFrozenRows(1);
    }
    sheet.appendRow([
      Utilities.formatDate(new Date(), CONFIG.TIMEZONE, "dd/MM/yyyy HH:mm:ss"),
      String(action || ""),
      String(priorityAge || ""),
      String(fullAge || ""),
      String(dispatchResult || ""),
      String(reason || "").slice(0, 1500)
    ]);
    const lastRow = sheet.getLastRow();
    if (lastRow > INSPECTOR_CONFIG.AUDIT_MAX_ROWS + 1) {
      sheet.deleteRows(2, lastRow - INSPECTOR_CONFIG.AUDIT_MAX_ROWS - 1);
    }
  } catch (error) {
    Logger.log("Khong ghi duoc nhat ky thanh tra: " + error);
  }
}
