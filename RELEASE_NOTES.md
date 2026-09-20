## What's changed

- **Windows/Vulkan path validation (#6):** Check projected nested MSBuild/FileTracker
  paths before starting a build. Account for custom source suffixes, collision
  timestamps and explicit PowerShell build directories. Reject excessive paths
  with guidance to use a fresh shorter output root, without moving existing outputs.
- **Native Windows/MSVC CPU features (#5):** Supplement upstream detection with
  live AVX-VNNI/BMI2 flags for CPU, CUDA and Vulkan builds. Check Windows AVX state
  support, clear unsupported cached features and preserve explicit profile
  overrides. Portable and other compiler flag paths retain their existing behavior.
- **Saved build choices:** Restore validated CPU-target and parallel-job settings.
  Clarify that detected features do not guarantee effective compiler settings.
- **Regression coverage:** All 82 tests pass, including direct PowerShell preflight,
  preservation of existing builds, flag transport, profile overrides and settings.

## Thanks

Thank you, **DaWaste ([@DaWasteh](https://github.com/DaWasteh))**, for reporting
[#5](https://github.com/nextscript/Llama.cpp-Build-Assistant/issues/5) and
[#6](https://github.com/nextscript/Llama.cpp-Build-Assistant/issues/6), and for
providing detailed reproduction steps, real build evidence and tested workarounds!

## Validation

The regression suite, Python syntax checks and Git whitespace checks passed.
A full GPU build and model-inference validation were not performed for this release.

## Downloads

Choose the Windows executable, Linux executable or macOS ZIP below.
On Linux, mark the downloaded executable as executable with `chmod +x`.
