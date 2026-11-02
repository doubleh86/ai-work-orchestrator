const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

const root = resolve(__dirname, '../..');
const app = readFileSync(resolve(root, 'desktop/renderer/src/App.tsx'), 'utf8');
const types = readFileSync(resolve(root, 'desktop/renderer/src/types.ts'), 'utf8');

test('verification history shows commit queue and bounded failure attribution evidence', () => {
  assert.match(types, /commit_queue_task_ids: string\[\]/);
  assert.match(types, /candidate_task_ids: string\[\]/);
  assert.match(types, /attribution_reason: string/);
  assert.match(app, /Commit Queue 순서/);
  assert.match(app, /직접 실패한 작업/);
  assert.match(app, /관련 작업 후보/);
  assert.match(app, /귀속 근거/);
});
