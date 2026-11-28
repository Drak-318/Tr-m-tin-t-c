/**
 * TRẠM VĂN BẢN PHÁP LUẬT - CỔNG NHẬN KẾT QUẢ V15.0
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

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return jsonOutput_({status: "ok", service: "Tram Tin Tuc API", version: "15.0"});
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonOutput_({status: "error", message: "Thiếu nội dung yêu cầu."});
    }

    const data = JSON.parse(e.postData.contents);
    const expectedToken = PropertiesService.getScriptProperties().getProperty("SHEETS_API_TOKEN");
    if (expectedToken && String(data.token || "") !== expectedToken) {
      return jsonOutput_({status: "error", message: "API token không hợp lệ."});
    }

    // GitHub Actions owns scheduling, collection, classification and memory.
    // This API only accepts result/source-status writes and returns source
    // registry data when explicitly requested by the GitHub scanner.
    xoaTriggerDieuPhoiCu_();

    if (!lock.tryLock(25000)) {
      return jsonOutput_({status: "error", message: "Hệ thống đang xử lý lượt đồng bộ khác. Hãy thử lại."});
    }

    const ss = SpreadsheetApp.getActiveSpreadsheet();
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
 * Remove legacy Apps Script triggers left by previous deployments.
 * This is a one-time cleanup only; Apps Script never schedules or dispatches scans.
 */
function xoaTriggerDieuPhoiCu_() {
  const props = PropertiesService.getScriptProperties();
  if (props.getProperty("GITHUB_ONLY_TRIGGERS_CLEANED") === "1") return;
  const obsoleteHandlers = [
    "thanhTraTramTinTuc",
    "kiemTraThanhTraThuCong",
    "caiDatThanhTraDocLap",
    "quetNhanhTrungUongTuSheet",
    "caiDatHenGio15Phut"
  ];
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (obsoleteHandlers.indexOf(trigger.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  props.setProperty("GITHUB_ONLY_TRIGGERS_CLEANED", "1");
}

/**
 * Compatibility cleanup entry point. Safe to run manually if desired.
 * All scheduling and scan control now live in GitHub Actions.
 */
function tatBoQuetCu() {
  PropertiesService.getScriptProperties().deleteProperty("GITHUB_ONLY_TRIGGERS_CLEANED");
  xoaTriggerDieuPhoiCu_();
  Logger.log("Da xoa trigger cu. GitHub Actions la bo dieu phoi duy nhat.");
}
