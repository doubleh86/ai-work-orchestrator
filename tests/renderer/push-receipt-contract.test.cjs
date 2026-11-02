const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

const root = resolve(__dirname, '../..');
const app = readFileSync(resolve(root, 'desktop/renderer/src/App.tsx'), 'utf8');
const types = readFileSync(resolve(root, 'desktop/renderer/src/types.ts'), 'utf8');

test('operations view shows persisted remote push evidence', () => {
  assert.match(types, /export interface PushReceipt/);
  assert.match(types, /remote_commit: string/);
  assert.match(types, /operation_request_id: string/);
  assert.match(types, /push_receipts: PushReceipt\[\]/);
  assert.match(app, /Push 기록/);
  assert.match(app, /확인한 원격 commit/);
  assert.match(app, /원격 branch가 Push 대상 commit과 일치합니다/);
});
