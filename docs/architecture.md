# Screen Translator architecture

## Direction

Screen Translator is a modular Windows desktop application, not a distributed service. Keep process and deployment boundaries small while enforcing dependency direction inside the application.

```text
Qt UI / overlays
       ↓
application controller + capture session + task runner
       ↓
OCR / translation / rendering contracts
       ↓
PaddleOCR, llama.cpp, OpenCV, Win32, model storage
```

The UI may issue commands and render state, but must not perform OCR, translation, network, or process work directly. Infrastructure implementations must not mutate Qt widgets from background threads.

## Session lifecycle

The valid capture lifecycle is:

```text
IDLE → SELECTING → PROCESSING → RESULT → IDLE
                    ↓
                CANCELLING → IDLE
```

Every background result carries the generation that created it. A result may update application state only when its generation is current. Cancelling invalidates the generation before closing overlays, so late signals cannot affect a newer task.

## Extension points

- `OcrPort`: image to structured OCR result.
- `TranslationPort`: text blocks to translated blocks, including model lifecycle.
- `RendererPort`: translated blocks to a rendered image.
- Factories are supplied to `Controller`; production defaults use PaddleOCR, llama.cpp, and OpenCV.

New model backends should implement these contracts and be selected during bootstrap. They should not add backend-specific branches to settings or overlay code.

GGUF variants are declared in the translation-model catalog. Configuration stores a stable model ID rather than a filename. `ModelRegistry` resolves that ID and each OCR role through the shared repository registry; engines never construct model filenames. Registry paths are relative, root-confined, dependency-aware, and validated by size or full hash. The v0.x flat `manifest.json` remains a read-only compatibility input.

The canonical local repository is `D:\AI\Models`, while mutable Screen Translator datasets, caches, runs, checkpoints, and unqualified adapters live in `D:\AI\Training\screen-translator`. Downloads publish into a model-specific directory and atomically replace the registry. Redownload quarantines only the selected translation artifact. Application upgrades and uninstall never mutate either shared root.

## Threading

`TaskRunner` owns background workers. Workers communicate with the UI only through Qt signals. Cancellation remains cooperative because native Paddle and llama.cpp calls cannot always be interrupted immediately. Application shutdown cancels tokens, stops llama.cpp, then briefly joins managed workers.

## Process lifecycle

`InstanceCoordinator` exclusively owns the per-user process lock and private local activation
channel. Later launches send a bounded `ping` or `show-settings` command and exit; they never
construct OCR or translation engines. Desktop and Start Menu shortcuts explicitly request the
settings window, while the Windows sign-in command has no activation flag and remains silent.

Window activation is an application command handled by `Controller`. It cancels an active capture
overlay before presenting settings, and it never reloads an already visible settings form, so
unsaved edits survive repeated shortcut launches.

## Configuration

Configuration migrations are sequential and normalize every persisted field. Invalid JSON is moved to a timestamped `config.corrupt-*` file and safe defaults are loaded. A configuration created by a newer application version is rejected rather than silently downgraded.

## Build and release

`screen_translator/version.py` is the version source. Build scripts pass it to both Inno Setup definitions. Release builds must run tests before PyInstaller and must use a dedicated build environment produced from the lock file.

The incremental updater is valid only for application-code and UI-resource changes. Python, Qt, Paddle, CUDA, llama.cpp, or packaging-layout changes require the full installer.

`installer.common.iss` owns product identity, platform requirements, and shared version defaults. Full installers support per-user installation, repair, upgrade, silent deployment, and optional cleanup of application data. Incremental installers require a registered full installation, enforce a minimum base version, refuse downgrades, and replace only the launcher and UI assets. They use Restart Manager instead of scheduling per-user replacements at reboot.

Every release package has a sibling `*.manifest.json` containing the version, package type, platform boundary, size, and SHA-256. `scripts/release_manifest.py` writes the manifest atomically and immediately verifies it. Production builds should pass an Inno Setup signing tool name to the build script; an unsigned package is a development artifact, not a trusted public release.
