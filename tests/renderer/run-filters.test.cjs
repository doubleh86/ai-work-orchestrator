const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'run-filters-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/runFilters.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'runFilters.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject });
const { filterRuns, runFilterCounts } = exportsObject;

function run(id, overrides = {}) {
  return {
    id,
    summary: id,
    stage: 'planned',
    updated_at: '', created_at: '', task_count: 1, completed_task_count: 0,
    archived: false, archived_at: '', cleanup_status: '', failed_task_count: 0,
    waiting_task_count: 0, plan_is_approved: true, attention_reasons: [],
    execution_situation: 'ready', pipeline_complete: false, checked_at: '',
    ...overrides,
  };
}

test('search and status filters compose while counts follow the search result', () => {
  const runs = [
    run('build-running', { execution_situation: 'running' }),
    run('build-failed', { stage: 'failed', failed_task_count: 1, attention_reasons: ['failure_recovery'] }),
    run('docs-confirm', { attention_reasons: ['plan_confirmation'] }),
    run('build-complete', { stage: 'pushed', pipeline_complete: true, completed_task_count: 1 }),
  ];

  assert.deepEqual(Array.from(filterRuns(runs, 'build', 'running'), (item) => item.id), ['build-running']);
  assert.deepEqual(Array.from(filterRuns(runs, 'build', 'attention'), (item) => item.id), ['build-failed']);
  assert.deepEqual(Array.from(filterRuns(runs, 'build', 'completed'), (item) => item.id), ['build-complete']);
  assert.deepEqual({ ...runFilterCounts(runs, 'build') }, {
    all: 3, running: 1, failed: 1, attention: 1, completed: 1,
  });
});
