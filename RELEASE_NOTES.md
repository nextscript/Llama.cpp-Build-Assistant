# v2.4.2 — Builds survive broken upstream tests

## What's changed

- **Test-only compile errors no longer fail the build (Windows):** Current
  llama.cpp's `tests/test-batch-alloc.cpp` does not compile with Visual Studio
  2026 (MSVC 19.51, error C2131), which made the whole build fail although
  `llama-server`, `llama-cli` and all other tools were built. The build
  assistant now checks the MSBuild log: if every error comes from a project
  under `build	ests` and `llama-server.exe` exists, the failed tests are
  reported as skipped and the build finishes normally, including CUDA runtime
  DLL deployment. Errors in any other target still fail the build.

## Validation

- All **110 regression tests passed**, including new checks that test-only
  failures are recognised and tool/linker errors are not.
- Built the Windows folder executable and passed its startup/rendering smoke
  test across all eight pages using the native Windows Qt platform.

## Downloads

Choose the Windows ZIP, Linux executable or macOS ZIP below.
On Windows, unzip `Llama.cpp-Build-Assistant-Windows.zip` and start
`Llama.cpp-Build-Assistant-Windows.exe` inside the folder; keep the EXE together
with its folder. On Linux, mark the downloaded executable as executable with
`chmod +x`.
