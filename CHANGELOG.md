# Changelog

All notable user-visible changes are recorded here. Versions follow semantic versioning.

## Unreleased

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
