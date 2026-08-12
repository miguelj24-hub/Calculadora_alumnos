const SPREADSHEET_ID = "PEGA_EL_ID_DE_LA_HOJA";
const SECRET_TOKEN = "INVENTA_UN_TOKEN_LARGO";
const WORKSHEET_NAME = "Comparativas";

function doGet() {
  return jsonResponse({ ok: true, message: "Webhook activo" });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    const data = JSON.parse(e.postData.contents || "{}");
    if (!data.token || data.token !== SECRET_TOKEN) {
      return jsonResponse({ ok: false, error: "Token inválido" });
    }
    if (!Array.isArray(data.headers) || !Array.isArray(data.rows) || !data.rows.length) {
      return jsonResponse({ ok: false, error: "No se recibieron filas válidas" });
    }

    lock.waitLock(20000);
    const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
    let sheet = spreadsheet.getSheetByName(WORKSHEET_NAME);
    if (!sheet) sheet = spreadsheet.insertSheet(WORKSHEET_NAME);

    if (sheet.getLastRow() === 0) {
      sheet.getRange(1, 1, 1, data.headers.length).setValues([sanitizeRow(data.headers)]);
      sheet.getRange(1, 1, 1, data.headers.length).setFontWeight("bold");
      sheet.setFrozenRows(1);
    }

    const rows = data.rows.map(sanitizeRow);
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, data.headers.length).setValues(rows);
    return jsonResponse({ ok: true, saved_rows: rows.length, sheet_url: spreadsheet.getUrl() });
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error.message || error) });
  } finally {
    try { lock.releaseLock(); } catch (_) {}
  }
}

function sanitizeRow(row) {
  return row.map(value => {
    if (typeof value === "string" && /^[=+\-@]/.test(value)) return "'" + value;
    return value;
  });
}

function jsonResponse(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
