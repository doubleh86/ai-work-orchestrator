const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'run-archive-cache-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/runArchiveCache.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'runArchiveCache.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject, Set });
const { applyArchivedRun, reconcileRunScope } = exportsObject;

function run(id, overrides = {}) {
  return {
    id,
    summary: id,
    stage: 'pushed',
    updated_at: '2026-09-21T01:00:00+00:00',
    created_at: '2026-09-21T00:00:00+00:00',
    task_count: 1,
    completed_task_count: 1,
    archived: false,
    archived_at: '',
    cleanup_status: '',
    failed_task_count: 0,
    waiting_task_count: 0,
    plan_is_approved: true,
    attention_reasons: [],
    execution_situation: 'complete',
    pipeline_complete: true,
    checked_at: '2026-09-21T01:00:00+00:00',
    ...overrides,
  };
}

test('archive success removes the run from active and inserts it into archived immediately', () => {
  const target = run('target');
  const other = run('other');
  const archived = run('target', {
    archived: true,
    archived_at: '2026-09-21T02:00:00+00:00',
    cleanup_status: 'partial',
    updated_at: '2026-09-21T02:00:00+00:00',
  });
  const result = applyArchivedRun({ project: { active: [target, other], archived: [] } }, 'project', archived);

  assert.deepEqual(Array.from(result.project.active, (item) => item.id), ['other']);
  assert.deepEqual(Array.from(result.project.archived, (item) => item.id), ['target']);
  assert.equal(result.project.archived[0].cleanup_status, 'partial');
});

test('late active response cannot resurrect an authoritatively archived run', () => {
  const archived = run('target', { archived: true, archived_at: '2026-09-21T02:00:00+00:00' });
  const staleActive = run('target');
  const result = reconcileRunScope({}, 'project', 'active', [staleActive, run('other')], [archived]);

  assert.deepEqual(Array.from(result.project.active, (item) => item.id), ['other']);
});

test('late archived response keeps the mutation result and accepts a fresher server summary', () => {
  const authoritative = run('target', {
    archived: true,
    archived_at: '2026-09-21T02:00:00+00:00',
    cleanup_status: 'partial',
    updated_at: '2026-09-21T02:00:00+00:00',
  });
  const missing = reconcileRunScope({}, 'project', 'archived', [], [authoritative]);
  assert.deepEqual(Array.from(missing.project.archived, (item) => item.id), ['target']);

  const fresher = { ...authoritative, cleanup_status: 'completed', updated_at: '2026-09-21T03:00:00+00:00' };
  const refreshed = reconcileRunScope(missing, 'project', 'archived', [fresher], [authoritative]);
  assert.equal(refreshed.project.archived[0].cleanup_status, 'completed');
});

test('renderer requests the archived scope explicitly and preserves navigation during archive refresh', () => {
  const app = readFileSync(join(root, 'desktop/renderer/src/App.tsx'), 'utf8');
  assert.match(app, /scope: "archived",\s*preferredRun: targetRunId,/);
  assert.match(app, /archiveRefresh: true,/);
  assert.match(app, /const completionView = archiveCompletionView\(requestContext,/);
  assert.match(app, /archiveTransitionRef\.current = \{ projectName, runId: targetRunId \}/);
  assert.match(app, /setWorkbenchView\(completionView\)/);
  assert.match(app, /기록 보관 완료 · 목록을 다시 확인하지 못했습니다/);
  assert.match(app, /목록 다시 확인/);
});
