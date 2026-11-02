const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'main-changes-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output, 'desktop/renderer/src/mainChanges.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'mainChanges.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject });
const { mainCanPull, mainCanPush, mainSnapshotSummary, mainSyncLabel } = exportsObject;

function snapshot(relation, changes = [], ahead = 0, behind = 0) {
  return {
    blocked_reason: '', changes,
    sync: { relation, ahead, behind, remote: 'origin', target_branch: 'main' },
  };
}

test('Main summary keeps local files and commit directions separate', () => {
  const value = snapshot('diverged', [{ path: 'a' }, { path: 'b' }], 2, 3);
  assert.equal(mainSnapshotSummary(value), '로컬 변경 2개 · 보낼 커밋 2개 · 받을 커밋 3개 · 통합 필요');
  assert.equal(mainSyncLabel(snapshot('unknown').sync), '원격 상태 미확인');
});

test('pull and push actions require a safe one-way relation', () => {
  assert.equal(mainCanPull(snapshot('behind', [], 0, 2)), true);
  assert.equal(mainCanPull(snapshot('behind', [{ path: 'dirty' }], 0, 2)), false);
  assert.equal(mainCanPush(snapshot('ahead', [], 2, 0)), true);
  assert.equal(mainCanPush(snapshot('diverged', [], 2, 1)), false);
  assert.equal(mainCanPush({ ...snapshot('ahead', [], 2, 0), blocked_reason: 'wrong branch' }), false);
});
