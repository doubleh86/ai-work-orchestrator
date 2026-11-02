const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, rmSync, readFileSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'work-panel-test-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { force: true, recursive: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/WorkDialog.tsx'], { cwd: root, stdio: 'inherit' });
const modulePath = join(output, 'WorkDialog.js'), localRequire = createRequire(modulePath);

function render(props) {
  const effects = [], exports = {};
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, require: name => name === 'react' ? {
    useRef: current => ({ current }), useEffect: effect => effects.push(effect),
  } : localRequire(name) });
  return { tree: exports.WorkDialog({ title: '프로젝트에 적용', titleId: 'apply', context: '프로젝트',
    onClose() {}, children: '작업 내용', ...props }), effects };
}

test('inline operation content does not open a native modal or duplicate the drawer heading and close action', () => {
  const { tree, effects } = render({ inline: true, suspendPlanning: true, footer: '결과' });
  assert.equal(tree.type, 'section');
  assert.equal(tree.props['aria-label'], '프로젝트에 적용');
  assert.equal(tree.props.hidden, false);
  assert.equal(tree.props.children[0].props.children, '작업 내용');
  assert.equal(tree.props.children[1].type, 'footer');
  for (const effect of effects) assert.equal(effect(), undefined, 'inline mode must not touch document or suspend chat');
});

test('closing inline content hides it while preserving mounted drafts; ordinary dialogs keep their existing modal structure', () => {
  const closed = render({ inline: true, open: false });
  assert.equal(closed.tree.props.hidden, true);
  assert.equal(closed.tree.props.children[0].props.children, '작업 내용');
  const native = render({});
  assert.equal(native.tree.type, 'dialog');
  assert.match(native.tree.props.className, /modal work-dialog/);
  assert.equal(native.tree.props.children[0].type, 'header');
});
