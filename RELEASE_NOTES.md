# v2.4.0 — Dark Windows title bars

## What's changed

- **Dark Windows title bars:** Match the main window and dialog title bars to
  the application's existing dark interface.
- **Native theme integration:** Request Qt's dark color scheme and apply the
  Windows dark-title-bar setting whenever a top-level window is shown.
  Unsupported Windows versions retain their default title-bar appearance.

## Validation

- All **110 regression tests passed**, including 20 Qt UI tests.
- Verified the native Windows dark-mode setting for main windows and dialogs.
- Built the Windows executable and passed its startup/rendering smoke test
  across all eight pages using the native Windows Qt platform.

## Downloads

Choose the Windows executable, Linux executable or macOS ZIP below.
On Linux, mark the downloaded executable as executable with `chmod +x`.
