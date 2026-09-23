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
| Composition | `app`, `backend`, `controller` | everything |
| UI | `settings`, `remote_settings`, `overlay`, `text_translation_page`, `tray`, `theme`, `widgets.*`, `feedback.sinks` | flow, domain, design |
| Design | `design.*` | **nothing from this application** |
| Flow | `backend_service`, `languages`, `config_store`, `downloads`, `hotkeys`, `manual_translation`, `inference`, `tasks`, `capture.pipeline`, `capture.session_controller`, `remote.host`, `feedback.center` | contracts, domain |
| Contracts | `contracts`, `capabilities`, `navigation`, `capture.view`, `feedback.confirm` | domain |
| Domain | `core`, `session`, `download_session`, `layout`, `text_segmenter`, `translation_quality`, `onboarding`, `capture.selection`, `capture.commands`, `feedback.notices`, `remote.protocol`, `remote.access`, `remote.pairing` | stdlib only |
| Infrastructure | `ocr_engine`, `translation_engine`, `models`, `model_registry`, `graphics`, `native`, `remote.client`, `remote.service`, `remote.tailnet` | contracts, domain |

`contracts` mentions Qt only inside `TYPE_CHECKING`, and the domain layer imports nothing from the application. That is what lets the host service and a client build without the model runtimes import the same modules.

`design` sits beside the layer table rather than inside it: it imports
PySide6 and nothing else from this project, which a test enforces. That
makes a circular import structurally impossible and lets the whole token
layer be exercised without an application.

`Controller` is an assembly root and three commands (`toggle`, `activate_settings`, `quit`). It
owns nothing; everything it builds owns itself. This is deliberate and load-bearing: when the
controller held the capture, the engines, the tray, the language pair and the download queue,
every test for any of them had to build a namespace impersonating `self` and call unbound methods
on it, which meant each test encoded its own idea of what the controller looked like. No test
does that now.

Anything that shows the language pair, readiness or progress is *told*, through a Qt signal, by
the object that owns the fact. Nothing polls the controller for it.

## Appearance

Three token layers. `design/primitives.py` holds raw colour and is **the
only file in the repository allowed to contain a hex value**;
`design/semantic.py` names roles; `design/components.py` answers
per-component questions as functions. The last is a function rather than
a table for one specific reason: QSS cannot reach a widget that paints
itself, so `ToggleSwitch.paintEvent` and the stylesheet generator have to
be able to read the same numbers.

The stylesheet is generated, which makes three properties testable
rather than aspirational: every hex in the output is a value the theme
holds, `border-radius` is emitted from a token instead of repeated, and
no `:focus` rule changes geometry — the resting state already declares
the focus border width, so focus alters only the colour.

Two surfaces are outside the theme, and deliberately:

- **The capture overlay** has a pinned sub-palette. It paints on an
  unknown screenshot, so the system appearance says nothing about whether
  the region the user grabbed is light or dark. Pinned means pinned
  against light and dark, not against the visual direction.
- **`graphics.py`** is outside the token system entirely. Its two inks
  are chosen per image from measured background luminance and
  `FONT_FAMILIES` maps a language to a system font. Under a theme,
  changing the application's appearance would change the pixels of a
  translated picture the user saved.
  `test_graphics_never_imports_the_design_package` keeps that separation
  from being removed by a later tidy-up.

The visual direction is Liquid-Glass-informed rather than Liquid Glass:
QSS has no background filter, `QGraphicsBlurEffect` cannot sample what is
behind a widget, and SF Pro cannot be redistributed. The one place real
glass is achievable is the capture overlay's status bar, because it sits
on a frozen `QImage`; the blur is cached on the `ScreenShot` rather than
computed in `paintEvent`, which runs ten times a second while the model
works. Window-level translucency is Windows 11 Mica, applied through
`DwmSetWindowAttribute` and silently absent where the attribute is
unknown. `design-system/screen-translator/decisions/` records all of
this; ADR 0002 and ADR 0005 are the two to read first.

Dark mode follows `AppsUseLightTheme`, read once at start-up. It ships
with a `QPalette`, which is not optional: a stylesheet does not reach
`QMessageBox`, `QToolTip`, spin-box arrows, the native file dialog or
disabled text.

## Session lifecycle

The valid capture lifecycle is:

```text
IDLE → SELECTING ⇄ ADJUSTING → PROCESSING → RESULT → IDLE
                                    ↓   ↘
                                    ↓    FAILED → PROCESSING (retry)
                                CANCELLING → IDLE
```

`ADJUSTING` is where a released selection waits to be confirmed, so releasing the mouse is no
longer the point of no return. `FAILED` is why a failure keeps the overlay and the framing on
screen: the old path destroyed both and then reported through a tray balloon that Windows is free
to suppress, so a user with notifications off lost the result and any trace of the error.

Every background result carries the generation that created it. A result may update application state only when its generation is current. Cancelling invalidates the generation before closing overlays, so late signals cannot affect a newer task.

`CapturePipeline` runs recognise → translate → render and knows nothing about sessions,
generations or signals. Deciding whether a result is still wanted belongs to the caller that owns
the session. The pipeline needs no Qt application, no OpenCV and no controller, which is what makes
it directly testable.

## What the user can do, and why not

