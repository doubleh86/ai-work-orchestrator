# Third-party software notices

AI Work Orchestrator source is provided under the MIT license in LICENSE.
Dependency licenses remain with their respective copyright holders.

| Component | License | Source |
| --- | --- | --- |
| Electron | MIT, with Chromium and other bundled notices | https://github.com/electron/electron |
| React, React DOM and Scheduler | MIT | https://github.com/facebook/react |
| Lucide React | ISC | https://github.com/lucide-icons/lucide |
| react-markdown and remark-gfm dependencies | MIT and dependency-specific notices | https://github.com/remarkjs/react-markdown |
| Geist font | SIL Open Font License 1.1 | https://github.com/vercel/geist-font |
| JetBrains Mono font | SIL Open Font License 1.1 | https://github.com/JetBrains/JetBrainsMono |
| OpenAI Codex Python SDK and bundled Codex CLI | Apache License 2.0 | https://github.com/openai/codex |
| Pydantic and other Python runtime packages | Package-specific licenses in distribution metadata | https://github.com/pydantic/pydantic |
| PyInstaller build tool | GPL with a distribution exception | https://pyinstaller.org/en/stable/license.html |

The package manager distributions provide the complete licenses for installed dependencies.
The desktop packaging scripts also copy npm runtime dependency notices, the application
license, and the Codex Apache license into the application resources. Electron's own
LICENSE and LICENSES.chromium.html must remain in the product. Python dependency
license metadata collected by the packager must remain in the frozen backend.

The source release does not contain credentials, user state, old release archives,
or copies of third-party native runtimes. Binary releases need a separate review of
all bundled software, fonts, notices, architecture and platform behavior.
