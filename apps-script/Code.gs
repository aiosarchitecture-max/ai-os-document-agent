/** AI_OS Google Workspace bridge v3.1. Configure secrets in Script Properties. */
const BRIDGE_VERSION = '3.2.1';
const ALLOWED_ACTIONS = Object.freeze([
  'PING', 'READ_DOC', 'READ_SHEET_ROWS', 'CREATE_DOC', 'APPEND_DOC', 'APPEND_SHEET_ROW',
  'RENAME_FILE', 'MOVE_FILE', 'TRASH_FILE'
]);
const WRITE_ACTIONS = Object.freeze([
  'CREATE_DOC', 'APPEND_DOC', 'APPEND_SHEET_ROW', 'RENAME_FILE', 'MOVE_FILE', 'TRASH_FILE'
]);
const MAX_TEXT_LENGTH = 100000;
const MAX_READ_LENGTH = 500000;
const MAX_SHEET_COLUMNS = 200;

function doGet() {
  return json_({status: 'success', service: 'AI_OS Workspace bridge', version: BRIDGE_VERSION});
}

function doPost(e) {
  const fallbackRequestId = Utilities.getUuid();
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    authenticate_(body.secret);
    validateAction_(body.action);
    const requestId = String(body.requestId || fallbackRequestId);
    if (WRITE_ACTIONS.indexOf(body.action) !== -1 && !body.requestId) {
      throw new Error('requestId is required for write actions');
    }

    const lock = LockService.getScriptLock();
    lock.waitLock(30000);
    try {
      const cache = CacheService.getScriptCache();
      const cacheKey = 'cmd_' + sha256_(requestId).slice(0, 48);
      if (WRITE_ACTIONS.indexOf(body.action) !== -1 && cache.get(cacheKey)) {
        return json_({status: 'success', requestId: requestId, duplicate: true});
      }
      const data = dispatch_(body.action, body.payload || {});
      if (WRITE_ACTIONS.indexOf(body.action) !== -1) cache.put(cacheKey, '1', 21600);
      return json_({status: 'success', requestId: requestId, duplicate: false, data: data});
    } finally {
      lock.releaseLock();
    }
  } catch (error) {
    console.error(JSON.stringify({requestId: fallbackRequestId, error: String(error), stack: error.stack || ''}));
    return json_({status: 'error', requestId: fallbackRequestId, error: String(error.message || error)});
  }
}

function authenticate_(supplied) {
  const expected = PropertiesService.getScriptProperties().getProperty('AI_OS_BRIDGE_SECRET');
  if (!expected) throw new Error('Bridge secret is not configured');
  if (!supplied || !constantTimeEqual_(String(supplied), String(expected))) throw new Error('Unauthorized');
}

function constantTimeEqual_(a, b) {
  const left = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, a, Utilities.Charset.UTF_8);
  const right = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, b, Utilities.Charset.UTF_8);
  let mismatch = 0;
  for (let i = 0; i < left.length; i++) mismatch |= left[i] ^ right[i];
  return mismatch === 0;
}

function sha256_(value) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(value), Utilities.Charset.UTF_8)
    .map(function(byte) { return ('0' + ((byte < 0 ? byte + 256 : byte).toString(16))).slice(-2); })
    .join('');
}

function validateAction_(action) {
  if (ALLOWED_ACTIONS.indexOf(action) === -1) throw new Error('Unsupported action');
}

function dispatch_(action, payload) {
  switch (action) {
    case 'PING': return {pong: true, rootFolderId: rootFolder_().getId()};
    case 'READ_DOC': return readDoc_(required_(payload, 'documentId'));
    case 'READ_SHEET_ROWS': return readSheetRows_(payload);
    case 'CREATE_DOC': return createDoc_(payload);
    case 'APPEND_DOC': return appendDoc_(payload);
    case 'APPEND_SHEET_ROW': return appendSheetRow_(payload);
    case 'RENAME_FILE': return renameFile_(payload);
    case 'MOVE_FILE': return moveFile_(payload);
    case 'TRASH_FILE': return trashFile_(payload);
    default: throw new Error('Unsupported action');
  }
}

function rootFolder_() {
  const rootId = PropertiesService.getScriptProperties().getProperty('AI_OS_ROOT_FOLDER_ID');
  if (!rootId) throw new Error('AI_OS root folder is not configured');
  return DriveApp.getFolderById(rootId);
}

function assertWithinRoot_(item) {
  const root = rootFolder_();
  const rootId = root.getId();
  if (item.getId() === rootId) return item;
  let queue = [];
  const directParentIds = {};
  const initialParents = item.getParents();
  while (initialParents.hasNext()) {
    const parent = initialParents.next();
    directParentIds[parent.getId()] = true;
    queue.push(parent);
  }
  const visited = {};
  let examined = 0;
  while (queue.length && examined < 200) {
    const folder = queue.shift();
    const folderId = folder.getId();
    if (folderId === rootId) return item;
    if (!visited[folderId]) {
      visited[folderId] = true;
      const parents = folder.getParents();
      while (parents.hasNext()) queue.push(parents.next());
    }
    examined += 1;
  }

  // DriveApp can omit ancestors from getParents() in some execution contexts.
  // Fall back to a bounded traversal from the configured root, accepting the
  // item only when one of its direct parents is actually below that root.
  queue = [root];
  const seenBelowRoot = {};
  examined = 0;
  while (queue.length && examined < 1000) {
    const folder = queue.shift();
    const folderId = folder.getId();
    if (directParentIds[folderId]) return item;
    if (!seenBelowRoot[folderId]) {
      seenBelowRoot[folderId] = true;
      const children = folder.getFolders();
      while (children.hasNext()) queue.push(children.next());
    }
    examined += 1;
  }
  throw new Error('Target is outside AI_OS root');
}