`capture.commands.allowed_commands(state, selection, has_result)` is a pure function over the
session state. A command outside the returned set is refused by `CaptureController.handle`, which
returns `False` and stores the sentence from `describe_block`. This is why a click during
processing can no longer look identical to a missed click: silence is not a reachable outcome.

`capture.view.OverlayViewModel` separates `message` (what is happening) from `hint` (what can be
done), and the overlay renders both rows always. They used to share one string, so progress text
overwrote "Esc 取消" exactly when the wait was longest and the way out mattered most.

## Feedback

There are two message surfaces (the in-page banner and the overlay capsule), one fallback (the
tray) and one confirmation primitive. `feedback.notices` is pure standard library: `route()` and
`supersedes()` are functions over a `Notice`, so which surface a message reaches is a
parameterised unit test rather than a property of where the call was written.

**`NoticeCenter` may only be called from the UI thread.** Background workers keep using the
existing pattern — a Qt signal carrying the generation — to get back to it. Without this rule the
feedback layer becomes a new way to mutate widgets from a worker.

A STICKY notice also enters `history()`, so a balloon the system swallowed can still be read when
the window is opened. That replay is the structural answer to a tray that may be silenced.

Flow-layer code never imports `QMessageBox`. The two remaining blocking questions (quit, and
redownload) go through `feedback.confirm.ConfirmationPort`.

## Onboarding

`onboarding.evaluate(config, backend_ready, local_runtime, intent) -> OnboardingPlan` is a pure
function, so first-run behaviour is a regression asset rather than something only observable by
reinstalling. The stage is always derived; the only thing written to disk is
`onboarding_completed`.

`StartupIntent` is read from the command line, not guessed. The registry Run entry passes
`--autostart`, so a login launch stays in the tray even on an installation that cannot translate
yet. Inferring it from "are the models ready" is what opened a window at every login on a machine
the user had not set up.

Every blocking stage carries a `navigation.Destination`, and the settings window resolves it to a
tab, an anchor and a widget to focus. A message that names the problem without the remedy leaves
the reader to hunt through three tabs.

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

### Protocol versions

`PROTOCOL_VERSION` is what a build sends; `SUPPORTED_PROTOCOL_VERSIONS` is what it will also
accept. Both ends previously compared for exact equality, which would have made every version
bump a flag day — a v2 host and a v1 client refusing each other, on machines updated one at a
time. `negotiate()` returns the highest version both speak. A peer advertising something *newer*
is answered at this build's best rather than refused, because the newer side is required to be
able to fall back and refusing it strands the older half of a rolling upgrade. A peer with no
version header at all is v1, which is when the header appeared.

### Pairing

A device claims a per-device secret by posting a six-digit code to `POST /v1/pair/claim`. That is
the only route that runs without a secret, because it is how a secret is obtained; the peer
address check still applies and the body is capped at 512 bytes.

**Why six digits is enough.** The code is not the only thing in the way. An attacker must already
be a member of this tailnet (WireGuard, plus the CGNAT range check in `remote.access`), must hit
the 180-second window while it is open, and gets five attempts before the offer is exhausted —
after which a 60-second lockout applies to that peer address. Blind guessing succeeds with
probability at most 5/10⁶, once, and only from inside the tailnet. A longer code would cost
readability and buy nothing against the threat that remains. This paragraph exists so the next
person does not assume six was chosen by feel.

Every rejected claim receives the same sentence. Distinguishing "wrong code" from "no offer" would
confirm to anyone on the tailnet that this host is currently pairing; distinguishing "expired"
would confirm the code was right. The real reason goes to the host log only.

A client generates a nonce and retries with it after a lost reply; the host returns the identical
grant rather than issuing a second secret that would leave the device holding the wrong one. The
same nonce from a different address costs an attempt like any other bad claim.

There is no `/v1/pair/status`. The host's own UI reads the broker in-process; an endpoint would
only add something for a stranger to probe.

`AccessPolicy.device_secrets` holds one secret per paired device and compares every candidate
without short-circuiting. Revoking a device is removing one entry, rather than rotating the shared
secret and re-pairing everything else. The shared secret keeps working, and the manual paste field
stays in the window, because a v0.7.0 host has no pairing route at all.

Per-device secrets are swapped into the running policy rather than counted in the listener's
restart signature: restarting the instant a device pairs would drop the connection that just
paired.

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

Version 5 adds every field the interaction refactor needs at once — `onboarding_completed`,
`capture_confirm_on_release`, `remote_host_id`, `remote_host_label`, `remote_protocol`,
`paired_devices`, `pairing_strict_peers` — even though they arrive over several releases. Bumping
once per feature would mean a config written by an intermediate version is rejected by a
reinstalled earlier one as "created by a newer version". One bump, lazy fields, and the shape of
the file stays stable across the whole refactor.

`Config.load` is `cls(**_normalize(data))` and performs no nested deserialisation, so
`paired_devices` needs `normalize_paired_devices` explicitly; without it the field would hold
plain dicts and every reader would have to guess which it got.

`ConfigStore` is the only writer. `config` remains a read-only view, and the store announces
changes, so nothing reloads a whole form to stay in step — which is how swapping the language pair
used to discard every unsaved edit in the window.

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
