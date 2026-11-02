const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const output = mkdtempSync(join(tmpdir(), 'notification-dismiss-focus-'));
try {
  const compiler = resolve(root, 'node_modules/typescript/bin/tsc');
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/notificationDismissFocus.ts'], { cwd: root, stdio: 'inherit' });
  const { notificationDismissFocusIndex } = require(join(output, 'notificationDismissFocus.js'));

  test('dismiss focus waits until the removed event leaves the committed list', () => {
    const request = { eventId: 'first', index: 0 };
    assert.equal(notificationDismissFocusIndex(request, [{ event_id: 'first' }, { event_id: 'second' }]), null);
    assert.equal(notificationDismissFocusIndex(request, [{ event_id: 'second' }]), 0);
  });

  test('dismiss focus chooses the previous row or close button at the end', () => {
    const request = { eventId: 'last', index: 2 };
    assert.equal(notificationDismissFocusIndex(request, [{ event_id: 'first' }, { event_id: 'middle' }]), 1);
    assert.equal(notificationDismissFocusIndex({ eventId: 'only', index: 0 }, []), -1);
  });
} finally {
  rmSync(output, { recursive: true, force: true });
}
