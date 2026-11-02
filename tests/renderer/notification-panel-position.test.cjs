const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'notification-panel-position-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/notificationPanelPosition.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { notificationPanelPosition } = require(join(output, 'notificationPanelPosition.js'));

test('panel stays within a narrow viewport around a right-side trigger', () => {
  const placement = notificationPanelPosition(
    { top: 60, right: 312, bottom: 104 },
    { width: 320, height: 600 },
  );
  assert.equal(placement.left, 12);
  assert.equal(placement.width, 296);
  assert.equal(placement.top, 112);
  assert.ok(placement.left + placement.width <= 308);
  assert.ok(placement.top + placement.maxHeight <= 588);
});

test('panel opens above when the trigger has more usable space there', () => {
  const placement = notificationPanelPosition(
    { top: 650, right: 900, bottom: 694 },
    { width: 1024, height: 720 },
  );
  assert.equal(placement.opensAbove, true);
  assert.equal(placement.bottom, 78);
  assert.equal(placement.maxHeight, 630);
  assert.ok(placement.left >= 12);
  assert.ok(placement.left + placement.width <= 1012);
});

test('visual viewport offsets are included in fixed panel bounds', () => {
  const placement = notificationPanelPosition(
    { top: 120, right: 740, bottom: 164 },
    { width: 600, height: 500, offsetLeft: 200, offsetTop: 80 },
  );
  assert.ok(placement.left >= 212);
  assert.ok(placement.left + placement.width <= 788);
  if (placement.top !== undefined) assert.ok(placement.top >= 92);
});
