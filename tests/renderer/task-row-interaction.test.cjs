const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'task-row-interaction-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/taskRowInteraction.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { shouldSelectTaskRow, taskRowInteractiveSelector } = require(join(output, 'taskRowInteraction.js'));
const intent = (overrides = {}) => ({
  defaultPrevented: false,
  interactiveTarget: false,
  textSelected: false,
  pointerDragged: false,
  ...overrides,
});

test('ordinary row space selects only the task detail', () => {
  assert.equal(shouldSelectTaskRow(intent()), true);
});

test('controls, prevented events, text selection, and drag do not select the row', () => {
  for (const reason of ['defaultPrevented', 'interactiveTarget', 'textSelected', 'pointerDragged']) {
    assert.equal(shouldSelectTaskRow(intent({ [reason]: true })), false, reason);
  }
});

test('interactive selector covers native and declared row controls', () => {
  for (const selector of ['button', 'input', 'select', 'textarea', 'a', 'label', "[role='button']", '[data-task-row-control]']) {
    assert.match(taskRowInteractiveSelector, new RegExp(selector.replace(/[\[\]]/g, '\\$&')));
  }
});