function assertMutableFile_(file) {
  assertWithinRoot_(file);
  if (file.getId() === rootFolder_().getId()) throw new Error('AI_OS root cannot be modified');
  return file;
}

function readDoc_(documentId) {
  const file = DriveApp.getFileById(documentId);
  assertWithinRoot_(file);
  const doc = DocumentApp.openById(documentId);
  const text = doc.getBody().getText();
  if (text.length > MAX_READ_LENGTH) throw new Error('Document exceeds read limit');
  return {documentId: documentId, name: doc.getName(), text: text};
}

function createDoc_(payload) {
  const title = boundedText_(required_(payload, 'title'), 500, 'title');
  const folder = DriveApp.getFolderById(required_(payload, 'folderId'));
  assertWithinRoot_(folder);
  const content = payload.content ? boundedText_(payload.content, MAX_TEXT_LENGTH, 'content') : '';
  const doc = DocumentApp.create(title);
  try {
    if (content) doc.getBody().setText(content);
    doc.saveAndClose();
    DriveApp.getFileById(doc.getId()).moveTo(folder);
    return {documentId: doc.getId(), url: doc.getUrl(), name: title};
  } catch (error) {
    try { DriveApp.getFileById(doc.getId()).setTrashed(true); } catch (cleanupError) { console.error(String(cleanupError)); }
    throw error;
  }
}

function appendDoc_(payload) {
  const documentId = required_(payload, 'documentId');
  assertMutableFile_(DriveApp.getFileById(documentId));
  const doc = DocumentApp.openById(documentId);
  doc.getBody().appendParagraph(boundedText_(required_(payload, 'text'), MAX_TEXT_LENGTH, 'text'));
  doc.saveAndClose();
  return {documentId: documentId, updated: true};
}

function readSheetRows_(payload) {
  const spreadsheetId = required_(payload, 'spreadsheetId');
  assertWithinRoot_(DriveApp.getFileById(spreadsheetId));
  const sheet = SpreadsheetApp.openById(spreadsheetId).getSheetByName(required_(payload, 'sheetName'));
  if (!sheet) throw new Error('Sheet not found');
  const rowCount = Math.min(Math.max(Number(payload.rowCount || 500), 1), 5000);
  const columnCount = Math.min(Math.max(Number(payload.columnCount || 11), 1), MAX_SHEET_COLUMNS);
  const lastRow = Math.min(sheet.getLastRow(), rowCount);
  if (!lastRow) return {spreadsheetId: spreadsheetId, sheetName: sheet.getName(), rows: []};
  return {
    spreadsheetId: spreadsheetId,
    sheetName: sheet.getName(),
    rows: sheet.getRange(1, 1, lastRow, columnCount).getDisplayValues()
  };
}

function appendSheetRow_(payload) {
  const spreadsheetId = required_(payload, 'spreadsheetId');
  assertMutableFile_(DriveApp.getFileById(spreadsheetId));
  const sheet = SpreadsheetApp.openById(spreadsheetId).getSheetByName(required_(payload, 'sheetName'));
  if (!sheet) throw new Error('Sheet not found');
  if (!Array.isArray(payload.values) || payload.values.length > MAX_SHEET_COLUMNS) {
    throw new Error('values must be an array within the column limit');
  }
  sheet.appendRow(payload.values.map(sanitizeCell_));
  SpreadsheetApp.flush();
  return {spreadsheetId: spreadsheetId, sheetName: sheet.getName(), row: sheet.getLastRow()};
}

function sanitizeCell_(value) {
  if (typeof value === 'string') {
    value = boundedText_(value, 50000, 'cell');
    if (/^[=+\-@]/.test(value)) return "'" + value;
  }
  return value;
}

function renameFile_(payload) {
  const file = assertMutableFile_(DriveApp.getFileById(required_(payload, 'fileId')));
  file.setName(boundedText_(required_(payload, 'name'), 500, 'name'));
  return {fileId: file.getId(), name: file.getName()};
}

function moveFile_(payload) {
  const file = assertMutableFile_(DriveApp.getFileById(required_(payload, 'fileId')));
  const destination = DriveApp.getFolderById(required_(payload, 'folderId'));
  assertWithinRoot_(destination);
  file.moveTo(destination);
  return {fileId: file.getId(), folderId: destination.getId()};
}

function trashFile_(payload) {
  const file = assertMutableFile_(DriveApp.getFileById(required_(payload, 'fileId')));
  file.setTrashed(true);
  return {fileId: file.getId(), trashed: true};
}

function boundedText_(value, maxLength, field) {
  const text = String(value);
  if (text.length > maxLength) throw new Error(field + ' exceeds length limit');
  return text;
}

function required_(object, key) {
  const value = object[key];
  if (value === undefined || value === null || value === '') throw new Error('Missing field: ' + key);
  return value;
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}
