const { execFileSync, spawnSync } = require('node:child_process');
const { existsSync, mkdirSync, cpSync, writeFileSync, readdirSync, renameSync } = require('node:fs');
const { join, resolve } = require('node:path');

const { checkMacArchitecture, selectedPython } = require('./macos_architecture.cjs');
const { copyPublicNotices } = require('./third_party_notices.cjs');

const root = resolve(__dirname, '..');
const buildRoot = join(root, 'build', 'macos-arm64');
const appPath = join(buildRoot, 'AI Work Orchestrator.app');
const stagedAppPath = join(buildRoot, 'AI Work Orchestrator.staging.app');
const bundleId = 'local.ai-work-orchestrator.desktop';

function run(command, args, environment = process.env) {
  const completed = spawnSync(command, args, { cwd: root, stdio: 'inherit', env: environment });
  if (completed.error) throw completed.error;
  if (completed.status !== 0) throw new Error(`${command} failed with exit code ${completed.status}`);
}

function setPlist(plist, key, value) {
  run('plutil', ['-replace', key, '-string', value, plist]);
}

function requireArm64(binary, label) {
  const architectures = execFileSync('lipo', ['-archs', binary], { encoding: 'utf8' }).trim().split(/\s+/u);
  if (!architectures.includes('arm64')) throw new Error(`${label} is not arm64: ${architectures.join(', ')}`);
}

function rebrandApp(version) {
  const contents = join(stagedAppPath, 'Contents');
  const info = join(contents, 'Info.plist');
  setPlist(info, 'CFBundleDisplayName', 'AI Work Orchestrator');
  setPlist(info, 'CFBundleName', 'AI Work Orchestrator');
  setPlist(info, 'CFBundleIdentifier', bundleId);
  setPlist(info, 'CFBundleShortVersionString', version);
  setPlist(info, 'CFBundleVersion', version);
  const frameworks = join(contents, 'Frameworks');
  let helperIndex = 0;
  for (const name of readdirSync(frameworks)) {
    if (!name.endsWith('.app')) continue;
    const helperInfo = join(frameworks, name, 'Contents', 'Info.plist');
    if (!existsSync(helperInfo)) continue;
    setPlist(helperInfo, 'CFBundleDisplayName', name.replace(/^Electron/u, 'AI Work Orchestrator').replace(/\.app$/u, ''));
    setPlist(helperInfo, 'CFBundleName', name.replace(/^Electron/u, 'AI Work Orchestrator').replace(/\.app$/u, ''));
    setPlist(helperInfo, 'CFBundleIdentifier', `${bundleId}.helper.${helperIndex++}`);
    setPlist(helperInfo, 'CFBundleShortVersionString', version);
    setPlist(helperInfo, 'CFBundleVersion', version);
  }
}

function main() {
  if (process.platform !== 'darwin' || process.arch !== 'arm64') {
    throw new Error('macOS arm64 Node.js에서만 Apple Silicon 앱을 빌드할 수 있습니다.');
  }
  const python = selectedPython(root);
  checkMacArchitecture(root, python);
  if (existsSync(appPath)) throw new Error(`기존 빌드가 있습니다. 먼저 확인하고 별도로 이동하거나 정리하세요: ${appPath}`);
  if (existsSync(stagedAppPath)) throw new Error(`완료되지 않은 빌드가 있습니다. 먼저 확인하세요: ${stagedAppPath}`);

  run(python, ['-c', 'import mcp']);
  run('npm', ['run', 'build']);
  mkdirSync(buildRoot, { recursive: true });
  const backendDist = join(buildRoot, 'backend-dist');
  const pyinstallerConfig = join(buildRoot, 'pyinstaller-config');
  mkdirSync(pyinstallerConfig, { recursive: true });
  run(python, [
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--target-arch', 'arm64',
    '--name', 'ai-orchestrator-backend', '--paths', join(root, 'src'),
    '--collect-all', 'openai_codex', '--collect-all', 'codex_cli_bin', '--collect-data', 'mcp',
    '--recursive-copy-metadata', 'mcp',
    '--distpath', backendDist, '--workpath', join(buildRoot, 'pyinstaller-work'),
    '--specpath', buildRoot, join(root, 'scripts', 'desktop_backend.py'),
  ], { ...process.env, PYINSTALLER_CONFIG_DIR: pyinstallerConfig });
  const frozenBackend = join(backendDist, 'ai-orchestrator-backend', 'ai-orchestrator-backend');
  requireArm64(frozenBackend, 'Python backend');
  requireArm64(join(backendDist, 'ai-orchestrator-backend', '_internal', 'codex_cli_bin', 'bin', 'codex'), 'Codex runtime');

  const electronApp = join(root, 'node_modules', 'electron', 'dist', 'Electron.app');
  run('ditto', [electronApp, stagedAppPath]);
  const resources = join(stagedAppPath, 'Contents', 'Resources');
  const appResources = join(resources, 'app');
  mkdirSync(appResources, { recursive: true });
  cpSync(join(root, 'dist-electron'), join(appResources, 'dist-electron'), { recursive: true });
  cpSync(join(root, 'dist', 'renderer'), join(appResources, 'dist', 'renderer'), { recursive: true });
  const sourcePackage = require(join(root, 'package.json'));
  writeFileSync(join(appResources, 'package.json'), JSON.stringify({
    name: sourcePackage.name,
    version: sourcePackage.version,
    main: sourcePackage.main,
  }, null, 2) + '\n', 'utf8');
  copyPublicNotices(root, join(appResources, 'licenses'));
  run('ditto', [join(backendDist, 'ai-orchestrator-backend'), join(resources, 'backend')]);
  rebrandApp(sourcePackage.version);
  requireArm64(join(stagedAppPath, 'Contents', 'MacOS', 'Electron'), 'Electron app');
  requireArm64(join(stagedAppPath, 'Contents', 'Frameworks', 'Electron Helper.app', 'Contents', 'MacOS', 'Electron Helper'), 'Electron Helper');
  run('codesign', ['--force', '--deep', '--sign', '-', stagedAppPath]);
  run('codesign', ['--verify', '--deep', '--strict', stagedAppPath]);
  renameSync(stagedAppPath, appPath);
  process.stdout.write(`arm64 앱 빌드 완료: ${appPath}\n`);
}

try {
  main();
} catch (error) {
  process.stderr.write(`Apple Silicon 앱 빌드 실패: ${error.message}\n`);
  process.exitCode = 1;
}
