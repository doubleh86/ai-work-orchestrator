const { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } = require('node:fs');
const { dirname, isAbsolute, join, relative, resolve, sep } = require('node:path');

function inside(directory, file) {
  const path = relative(directory, file);
  return path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

function copyPublicNotices(root, destination) {
  root = resolve(root);
  destination = resolve(destination);
  if (existsSync(destination)) throw new Error('License output already exists; refusing to overwrite it');
  const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
  const files = [
    ['LICENSE', 'APP-LICENSE.txt'],
    ['THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.md'],
    ['licenses/Apache-2.0.txt', 'codex/LICENSE'],
  ].map(([source, target]) => ({ source: join(root, source), target }));
  const packages = [];
  for (const [folder, data] of Object.entries(lock.packages)) {
    if (!folder || data.dev) continue;
    const directory = resolve(root, folder);
    if (!folder.startsWith('node_modules/') || !inside(join(root, 'node_modules'), directory)) {
      throw new Error('Invalid runtime package path in lock file');
    }
    const metadata = JSON.parse(readFileSync(join(directory, 'package.json'), 'utf8'));
    const notices = readdirSync(directory, { withFileTypes: true }).filter((file) =>
      file.isFile() && /^(?:LICEN[CS]E|COPYING|NOTICE|OFL)(?:[.-]|$)/iu.test(file.name));
    if (!notices.length) throw new Error(`Runtime package has no license or notice file: ${folder}`);
    const targets = [];
    for (const notice of notices) {
      const target = join('npm', folder, notice.name);
      files.push({ source: join(directory, notice.name), target });
      targets.push(target.split(sep).join('/'));
    }
    packages.push({ name: metadata.name, version: metadata.version, license: data.license, notices: targets });
  }
  for (const file of files) {
    if (!existsSync(file.source)) throw new Error(`Required public license file is missing: ${relative(root, file.source)}`);
  }
  for (const file of files) {
    const target = join(destination, file.target);
    if (!inside(destination, target)) throw new Error('Invalid license destination');
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(file.source, target);
  }
  writeFileSync(join(destination, 'npm-licenses.json'), JSON.stringify(packages, null, 2) + '\n', 'utf8');
  return packages;
}

module.exports = { copyPublicNotices };
