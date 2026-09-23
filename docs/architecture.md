# Screen Translator architecture

## Direction

Screen Translator is a modular monolith: one Windows desktop application whose parts are separated by interfaces rather than by processes. Cross-device translation does not change that. There is no service tier and no message broker; there is one optional HTTP listener inside the same process, reached through the same contracts the local engines implement.

```text
Qt UI / overlays
       ↓
application controller + capture session + task runner
       ↓
Backend  →  OCR / translation / rendering contracts
       ↓
local: PaddleOCR, llama.cpp, OpenCV, Win32, model storage
remote: tailnet transport to another installation
```

The UI may issue commands and render state, but must not perform OCR, translation, network, or process work directly. Infrastructure implementations must not mutate Qt widgets from background threads.

## Dependency direction

| Layer | Modules | May import |
| --- | --- | --- |
| Composition | `app`, `backend` | everything |
| UI | `settings`, `remote_settings`, `overlay`, `text_translation_page`, `theme`, `ui_components` | flow, domain |
| Flow | `controller`, `session`, `manual_translation`, `inference`, `tasks`, `remote.host` | contracts, domain |
| Contracts | `contracts`, `capabilities` | domain |
| Domain | `core`, `layout`, `text_segmenter`, `translation_quality`, `remote.protocol`, `remote.access` | stdlib only |
| Infrastructure | `ocr_engine`, `translation_engine`, `models`, `model_registry`, `graphics`, `native`, `remote.client`, `remote.service`, `remote.tailnet` | contracts, domain |

`contracts` mentions Qt only inside `TYPE_CHECKING`, and the domain layer imports nothing from the application. That is what lets the host service and a client build without the model runtimes import the same modules.

## Session lifecycle

The valid capture lifecycle is:

```text
IDLE → SELECTING → PROCESSING → RESULT → IDLE
                    ↓
                CANCELLING → IDLE
```

Every background result carries the generation that created it. A result may update application state only when its generation is current. Cancelling invalidates the generation before closing overlays, so late signals cannot affect a newer task.

## Extension points

- `OcrPort`: image to structured OCR result, plus a cheap `ready()`.
- `TranslationPort`: text blocks to translated blocks, including model lifecycle, plus `ready()`.
- `RendererPort`: translated blocks to a rendered image.
- `Backend`: one OCR engine, one translation engine and their shared readiness. `create_backend` is the only place that decides between them.

New model backends should implement these contracts and be selected during bootstrap. They should not add backend-specific branches to settings or overlay code.

`ready()` is polled from the UI thread on every hotkey press, so it must not block. The local backend answers from a registry read and a few `stat` calls; the remote backend answers from a cached health snapshot that a 15-second background tick refreshes. That tick is also how a client notices a host that was offline at start-up.

GGUF variants are declared in the translation-model catalog. Configuration stores a stable model ID rather than a filename. `ModelRegistry` resolves that ID and each OCR role through the shared repository registry; engines never construct model filenames. Registry paths are relative, root-confined, dependency-aware, and validated by size or full hash. The v0.x flat `manifest.json` remains a read-only compatibility input.

The canonical local repository is `D:\AI\Models`, while mutable Screen Translator datasets, caches, runs, checkpoints, and unqualified adapters live in `D:\AI\Training\screen-translator`. Downloads publish into a model-specific directory and atomically replace the registry. Redownload quarantines only the selected translation artifact. Application upgrades and uninstall never mutate either shared root.

## Cross-device translation

The split is: the capturing device takes the screenshot and renders the result, the host runs OCR
and the translation model. Only the cropped selection goes up, as lossless PNG; only
`{block_id: text}` comes back. Polygons never leave the capturing device, which keeps the downlink
at a few kilobytes and — more importantly — keeps `fitted_text` and `OverlayRenderer` working with
the screen DPI and installed fonts that actually apply.

```text
client                              host (same desktop process)
capture selection  ── PNG ────────▶ OcrPort.recognize
merge_lines                ◀── JSON  OcrResult
TranslationPort.translate ── JSON ─▶ InferenceCoordinator.reserve(REMOTE)
OverlayRenderer.render     ◀── JSON  {block_id: text}
```

Boundaries that are not negotiable:

- **Binding.** The listener binds a Tailscale address or refuses to start. `0.0.0.0` is rejected by
  `resolve_bind_address`, so the port never appears on whatever other network the host is joined to.
