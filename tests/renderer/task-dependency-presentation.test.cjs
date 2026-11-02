const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'task-dependency-presentation-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/taskDependencyPresentation.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { taskDependencySections } = require(join(output, 'taskDependencyPresentation.js'));
const task = (id, overrides = {}) => ({
  id, title: id, status: 'pending', blocked_by: [], dependencies: [],
  conflict_dependencies: [], conflict_group: [], ...overrides,
});

test('direct and inferred blockers stay distinct from conflict analysis', () => {
  const current = task('current', {
    dependencies: ['api', 'missing', 'api'],
    conflict_dependencies: ['api', 'schema'],
    conflict_group: ['current', 'api', 'peer'],
    blocked_by: ['api', 'schema'],
  });
  const sections = taskDependencySections(current, [
    current,
    task('api', { title: '로그인 API', status: 'running' }),
    task('schema', { title: '스키마 작업', status: 'pending' }),
    task('peer', { title: '같은 파일 수정', status: 'completed' }),
  ]);

  assert.deepEqual(sections.map(({ kind, items }) => [kind, items.map(({ id }) => id)]), [
    ['declared', ['api', 'missing']],
    ['inferred', ['schema']],
    ['conflict', ['api', 'peer']],
  ]);
  assert.equal(sections[0].items[0].title, '로그인 API');
  assert.equal(sections[0].items[0].status, 'running');
  assert.equal(sections[0].items[0].blocked, true);
  assert.equal(sections[0].items[1].available, false);
  assert.equal(sections[0].items[1].title, '확인 불가');
  assert.equal(sections[1].items[0].blocked, true);
  assert.equal(sections[2].items[0].blocked, false);
});

test('current draft titles and dependencies replace saved presentation without losing unknown IDs', () => {
  const selected = task('current', { dependencies: ['draft-name', 'unknown'] });
  const sections = taskDependencySections(selected, [selected, task('draft-name', { title: '수정 중인 제목' })]);
  assert.deepEqual(sections.map(({ kind }) => kind), ['declared']);
  assert.equal(sections[0].items[0].title, '수정 중인 제목');
  assert.equal(sections[0].items[0].available, true);
  assert.equal(sections[0].items[1].id, 'unknown');
  assert.equal(sections[0].items[1].available, false);
  assert.deepEqual(taskDependencySections(task('alone'), [task('alone')]), []);
});
