# v2.4.1 — Faster startup

## What's changed

- **About 3× faster startup on Windows:** The release is now a folder build
  instead of a single-file EXE. It no longer unpacks 80 MB into a temporary
  folder on every launch, so the window appears in about 2 seconds instead of
  about 6.
- **Smaller packages:** UPX compression is disabled and unused Qt modules
  (Multimedia/FFmpeg, WebEngine, QML/Quick, PDF, Charts, 3D) are no longer
  bundled.
- **Faster source launch:** `start.bat`/`start.sh` reuse a ready virtualenv
  without searching all Python installations and check required packages in a
  single Python process (about 2.5 → 1 second).

## Validation

- All **110 regression tests passed**, including 20 Qt UI tests.
- Built the Windows folder executable and passed its startup/rendering smoke
  test across all eight pages using the native Windows Qt platform.

## Downloads

Choose the Windows ZIP, Linux executable or macOS ZIP below.
On Windows, unzip `Llama.cpp-Build-Assistant-Windows.zip` and start
`Llama.cpp-Build-Assistant-Windows.exe` inside the folder; keep the EXE together
with its folder. On Linux, mark the downloaded executable as executable with
`chmod +x`.
