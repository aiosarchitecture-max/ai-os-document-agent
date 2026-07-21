const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function iterator(items) {
  let index = 0;
  return { hasNext: () => index < items.length, next: () => items[index++] };
}

function makeFolder(id, parents = []) {
  return { getId: () => id, getParents: () => iterator(parents) };
}

function makeFile(id, parents = []) {
  let name = id;
  let trashed = false;
  return {
    getId: () => id,
    getParents: () => iterator(parents),
    getName: () => name,
    setName: value => { name = value; },
    setTrashed: value => { trashed = value; },
    isTrashed: () => trashed,
    moveTo: () => {},
  };
}

function loadBridge(options = {}) {
  const root = makeFolder('root');
  const inside = makeFolder('inside', [root]);
  const outside = makeFolder('outside');
  const files = {
    insideFile: makeFile('insideFile', [inside]),
    outsideFile: makeFile('outsideFile', [outside]),
  };
  const folders = { root, inside, outside };
  const cache = new Map();
  const properties = {
    AI_OS_BRIDGE_SECRET: 'test-secret',
    AI_OS_ROOT_FOLDER_ID: 'root',
    ...(options.properties || {}),
  };
  if (options.removeSecret) delete properties.AI_OS_BRIDGE_SECRET;
  if (options.removeRoot) delete properties.AI_OS_ROOT_FOLDER_ID;

  const context = {
    console,
    PropertiesService: { getScriptProperties: () => ({ getProperty: key => properties[key] || null }) },
    Utilities: {
      getUuid: () => 'fallback-id',
      DigestAlgorithm: { SHA_256: 'sha256' },
      Charset: { UTF_8: 'utf8' },
      computeDigest: (_algorithm, value) => Array.from(crypto.createHash('sha256').update(value, 'utf8').digest()).map(x => x > 127 ? x - 256 : x),
    },
    LockService: { getScriptLock: () => ({ waitLock: () => {}, releaseLock: () => {} }) },
    CacheService: { getScriptCache: () => ({ get: key => cache.get(key) || null, put: (key, value) => cache.set(key, value) }) },
    ContentService: {
      MimeType: { JSON: 'application/json' },
      createTextOutput: content => ({ content, setMimeType() { return this; } }),
    },
    DriveApp: {
      getFolderById: id => {
        if (!folders[id]) throw new Error('Folder not found');
        return folders[id];
      },
      getFileById: id => {
        if (!files[id]) throw new Error('File not found');
        return files[id];
      },
    },
    DocumentApp: {},
    SpreadsheetApp: {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'Code.gs'), 'utf8'), context);
  return { context, files };
}

function post(context, body) {
  return JSON.parse(context.doPost({ postData: { contents: JSON.stringify(body) } }).content);
}

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test('fails closed when the bridge secret is not configured', () => {
  const { context } = loadBridge({ removeSecret: true });
  assert.match(post(context, { secret: 'anything', action: 'PING' }).error, /not configured/);
});

test('rejects an incorrect secret', () => {
  const { context } = loadBridge();
  assert.match(post(context, { secret: 'wrong', action: 'PING' }).error, /Unauthorized/);
});

test('accepts an authenticated ping and verifies the root', () => {
  const { context } = loadBridge();
  const result = post(context, { secret: 'test-secret', action: 'PING' });
  assert.equal(result.status, 'success');
  assert.equal(result.data.rootFolderId, 'root');
});

test('fails closed when the AI_OS root is not configured', () => {
  const { context } = loadBridge({ removeRoot: true });
  const result = post(context, { secret: 'test-secret', action: 'PING' });
  assert.match(result.error, /root folder is not configured/);
});

test('requires a requestId for every write operation', () => {
  const { context } = loadBridge();
  const result = post(context, { secret: 'test-secret', action: 'RENAME_FILE', payload: { fileId: 'insideFile', name: 'new' } });
  assert.match(result.error, /requestId is required/);
});

test('rejects writes outside the configured AI_OS root', () => {
  const { context } = loadBridge();
  const result = post(context, { secret: 'test-secret', action: 'RENAME_FILE', requestId: 'r1', payload: { fileId: 'outsideFile', name: 'new' } });
  assert.match(result.error, /outside AI_OS root/);
});

test('executes an in-root write only once for the same requestId', () => {
  const { context, files } = loadBridge();
  const body = { secret: 'test-secret', action: 'RENAME_FILE', requestId: 'r2', payload: { fileId: 'insideFile', name: 'renamed' } };
  const first = post(context, body);
  const second = post(context, { ...body, payload: { ...body.payload, name: 'must-not-run' } });
  assert.equal(first.status, 'success');
  assert.equal(first.duplicate, false);
  assert.equal(second.duplicate, true);
  assert.equal(files.insideFile.getName(), 'renamed');
});

test('neutralizes spreadsheet formula injection', () => {
  const { context } = loadBridge();
  assert.equal(context.sanitizeCell_('=IMPORTDATA("https://example.invalid")'), "'=IMPORTDATA(\"https://example.invalid\")");
  assert.equal(context.sanitizeCell_('ordinary text'), 'ordinary text');
});

let failures = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`ok - ${name}`); }
  catch (error) { failures += 1; console.error(`not ok - ${name}\n${error.stack}`); }
}
if (failures) process.exit(1);
