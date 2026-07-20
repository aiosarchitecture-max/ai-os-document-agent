/** AI_OS Google Workspace bridge. Configure AI_OS_BRIDGE_SECRET in Script Properties. */
const ALLOWED_ACTIONS = Object.freeze([
  'PING', 'READ_DOC', 'CREATE_DOC', 'APPEND_DOC', 'APPEND_SHEET_ROW',
  'RENAME_FILE', 'MOVE_FILE', 'TRASH_FILE'
]);

function doGet() {
  return json_({status: 'success', service: 'AI_OS Workspace bridge', version: '3.0.0'});
}

function doPost(e) {
  const requestId = Utilities.getUuid();
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    authenticate_(body.secret);
    if (ALLOWED_ACTIONS.indexOf(body.action) === -1) throw new Error('Unsupported action');
    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      const data = dispatch_(body.action, body.payload || {});
      return json_({status: 'success', requestId: requestId, data: data});
    } finally {
      lock.releaseLock();
    }
  } catch (error) {
    console.error(JSON.stringify({requestId: requestId, error: String(error), stack: error.stack || ''}));
    return json_({status: 'error', requestId: requestId, error: String(error.message || error)});
  }
}

function authenticate_(supplied) {
  const expected = PropertiesService.getScriptProperties().getProperty('AI_OS_BRIDGE_SECRET');
  if (!expected) throw new Error('Bridge secret is not configured');
  if (!supplied || !constantTimeEqual_(String(supplied), String(expected))) throw new Error('Unauthorized');
}

function constantTimeEqual_(a, b) {
  if (a.length !== b.length) return false;
  let mismatch = 0;
  for (let i = 0; i < a.length; i++) mismatch |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return mismatch === 0;
}

function dispatch_(action, payload) {
  switch (action) {
    case 'PING': return {pong: true};
    case 'READ_DOC': return readDoc_(required_(payload, 'documentId'));
    case 'CREATE_DOC': return createDoc_(payload);
    case 'APPEND_DOC': return appendDoc_(payload);
    case 'APPEND_SHEET_ROW': return appendSheetRow_(payload);
    case 'RENAME_FILE': return renameFile_(payload);
    case 'MOVE_FILE': return moveFile_(payload);
    case 'TRASH_FILE': return trashFile_(payload);
    default: throw new Error('Unsupported action');
  }
}

function readDoc_(documentId) {
  const doc = DocumentApp.openById(documentId);
  return {documentId: documentId, name: doc.getName(), text: doc.getBody().getText()};
}

function createDoc_(payload) {
  const title = required_(payload, 'title');
  const doc = DocumentApp.create(title);
  if (payload.content) doc.getBody().setText(String(payload.content));
  doc.saveAndClose();
  if (payload.folderId) moveFile_({fileId: doc.getId(), folderId: payload.folderId});
  return {documentId: doc.getId(), url: doc.getUrl(), name: title};
}

function appendDoc_(payload) {
  const documentId = required_(payload, 'documentId');
  const doc = DocumentApp.openById(documentId);
  doc.getBody().appendParagraph(String(required_(payload, 'text')));
  doc.saveAndClose();
  return {documentId: documentId, updated: true};
}

function appendSheetRow_(payload) {
  const spreadsheetId = required_(payload, 'spreadsheetId');
  const sheet = SpreadsheetApp.openById(spreadsheetId).getSheetByName(required_(payload, 'sheetName'));
  if (!sheet) throw new Error('Sheet not found');
  if (!Array.isArray(payload.values)) throw new Error('values must be an array');
  sheet.appendRow(payload.values.map(sanitizeCell_));
  SpreadsheetApp.flush();
  return {spreadsheetId: spreadsheetId, sheetName: sheet.getName(), row: sheet.getLastRow()};
}

function sanitizeCell_(value) {
  if (typeof value === 'string' && /^[=+\-@]/.test(value)) return "'" + value;
  return value;
}

function renameFile_(payload) {
  const file = DriveApp.getFileById(required_(payload, 'fileId'));
  file.setName(required_(payload, 'name'));
  return {fileId: file.getId(), name: file.getName()};
}

function moveFile_(payload) {
  const file = DriveApp.getFileById(required_(payload, 'fileId'));
  const destination = DriveApp.getFolderById(required_(payload, 'folderId'));
  file.moveTo(destination); // Atomic parent replacement; avoids remove-all-parents data loss.
  return {fileId: file.getId(), folderId: destination.getId()};
}

function trashFile_(payload) {
  const file = DriveApp.getFileById(required_(payload, 'fileId'));
  file.setTrashed(true);
  return {fileId: file.getId(), trashed: true};
}

function required_(object, key) {
  const value = object[key];
  if (value === undefined || value === null || value === '') throw new Error('Missing field: ' + key);
  return value;
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}
