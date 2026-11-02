const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'tech-stack-decision-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/techStackDecision.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'techStackDecision.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject });
const { activeTechStackDecision, techStackCoreItems, techStackDevelopmentItems } = exportsObject;

const components = {
  languages: ['TypeScript'], runtimes: ['Node.js'], application_frameworks: ['Electron'],
  ui_frameworks: ['React'], persistence: ['SQLite'], package_and_build_tools: ['npm'],
  test_tools: ['Node test runner'], style_and_analysis: ['TypeScript strict'],
  packaging_and_deployment: ['Windows installer'],
};

test('active technology stack decision skips superseded history', () => {
  const oldDecision = { revision: 1, status: 'superseded' };
  const currentDecision = { revision: 2, status: 'options_ready' };
  assert.equal(activeTechStackDecision([oldDecision, currentDecision]), currentDecision);
});

test('technology stack cards group core and development components', () => {
  const option = { components };
  assert.deepEqual(Array.from(techStackCoreItems(option)), ['TypeScript', 'Node.js', 'Electron', 'React', 'SQLite']);
  assert.deepEqual(Array.from(techStackDevelopmentItems(option)), ['npm', 'Node test runner', 'TypeScript strict']);
});
