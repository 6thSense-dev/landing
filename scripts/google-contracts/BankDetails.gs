/* Append to the live contractor Apps Script project without replacing its
 * existing contract source. Deploy as an owner-executed web app. Every request
 * is HMAC authenticated; no bank details or secret values are logged.
 */
const BANK_SHEET_ID = '1ZJZ_H4ZIWRl_c6QngmsDTfcAhQnbN6vrLbUnpPd_CPg';
const BANK_TAB = 'Bank details';
const BANK_HEADERS = ['Contributor ID', 'Contributor name', 'Account holder', 'Bank', 'Account number',
  'Submitted at (UTC)', 'Submission ID', 'Status', 'Notice version', 'Notice SHA-256', 'Consent receipt'];

function bankSafeCell(value) {
  const text = String(value === undefined || value === null ? '' : value);
  return /^[=+\-@\t\r]/.test(text) ? "'" + text : text;
}
function bankPrivateWorkbook() {
  if (DriveApp.getFileById(BANK_SHEET_ID).getSharingAccess() !== DriveApp.Access.PRIVATE)
    throw Error('payment_sheet_access');
  return SpreadsheetApp.openById(BANK_SHEET_ID);
}
function setupBankDetails() {
  const book = bankPrivateWorkbook();
  let tab = book.getSheetByName(BANK_TAB);
  if (!tab) {
    tab = book.insertSheet(BANK_TAB);
    tab.getRange(1, 1, 1, BANK_HEADERS.length).setValues([BANK_HEADERS]);
    tab.setFrozenRows(1);
    tab.getRange(1, 1, 1, BANK_HEADERS.length).setFontWeight('bold').setBackground('#262312').setFontColor('#ffffff');
    tab.getRange('A:K').setNumberFormat('@');
    tab.setColumnWidths(1, 11, 170);
    tab.setColumnWidth(5, 220);
    tab.setColumnWidth(11, 260);
  }
  bankTab(book);
  return {ready: true, spreadsheetId: BANK_SHEET_ID, sheetId: tab.getSheetId()};
}
function bankTab(book) {
  const tab = book.getSheetByName(BANK_TAB);
  if (!tab || JSON.stringify(tab.getRange(1, 1, 1, BANK_HEADERS.length).getValues()[0]) !== JSON.stringify(BANK_HEADERS))
    throw Error('payment_sheet_columns');
  return tab;
}
function bankSummary(row) {
  return {contributorId: Number(row[0]), accountHolderName: String(row[2]), bankLabel: String(row[3]),
    maskedAccount: '•••• ' + String(row[4]).slice(-4), submittedAt: String(row[5]),
    submissionId: String(row[6]), status: 'sheet_saved'};
}
function bankAuthorized(envelope) {
  const secret = PropertiesService.getScriptProperties().getProperty('BANK_DETAILS_SECRET');
  if (!secret || secret.length < 32 || !envelope || typeof envelope.payload !== 'string'
      || envelope.payload.length > 16000 || !/^[0-9]{10}$/.test(String(envelope.timestamp))
      || Math.abs(Date.now() / 1000 - Number(envelope.timestamp)) > 300
      || !/^[a-f0-9]{64}$/.test(String(envelope.signature))) return false;
  const actual = Utilities.computeHmacSha256Signature(envelope.timestamp + '.' + envelope.payload,
    secret, Utilities.Charset.UTF_8).map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
  let mismatch = 0;
  for (let i = 0; i < actual.length; i++) mismatch |= actual.charCodeAt(i) ^ envelope.signature.charCodeAt(i);
  return mismatch === 0;
}
function bankRequest(envelope) {
  if (!bankAuthorized(envelope)) return {ok: false};
  const data = JSON.parse(envelope.payload);
  const book = bankPrivateWorkbook(), tab = bankTab(book);
  if (data.action === 'health') return {ok: true, ready: true, sheetId: tab.getSheetId()};
  if (!Number.isSafeInteger(data.contributorId) || data.contributorId <= 0
      || !['lookup', 'submit', 'delete'].includes(data.action)) return {ok: false};
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(3000)) return {ok: false};
  try {
    // One row per authenticated contributor. A delayed request or a retry with
    // a new browser operation ID returns the existing receipt, never a second
    // row or an overwrite of account instructions.
    const properties = PropertiesService.getScriptProperties();
    const tombstone = 'BANK_DELETED_' + data.contributorId;
    const rows = tab.getDataRange().getDisplayValues();
    if (data.action === 'delete') {
      // A timed-out submission may still be executing. Record the tombstone
      // before removing rows, under the same lock used by every submission.
      properties.setProperty(tombstone, new Date().toISOString());
      for (let i = rows.length - 1; i >= 1; i--) {
        if (String(rows[i][0]) === String(data.contributorId)) tab.deleteRow(i + 1);
      }
      SpreadsheetApp.flush();
      if (tab.getDataRange().getDisplayValues().slice(1).some(row => String(row[0]) === String(data.contributorId)))
        throw Error('payment_sheet_delete_incomplete');
      return {ok: true, deleted: true, contributorId: data.contributorId};
    }
    if (properties.getProperty(tombstone))
      return data.action === 'lookup' ? {ok: true, bank: null} : {ok: false};
    const matches = rows.slice(1).filter(row => String(row[0]) === String(data.contributorId));
    if (matches.length > 1) throw Error('payment_sheet_duplicate');
    if (matches.length) return {ok: true, bank: bankSummary(matches[0])};
    if (data.action === 'lookup') return {ok: true, bank: null};
    const values = data.values || {}, consent = data.consent || {};
    if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(String(data.operationId))
        || typeof data.contributorName !== 'string' || data.contributorName.length > 200
        || !/^[0-9]{6,34}$/.test(String(values.accountNumber))
        || !['accountHolderName', 'bankName'].every(key => typeof values[key] === 'string'
          && values[key].trim() && values[key].length <= 100 && !/[\x00-\x1f]/.test(values[key]))
        || !consent.notice || !/^[a-f0-9]{64}$/.test(String(consent.notice.sha256))
        || !['collects_details', 'international_transfer']
          .every(key => consent.choices && consent.choices[key] === true)) return {ok: false};
    const row = [String(data.contributorId), bankSafeCell(data.contributorName),
      bankSafeCell(values.accountHolderName), bankSafeCell(values.bankName), values.accountNumber,
      new Date().toISOString(), data.operationId, 'Received — staff review',
      bankSafeCell(consent.notice.version), consent.notice.sha256, bankSafeCell(JSON.stringify(consent))];
    const target = tab.getRange(tab.getLastRow() + 1, 1, 1, BANK_HEADERS.length);
    target.setNumberFormat('@').setValues([row]);
    SpreadsheetApp.flush();
    // Receipt comes from read-back, not from the submitted payload.
    return {ok: true, bank: bankSummary(target.getDisplayValues()[0])};
  } finally { lock.releaseLock(); }
}
function doPost(event) {
  let result;
  try {
    if (!event || !event.postData || event.postData.contents.length > 24000) throw Error();
    result = bankRequest(JSON.parse(event.postData.contents));
  } catch (_) { result = {ok: false}; }
  return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);
}
