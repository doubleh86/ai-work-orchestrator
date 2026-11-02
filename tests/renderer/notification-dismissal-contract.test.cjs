const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

const root = resolve(__dirname, '../..');
const app = readFileSync(resolve(root, 'desktop/renderer/src/App.tsx'), 'utf8');

test('notification cleanup exposes item, read, and confirmed all dismissal actions', () => {
  assert.match(app, /aria-label=\{`\$\{copy\.title\} 알림 지우기`\}/);
  assert.match(app, /읽은 알림 \{readCount\}개 지우기/);
  assert.match(app, /모든 알림 \{snapshot\.items\.length\}개 지우기/);
  assert.match(app, /작업과 로그는 삭제되지 않습니다/);
  assert.match(app, /알림을 지우지 못했습니다\. 다시 시도해 주세요/);
});
