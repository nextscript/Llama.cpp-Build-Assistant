# Qt migration and verification

`app.py` now starts PySide6/Qt 6. `ui/main_window.py` owns a native `QMainWindow` and eight persistent pages in a `QStackedWidget`. Fluent push buttons, primary buttons, line edits and checkboxes are combined with centrally styled Qt cards, tables and searchable combo boxes.

## Preserved interface

The audited navigation is **Dashboard → System Check → Dependencies → Build → History → Sources → Profiles → Update**. The repository did not have a separate Settings page: output-directory, CPU-target and job settings remain on Build. No new navigation entry was inserted.

The shell retains the 1600 × 1024 initial size, 1200 × 800 minimum, 150 logical-pixel sidebar, 64-pixel header, dark palette, blue primary buttons, existing logos, cards and side-by-side build configuration/log. All theme rules live in `ui/theme.py`. Qt's native title bar preserves normal Windows move, resize, maximize and snap behavior.

| Previous functionality | Qt implementation | Verification |
| --- | --- | --- |
| Dashboard and hardware recommendation | `MainWindow.run_hardware_check`, existing `hardware_check` | Automated mock and real local hardware/dependency run |
| System report and JSON export | Existing report formatting in `ui/reports.py`, `QFileDialog`, worker export | Report rendering tested; native file-picker interaction remains manual |
| Dependency check/install/manual guide | Existing checker/installer called by `Tasks`; progress dialog | Checker run locally; installer integration tested with mocks, no real packages installed |
| Source/profile selection and build options | `ui/pages/build_page.py` | Backend argument forwarding and npm-disable override tested |
| Source add/edit/delete | `SourceDialog`, existing source manager | CRUD integration, pinned commit/fetch ref, stale branch responses tested |
| Remote branches/default/custom branch | Editable `QComboBox`, contains-filter `QCompleter`, worker query | Branch selection and stale-result rejection tested |
| Profile add/edit/delete, arbitrary CMake flags | `ProfileDialog`, plus/minus flag rows, existing profile manager | CRUD integration tested; unknown profile fields remain untouched |
| Build/output directory | Existing `builder.run_build` via `ui/workers/build_worker.py` | Success, failure, exception, output validation and result recording tested with mocked compiler |
| Build version/changes | Existing `source_version.check_source_version` and Qt dialog | Rapid selection changes coalesce; latest-result delivery tested |
| Build history | Native read-only table; double-click opens full result | Backend history tests plus persistent navigation checks |
| Application update | Worker service plus Qt progress dialog; frozen builds open releases as before | Check/error paths, staging, failed download and path validation tested; no live application update applied |
| Settings/window state | Existing JSON file plus `qt_geometry` and `qt_build_splitter` | Close/reopen test preserves unrelated settings; screen-boundary clamping respected |
| Packaging | Existing release workflow updated to Qt and Fluent resources | Local Windows one-file build; frozen smoke test |

Existing builder, config, source/profile managers, hardware/dependency modules and build scripts are reused. `python_manager.py` only changes GUI dependency detection and the minimum Python version (3.10 for Qt 6.8+).

## Thread and lifecycle behavior

- Worker `QThread` instances deliver results, errors and log batches to QObject slots with queued connections. No worker accesses widgets.
- Builds, hardware checks, dependency checks/installations, remote branches, source versions, update downloads, history/config reloads, directory validation and report exports run off the GUI thread.
- Source-version requests are serialized and intermediate selection requests are coalesced. Closed source dialogs ignore late replies.
- Log output is batched before Qt delivery. `QPlainTextEdit` retains at most 5,000 blocks.
- Pages are created once. There is no Tk queue, `after()` loop, resize freeze or move-event file/network work in the active GUI.
- Closing waits asynchronously for outstanding read tasks and settings persistence. Active builds/installations/updates must finish first, so no running QThread is destroyed.
- Settings writes use a lock around the existing read/modify/write operation.
- The updater uses verified HTTPS, stages downloads before replacement, rolls back replacement errors and preserves runtime data directories.

## Reproduce automated checks

```powershell
python -m pip install -r requirements.txt pytest pyinstaller
python -m pytest -p no:cacheprovider -o addopts= -q
python scripts/check_qt_dpi.py
python scripts/check_qt_responsiveness.py
python scripts/check_frozen_qt.py dist/Llama.cpp-Build-Assistant-Windows.exe
```

The DPI probe uses the native Windows Qt platform at factors 1, 1.25, 1.5, 1.75 and 2. It renders all eight pages and writes images/reports under `build/qt-dpi-*`. It verifies that Tk is not imported and `qwindows.dll` is available. This tests rendering, not physical movement between monitors.

`app.py --smoke-test <output-directory>` and the equivalent executable argument render pages without starting network checks/builds or saving window settings. The frozen test sets `LOCALAPPDATA` to an isolated directory under `build/`.

Local results: **110 tests passed**. A native Windows responsiveness probe with real hardware and dependency checks, 50,000 synthetic log lines, repeated page switches and programmatic move/resize completed in 7.11 seconds. It retained 5,000 log blocks and serviced 670 timer ticks; p95 event gap was 11.0 ms, maximum 60.5 ms. These measurements were taken on a hidden test window and do not measure compositor/drag smoothness.

## Remaining release acceptance

Do not interpret the automated checks as full interactive acceptance. Still verify on the target machines:

- Real successful CPU/GPU builds through the GUI and a real compiler failure; move/resize and switch pages during those builds.
- Interactive window dragging, Aero Snap, minimize/maximize/restore, physical multi-monitor transitions, and file dialogs at the requested Windows DPI settings.
- Source/profile dialogs with production repositories and existing personal configurations; visual comparison against the original on the same display.
- A real dependency installation and an end-to-end update/restart on a disposable installation.
- Linux/macOS packaged binaries in their native environments.

`legacy_app.py` is the unmodified original GUI kept solely for comparison until those acceptance checks establish parity. It is never imported by the Qt application and is excluded from the executable. For a comparison run, install `requirements-legacy.txt` and run `python legacy_app.py`. Remove that reference and its optional requirements only after acceptance; the production requirements already contain no CustomTkinter.

## Dependencies

The selected package is [PySide6-Fluent-Widgets](https://qfluentwidgets.com/pages/install/), imported as `qfluentwidgets`. Its upstream [license](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/PySide6/LICENSE) is GPLv3 with a commercial licensing option. The repository's existing license metadata is unchanged; third-party licensing is listed here explicitly.

Qt references: [queued cross-thread delivery](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html), [bounded plain-text logs](https://doc.qt.io/qtforpython-6.10/PySide6/QtWidgets/QPlainTextEdit.html).
