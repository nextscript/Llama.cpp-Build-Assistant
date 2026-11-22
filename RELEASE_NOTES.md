# v2.4.5 — npm 12 web UI build fix

## What's changed

- Fix `EALLOWREMOTE` when building llama.cpp's web UI with npm 12. The build
  scripts allow direct URL dependencies such as `llama-brand` for the npm
  install command, without changing the user's npm configuration.

## Validation

- Windows build script tests and shell script syntax checks passed.

## Downloads

Choose the Windows ZIP, Linux executable or macOS ZIP below.
On Windows, unzip `Llama.cpp-Build-Assistant-Windows.zip` and start
`Llama.cpp-Build-Assistant-Windows.exe` inside the folder; keep the EXE together
with its folder. On Linux, mark the downloaded executable as executable with
`chmod +x`.
