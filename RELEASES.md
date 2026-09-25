# Release builds

## v2.4.2

- Keep Windows (Visual Studio) builds usable when only llama.cpp's own unit
  tests fail to compile: if every MSBuild error belongs to a project under
  `build	ests` and `llama-server.exe` was built, the tests are reported as
  skipped and the build finishes successfully. Errors in any other target
  still fail the build. Fixes CUDA builds of llama.cpp `4b1a27fa0` with
  MSVC 19.51, where `tests/test-batch-alloc.cpp` fails with C2131.
- Pass all 110 regression tests and the Windows folder-build smoke test.

## v2.4.1

- Ship Windows as a folder build (`Llama.cpp-Build-Assistant-Windows.zip`):
  startup drops from about 6 to about 2 seconds because the EXE no longer
  unpacks itself on every launch.
- Disable UPX and exclude unused Qt modules (Multimedia/FFmpeg, WebEngine,
  QML/Quick, PDF, Charts, 3D) from all platform packages.
- Reuse a ready virtualenv in the source bootstrap without interpreter
  discovery and check required packages in one Python process.
- Pass all 110 regression tests and the Windows folder-build smoke test.

## v2.4.0

- Enable dark native Windows title bars for the main window and dialogs.
- Request Qt's dark color scheme and apply the native Windows setting when
  top-level windows are shown. Unsupported Windows versions keep their default
  title-bar appearance.
- Verify the native dark-mode setting for main windows and dialogs, pass all
  110 regression tests, and validate the Windows EXE across all eight pages.

## v2.3.9

- Replace the main CustomTkinter/Tk GUI with PySide6 / Qt 6 + Fluent Widgets,
  retaining the existing dark palette, sidebar, page order and card layout.
- Use persistent Qt pages, queued worker signals and native layouts for
  background builds/checks and window resizing. Batch live logs and cap the
  display at 5,000 lines.
- Preserve the existing build backend, source/profile management, searchable
  branch selection, version checks and build-history functionality.
- Save window geometry, maximized state and the build/log splitter alongside
  existing settings, with serialized writes.
- Stage application-update downloads, verify HTTPS and preserve runtime data.
- Update dependency bootstrapping and PyInstaller packaging for Qt and Fluent
  resources. Source launches require Python 3.10+.
- Pass 110 regression tests, native Windows DPI rendering checks at 100–200%,
  real hardware/dependency checks under log load, and the Windows EXE smoke test.

Interactive drag/snap/multi-monitor acceptance, real compiler builds,
installation/update workflows and native Linux/macOS packages still require
validation. See [the migration report](docs/qt-migration.md). The original GUI
is retained as an optional comparison copy and excluded from releases.

## v2.3.8

- Prevent deep Windows/Vulkan output paths from reaching MSBuild/FileTracker
  failures with path-budget checks before cloning or cleaning builds (#6).
- Enable detected AVX-VNNI/BMI2 features in native Windows/MSVC CPU, CUDA and
  Vulkan builds, respecting Windows AVX state support and explicit profile
  overrides (#5). Portable and other compiler flag paths remain unchanged.
- Persist CPU-target and parallel-job choices and clarify native CPU hints.
- Add regression coverage; all 82 tests pass.

Thank you, DaWaste ([@DaWasteh](https://github.com/DaWasteh)), for the detailed
reports, reproduction steps, build evidence and tested workarounds for both issues!

## v2.3.7

- Persist and restore the main window position, including secondary monitors.
- Center source and profile dialogs over the main application window.

## v2.3.6

- Add asynchronous remote branch discovery for custom build sources using
  `git ls-remote`, including default-branch detection, refresh, manual refs,
  validation, and host-independent error handling.
- Add a fast searchable branch selector that remains responsive with large
  repositories and launches background Git queries without a console window
  on Windows.
- Refine the Build Configuration layout with a compact two-column version
  status, reordered profile/options/output sections, and clearer dashboard
  recommendation styling.
- Disable the npm web UI option when the selected build profile explicitly
  sets `LLAMA_BUILD_UI=OFF`.

## Release automation

Push a version tag (for example `v1.0.0`) to run the release workflow.
Windows, Linux and macOS build in parallel. Each job uploads its artifact
and attaches it to the GitHub Release for that tag.

- Windows: `Llama.cpp-Build-Assistant-Windows.zip` (unzip, then start `Llama.cpp-Build-Assistant-Windows.exe` inside the folder; the folder build starts about three times faster than a single-file EXE)
- Linux: `Llama.cpp-Build-Assistant-Linux` (run `chmod +x` after download)
- macOS: `Llama.cpp-Build-Assistant-macOS.zip` containing the `.app`

The macOS build uses the architecture of the `macos-latest` runner.
Builds are not code-signed or notarized. Linux builds target the libraries
available on the Ubuntu runner, not every older Linux distribution.

`scripts/prepare_icons.py` converts `icon.png` into ICO, ICNS and PNG files.
`logo.png`, `logo_big.png`, `icon.png`, `VERSION` and both build scripts are bundled.
Qt platform plugins and Fluent widget resources are collected by PyInstaller;
the Windows smoke test verifies `qwindows.dll` and renders all eight pages.
The source/profile JSON files are bundled as templates. Missing configuration
files are created from these templates at launch. On the first launch of this
version, empty source/profile files from older builds are backed up as
`*.before-defaults.json` and populated once. Afterwards even empty lists are
preserved, so deleting all entries remains possible. Existing nonempty files
are preserved. Runtime history and hardware reports
are initialized separately and are not published.

Packaged apps keep writable data outside the executable or temporary bundle:

- Windows: `%LOCALAPPDATA%/Llama.cpp-Build-Assistant`
- Linux: `$XDG_DATA_HOME/Llama.cpp-Build-Assistant` (default `~/.local/share`)
- macOS: `~/Library/Application Support/Llama.cpp-Build-Assistant`

Source launches continue using the project directory. `start.bat` exits after
starting a hidden PowerShell helper, which launches Python without a console.
Bootstrap and launch errors are recorded in `logs/`.
`start.sh` detaches the GUI using `nohup` with all standard streams redirected.
An existing interactive terminal remains under the user's control and can be
closed without ending the GUI; closing an automatically opened terminal window
also depends on that terminal's exit preferences. A batch launch may briefly
flash CMD; the packaged Windows executable starts without CMD or PowerShell.
