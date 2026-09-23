# Changelog

All notable user-visible changes are recorded here. Versions follow semantic versioning.

## 0.8.0

### Capture

- Releasing the mouse now enters an adjustable state instead of translating immediately. The eight
  corner and edge handles are draggable, arrow keys nudge by 1 px and Shift+arrow by 10, Return
  confirms and R starts over. Set `capture_confirm_on_release` to restore the old gesture.
- A selection below 12 × 12 says so and stays adjustable. It used to destroy the whole session and
  send you back to the hotkey.
- A failed capture keeps the overlay and your framing on screen, and Return retries the same
  screenshot without grabbing it again. The failure used to tear both down and report through a
  tray balloon Windows can suppress.
- "Esc 取消" no longer disappears while the model runs, and the capsule counts the seconds spent —
  a cold start can take most of a minute with nothing else to show for it.
- Right-clicking a result offers copy translation, copy image, save image, retranslate, and swap
  languages and retranslate. The only entry before swapped languages for the *next* capture.
- A click the overlay cannot act on now says why instead of doing nothing.
- The status capsule is drawn once, on the screen holding the cursor, and the 10 Hz repaint stops
  once a result is on screen.

### Setting up

- A new installation is told what is missing and taken to the control that fixes it, rather than
  getting a tray balloon and whichever settings tab was last open. The download size is named
  before the button is pressed.
- A login launch stays in the tray. The registry Run entry now passes `--autostart`, so the
  application no longer infers the reason it was started from whether the models are ready.
- Pair two devices with a six-digit code: pick the host from the Tailscale device list — which
  shows its name, system, whether it is online and whether the connection is direct — and type the
  code shown on it. No 43-character secret is read off a screen. Each device gets its own secret,
  so revoking one does not disturb the others.
- Pasting a secret manually still works, for a host that has not been updated yet.

### Appearance

- The interface is rebuilt in Apple's current design language: a light grey canvas with white
  rounded cards, hairline separators, system blue where revolutionary red used to be, and Segoe UI
  Variable in place of Arial Black. Red now means danger and nothing else.
- Dark mode. The application follows the Windows per-application appearance setting, decided at
  start-up.
- The capture overlay's status bar is genuine frosted glass: the screenshot behind it is frozen, so
  it can be blurred and composited rather than faked with a texture. It is the only place in the
  application where that is possible.
- Windows 11 draws the settings window on the Mica material. Windows 10 and older Windows 11 get an
  opaque window instead, with nothing else changed.
- Every disabled control keeps its reason, and the focus ring no longer shifts a control by a pixel
  when it appears.
- Each settings tab now scrolls on its own. The text page's Translate button used to sit below the
  fold at the default window size, because a single scroll area gave every tab the longest page's
  height; the capture page also carried a large stretch of empty space for the same reason.
- Scrolling the settings page no longer changes a dropdown or the listen port on the way past. The
  selection changes by clicking and picking from the list; the list itself still scrolls once it is
  open, and the page still scrolls when the cursor is over a dropdown.
- Headings no longer ask for a font weight Chinese fonts do not have, which was making them render
  blurry at 100% scaling.
- A new application icon: the 译 character on a rounded blue tile. The old mark carried a red
  field, a black diagonal, a yellow disc and four crop brackets, which at the 16-pixel size the
  notification area actually shows was a smudge. Each of the nine icon sizes is now drawn for its
  own pixel count rather than shrunk from one large picture, so the character stays readable down
  to 24 pixels.
- Installing or updating now tells Explorer the icon may have changed, so the taskbar and existing
  shortcuts stop showing the previous one without a sign-out. The v0.5.1 notes said this already
  happened; it did not.

### Reliability and compatibility

- The remote protocol negotiates a version instead of demanding equality, so a v0.7.0 host and a
  newer client keep working while machines are updated one at a time.
- Disabled controls explain themselves. Every disabled button now carries the reason in its
  tooltip.
- Saving settings confirms on every tab. The confirmation used to be written into a label that
  only exists on one of the three.
- Translating text with no model downloaded is refused with an explanation, instead of running far
  enough to fail and showing an absolute file path as the error.