- **Authorization.** The tunnel proves traffic came from the tailnet, not that a device was invited.
  `AccessPolicy` therefore requires a tailnet peer address, optionally an explicit allow-list, and a
  shared secret compared with `compare_digest`. A weak or missing secret fails at start-up.
- **Cancellation.** Inference emits no progress for seconds at a time, so the host writes a
  heartbeat every 0.5 s and treats a failed write as a cancellation. Closing the socket is the
  client's cancel signal; this also covers a client that crashed.
- **Privacy.** The host holds requests in memory and logs counts, devices and timings only. The
  existing promise that no screenshot, source text or translation is written to disk applies
  unchanged to remote work.
- **No chaining.** A remote client cannot also be a host. `HostService` refuses the configuration
  rather than letting one screenshot take two hops through an inference slot nobody can reason about.
- **No silent fallback.** An unreachable host is reported. Remote mode never quietly runs the
  models locally, because that would change which machine sees the user's screen.

## Inference arbitration

One llama.cpp server serves both workspaces and every connected device. `InferenceCoordinator`
owns a single slot and is the only sanctioned way to reach `TranslationPort.translate`. Capture
preempts: `Controller.begin` cancels registered preemptable work and marks the capture active, so
manual and remote requests made during a capture are refused rather than queued. Manual and remote
requests are peers, and because several remote requests can arrive at once, preemptable work is a
set of tokens rather than one. A holder keeps the slot for its whole run, which also protects the
fallback path in `TranslationEngine` — it stops the server mid-flight and must never do so while
another caller is streaming.

Remote requests wait up to `SLOT_WAIT` for the slot so a short overlap with the host user queues,
then fail with a readable message rather than stalling the other device.

Model warm-up is the one exception: loading weights can outlast any reasonable slot wait, so
warm-up skips itself when the slot is owned instead of blocking the capture pipeline behind it.

Manual translation never uses `CaptureSession`. It has its own monotonic request ID, its own
cancellation token, and its own signals; results from a superseded request are dropped by both the
use-case controller and the view.

## Released adapters

`models.SUPPORTED_ADAPTERS` maps a base model ID to the adapter released for it and is empty until
an adapter passes the gate in `model-requirements.json`. Resolution goes through the registry and
requires `kind == "adapter"`, `status == "production"`, `format == "gguf"`, the
`translation-adapter` role, a `dependencies` entry naming the active base model, and a size match.
A listed adapter that fails any of these raises; the application never silently falls back to base
weights while claiming a fine-tuned model. Unqualified training output stays in
`D:\AI\Training\screen-translator`.

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

Version 4 adds the cross-device fields. Migration is additive, so an existing single-device installation upgrades with its behaviour unchanged. `core` validates them structurally — URL shape, IP parsing, port range, secret length — while whether an address is on the tailnet is policy and stays in `remote.access`; that separation is what keeps the configuration layer independent of the networking layer. A remote mode without both an address and a secret is repaired to local, because the alternative is an installation that cannot capture at all.

## Build and release

`screen_translator/version.py` is the version source. Build scripts pass it to both Inno Setup definitions. Release builds must run tests before PyInstaller and must use a dedicated build environment produced from the lock file.

The incremental updater is valid only for application-code and UI-resource changes. Python, Qt, Paddle, CUDA, llama.cpp, or packaging-layout changes require the full installer.

Two editions ship from one installer script. `installer.common.iss` switches identity on
`ClientEdition`; `installer.client.iss` is six lines that define it and include `installer.iss`, so
installation, upgrade, downgrade protection and uninstall cannot diverge between them. The client
payload is built by `ScreenTranslatorClient.spec` and gated in `scripts/build_client.ps1` on both a
size ceiling and the absence of any model runtime, because a client that quietly regained a
gigabyte would have no reason to exist. `capabilities` reports the missing runtime at run time so
the application explains itself instead of failing part-way through a capture. Incremental
packages remain full-edition only.

`installer.common.iss` owns product identity, platform requirements, and shared version defaults. Full installers support per-user installation, repair, upgrade, silent deployment, and optional cleanup of application data. Incremental installers require a registered full installation, enforce a minimum base version, refuse downgrades, and replace only the launcher and UI assets. They use Restart Manager instead of scheduling per-user replacements at reboot.

Every release package has a sibling `*.manifest.json` containing the version, package type, platform boundary, size, and SHA-256. `scripts/release_manifest.py` writes the manifest atomically and immediately verifies it. Production builds should pass an Inno Setup signing tool name to the build script; an unsigned package is a development artifact, not a trusted public release.
