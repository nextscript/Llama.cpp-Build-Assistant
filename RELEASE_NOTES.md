# v2.3.9 — Qt GUI migration

## What's changed

- **PySide6 / Qt 6 + Fluent Widgets:** Replace the main CustomTkinter/Tk GUI while
  retaining the dark palette, 150-pixel sidebar, eight-page navigation, cards and
  1600 × 1024 initial window size. The existing build backend and scripts are reused.
- **Background work and native layouts:** Use Qt worker threads and queued signals
  for builds, checks, Git queries, downloads and larger file operations. Reuse pages
  through `QStackedWidget` and remove the Tk resize-freeze and UI-queue mechanisms.
- **Build logs and management:** Batch live output in a read-only `QPlainTextEdit`
  capped at 5,000 lines. Use searchable Qt selectors and native tables for sources,
  profiles and history, with Qt editors, progress dialogs and file pickers.
- **Settings compatibility:** Keep existing JSON settings and add saved window
  geometry, maximized state and build/log splitter positions. Serialize settings
  writes and ignore stale results from background branch queries.
- **Application updater:** Verify HTTPS, stage downloads before replacement,
  roll back replacement errors and preserve runtime data directories.
- **Packaging and dependencies:** Update launchers and PyInstaller for Qt platform
  plugins, Fluent resources and existing icons. Source launches require Python
  **3.10+**. CustomTkinter is no longer a production dependency.

## Validation

- **110 regression tests passed**, including Qt thread delivery, build success and
  failure handling, source/profile CRUD, settings persistence and updater staging.
- All eight pages rendered with the native Windows Qt platform at **100%, 125%,
  150%, 175% and 200%** scaling.
- Real hardware/dependency checks completed while processing 50,000 synthetic log
  lines and programmatic page/move/resize operations; the display retained 5,000 lines.
- The windowed Windows executable was built and passed its startup/rendering smoke
  test with `qwindows.dll` available and no Tk imports.

Full interactive drag/snap/multi-monitor acceptance, real compiler builds,
dependency installation, a live update/restart and native Linux/macOS package
validation remain open. The original GUI is retained as `legacy_app.py` for
comparison and is excluded from the executable. See the
[migration and acceptance report](docs/qt-migration.md).

## Downloads

Choose the Windows executable, Linux executable or macOS ZIP below.
On Linux, mark the downloaded executable as executable with `chmod +x`.
