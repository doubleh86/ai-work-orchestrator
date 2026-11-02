const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const output = mkdtempSync(join(tmpdir(), 'run-archive-navigation-'));
try {
  const compiler = resolve(root, 'node_modules/typescript/bin/tsc');
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/runArchiveNavigation.ts'], { cwd: root, stdio: 'inherit' });
  const { archiveCompletionView, selectedRunView } = require(join(output, 'runArchiveNavigation.js'));

  test('archive completion opens read-only details only if the original view is still selected', () => {
    const requested = { projectName: 'project', runId: 'run', scope: 'active' };
    assert.equal(archiveCompletionView(requested, { ...requested }), 'operations');
    assert.equal(archiveCompletionView(requested, { ...requested, runId: 'other' }), null);
    assert.equal(archiveCompletionView(requested, { ...requested, projectName: 'other' }), null);
    assert.equal(archiveCompletionView(requested, { ...requested, scope: 'archived' }), null);
  });

  test('selecting an archived group opens archive details instead of its old task screen', () => {
    assert.equal(selectedRunView('archived'), 'operations');
    assert.equal(selectedRunView('active'), 'tasks');
  });
} finally {
  rmSync(output, { recursive: true, force: true });
}