- Fixed a Tailscale connection being reported as relayed when it was direct.
- Configuration migrates to version 5. Migration is additive; a version 5 file is still refused by
  older builds.
- A configuration written by a newer version now says so. It was already refused, correctly, but the
  refusal escaped as an unhandled error and the application simply never appeared — no window and no
  message. You now get a dialog naming both versions, and your settings file is left untouched.
- A configuration whose version number is damaged is repaired like any other corrupt file instead of
  stopping the application.

## 0.7.0

- Add cross-device translation over Tailscale: one device captures and renders, another runs OCR
  and the translation model. Only the cropped selection is uploaded and only text comes back, so
  the result is composited with the capturing device's own DPI and fonts.
- Introduce a `Backend` boundary. Local and remote engines are selected once at composition time;
  the capture pipeline, the text workspace and the overlay are unchanged in either mode.
- Add a client edition (`ScreenTranslatorClient.spec`, `scripts/build_client.ps1`,
  `installer.client.iss`) that ships no PaddleOCR, CUDA or llama.cpp. It reuses the shared
  installer script, so upgrade, downgrade protection and uninstall behave identically, and it
  refuses to install beside the full edition because both share the per-user configuration and
  single-instance lock.
- Serve remote requests through the existing single inference slot: a local capture preempts
  remote and manual work, and preemptable work is now tracked as a set so several remote requests
  can be in flight without cancelling each other.
- Bind the host service only to a Tailscale address, never `0.0.0.0`, and require both a tailnet
  peer address (optionally an explicit device allow-list) and a shared secret. An unresolvable
  address stops the service with an explanation instead of listening more widely.
- Cancel remote work by closing the connection: the host heartbeats every 0.5 s during inference,
  and a failed write cancels the token, so pressing Esc stops the model on the other machine.
- Release manifests gain an `edition` field (`full` or `client`); `schema_version` is now 2.
- Configuration migrates to version 4 with the cross-device fields. Existing single-device
  installations are unaffected, and a version 4 file is still refused by older builds.

## 0.6.0

- Add a text translation workspace: type or paste text, translate it locally, cancel a running
  translation, copy the result, and clear the fields.
- Reorganize the main window into 截图翻译 / 文本翻译 / 系统设置 workspaces while keeping the
  tray menu, single-instance activation, close-to-tray, and exit behaviour unchanged.
- Preserve paragraphs, indentation, list markers, and numbering deterministically by segmenting
  the input outside the model request and restoring the framing verbatim.
- Serialize screenshot and text translation through one inference slot; starting a capture cancels
  an in-flight text translation and text requests are refused while a capture runs.
- Resolve released LoRA adapters through the shared registry and load them with llama.cpp
  `--lora-scaled`, rejecting adapters that are experimental, mismatched, corrupted, or not GGUF.
  No adapter ships yet: none has passed the project release gate.
- Add `scripts/training/check_release_gate.py` so the declared release gate is machine-checked
  against evaluation reports instead of read by hand.

- Add a bottom-positioned Exit action to the tray menu.
- Reuse the settings exit confirmation and centralized resource cleanup path.

## 0.5.2

- Replace the flickering native selection cursor with a high-contrast cursor painted by the capture overlay.
- Keep the cursor visible before dragging and synchronize its global position across multi-monitor overlays.
- Use explicit wait and arrow cursors for processing and result views.

## 0.5.1

- Keep wrapped numbered items in one semantic block across normal OCR line-height variation,
  preventing duplicated neighboring translations and abnormally small rendered text.
- Validate structured translations for cross-block duplication, numbering, and extreme length;
  repair list markers deterministically and retry only suspicious blocks with the selected model.
- Warm PaddleOCR in the background without loading Qwen at tray startup.
- Run 4B and 8B long-document batches through two bounded llama.cpp slots after a measured
  24.7% single-to-dual-slot improvement; keep 14B on one slot.
- Expand translated blocks only into free space in their own column and preserve a readable
  minimum font size before using a high-opacity backing panel.
- Point Windows shortcuts directly at the packaged multi-resolution ICO and notify Explorer after
  install or update, avoiding stale large desktop icons when the EXE is replaced in place.

