const { test } = require('node:test');
const assert = require('node:assert/strict');
const { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { tmpdir } = require('node:os');
const { copyPublicNotices } = require('../../scripts/third_party_notices.cjs');

function fixture(action) {
  const parent = resolve(tmpdir());
  const root = mkdtempSync(join(parent, 'public-notices-'));
  const put = (file, value) => { const path = join(root, file); mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, value); };
  try {
    put('LICENSE', 'App MIT copyright'); put('THIRD_PARTY_NOTICES.md', 'Dependency notices');
    put('licenses/Apache-2.0.txt', 'Apache license');
    put('package-lock.json', JSON.stringify({ packages: { '': {},
      'node_modules/font': { version: '1.0.0', license: 'OFL-1.1' },
      'node_modules/build-only': { version: '1.0.0', dev: true, license: 'MIT' },
    } }));
    put('node_modules/font/package.json', JSON.stringify({ name: 'font', version: '1.0.0' }));
    put('node_modules/font/LICENSE', 'Font copyright and complete OFL');
    action({ root, put, destination: join(root, 'output', 'licenses') });
  } finally { assert.equal(dirname(root), parent); rmSync(root, { recursive: true, force: true }); }
}

test('public notices preserve app, runtime font and Codex licenses without requiring unshipped build dependencies', () => fixture(({ root, put, destination }) => {
  put('output/LICENSE', 'Electron copyright');
  const packages = copyPublicNotices(root, destination);
  assert.equal(readFileSync(join(root, 'output/LICENSE'), 'utf8'), 'Electron copyright');
  assert.equal(readFileSync(join(destination, 'APP-LICENSE.txt'), 'utf8'), 'App MIT copyright');
  assert.equal(readFileSync(join(destination, 'codex/LICENSE'), 'utf8'), 'Apache license');
  assert.equal(readFileSync(join(destination, 'npm/node_modules/font/LICENSE'), 'utf8'), 'Font copyright and complete OFL');
  assert.deepEqual(packages.map((entry) => entry.name), ['font']);
  assert.deepEqual(JSON.parse(readFileSync(join(destination, 'npm-licenses.json'), 'utf8')), packages);
}));

test('missing runtime license stops packaging before creating incomplete notices', () => fixture(({ root, destination }) => {
  rmSync(join(root, 'node_modules/font/LICENSE'));
  assert.throws(() => copyPublicNotices(root, destination), /no license or notice/);
  assert.equal(existsSync(destination), false);
}));

test('a missing app or Apache license is a packaging failure', () => fixture(({ root, destination }) => {
  rmSync(join(root, 'licenses/Apache-2.0.txt'));
  assert.throws(() => copyPublicNotices(root, destination), /Required public license/);
  assert.equal(existsSync(destination), false);
}));

test('existing license output is preserved instead of overwritten', () => fixture(({ root, put, destination }) => {
  put('output/licenses/keep.txt', 'keep');
  assert.throws(() => copyPublicNotices(root, destination), /refusing to overwrite/);
  assert.equal(readFileSync(join(destination, 'keep.txt'), 'utf8'), 'keep');
}));

test('a lock entry cannot read notices outside the node_modules boundary', () => fixture(({ root, put, destination }) => {
  put('package-lock.json', JSON.stringify({ packages: { 'node_modules/../outside': { license: 'MIT' } } }));
  assert.throws(() => copyPublicNotices(root, destination), /Invalid runtime package path/);
  assert.equal(existsSync(destination), false);
}));
