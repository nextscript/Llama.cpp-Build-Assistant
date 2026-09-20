# Release builds

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

- Windows: `Llama.cpp-Build-Assistant-Windows.exe`
- Linux: `Llama.cpp-Build-Assistant-Linux` (run `chmod +x` after download)
- macOS: `Llama.cpp-Build-Assistant-macOS.zip` containing the `.app`

The macOS build uses the architecture of the `macos-latest` runner.
Builds are not code-signed or notarized. Linux builds target the libraries
available on the Ubuntu runner, not every older Linux distribution.

`scripts/prepare_icons.py` converts `icon.png` into ICO, ICNS and PNG files.
`logo.png`, `icon.png`, `VERSION` and both build scripts are bundled.
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