## 0.4.8

- Rebuild the application, tray, shortcut, executable, and installer icon as one multi-resolution
  constructivist identity.
- Add a canonical SVG master and deterministic PNG/ICO generation script.
- Add small-size icon regression checks for 16–256 pixel Windows surfaces.

## 0.4.7

- Restyle Settings, the capture overlay, switches, menus, icons, and the tray mark with a modern
  constructivist system of red, black, warm paper, yellow accents, hard borders, and geometric forms.
- Preserve desktop accessibility, keyboard focus, concise labels, and 44-pixel interaction targets.

## 0.4.6

- Remove repeated descriptions, technical model suffixes, duplicate language previews, and
  instructional footer copy from Settings while retaining labels and operational feedback.
- Move secondary model details into tooltips and tighten the settings window layout.

## 0.4.5

- Open and focus the existing settings window from desktop and Start Menu shortcuts without
  starting a duplicate application instance.
- Keep Windows sign-in startup silent while forwarding explicit activation through a private
  per-user local channel.
- Reduce the tray menu to Settings and the current language pair, and move application exit to
  the settings footer.
- Update existing shortcuts through the incremental installer without touching local models.

## 0.4.4

- Redesign the settings window with an iOS 18-inspired grouped layout, system-blue hierarchy,
  accessible contrast, lightweight glass surfaces, and responsive long-text behavior.
- Add keyboard-accessible animated switches, consistent SVG action icons, and a refreshed tray icon.
- Restyle the capture overlay with a lighter glass status bar, clearer selection handles, and
  platform-consistent state colors.
- Add a persisted UI design specification and an offscreen preview renderer for repeatable review.

## 0.4.3

- Add a Qwen3-4B-Instruct-2507 Q8_0 fast mode alongside the existing 8B and 14B modes.
- Route Japanese and Korean from 4B, and Korean from 8B, to an installed 14B model based on held-out quality results.
- Pass the permanent 300-record quality gate with all three product modes while preserving strict JSON, ID coverage, block alignment, and zero-repeat requirements.
- Preserve existing models during upgrades and include the exact published 4B artifact checksum in the model manifest.

## 0.4.2

- Label the existing 8B and 14B backends as balanced and high-quality modes.
- Automatically retry failed 8B translations with an installed 14B model.
- Split long documents at headings and numbered items instead of arbitrary
  four-line boundaries, preventing cross-block drift and repeated paragraphs.
- Use smaller model requests for long documents while preserving the low-overhead
  batching path for normal screenshots.

## 0.4.1

- Add selectable Qwen3-8B and Qwen3-14B Q5_K_M translation backends.
- Preserve installed translation models when downloading or resetting another model.
- Add a reusable offline image benchmark for cold and warm pipeline measurements.

## 0.4.0

- Refactor application orchestration into a dedicated controller.
- Add explicit capture-session states and managed background tasks.
- Add replaceable OCR, translation, and rendering contracts.
- Harden configuration migration and recovery from corrupted JSON.
- Use one Python version source for application and installer builds.
- Unify full and incremental installer metadata and enforce upgrade boundaries.
- Add per-user installation, desktop shortcut, downgrade protection, optional data purge, and release manifests with SHA-256 verification.

## 0.3.0

- Redesign the settings and capture overlay UI.
- Add a small incremental Windows update package for application-code changes.
- Persist language direction changes immediately and expose swapping from the result view.
# 0.5.0

- Added a shared, application-neutral model registry with stable IDs, role-based resolution, root confinement, size/hash validation, dependencies, and legacy flat-manifest compatibility.
- Moved reusable inference, OCR, and Hugging Face base weights to `D:\AI\Models`; moved mutable Screen Translator training history to `D:\AI\Training\screen-translator` without duplicating payloads.
- Added a journaled same-volume migration tool with dry-run, lock, collision detection, metadata rewrite, resumability, and rollback.
- Made OCR and translation engines resolve physical paths through the registry; redownload now quarantines only the selected translation artifact.
- Added workspace-wide model policy, agent rules, project model requirements, and environment-overridable training path resolution.
- Ensured installers and uninstallers leave shared model and training roots untouched.
