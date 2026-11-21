# v2.4.3 — Patch-series sources (tritq-vllm)

## What's changed

- **Patch-series repositories now build:** Some sources are not a llama.cpp
  fork but a set of patches against a pinned upstream commit, for example
  [`ternii-ai/tritq-vllm`](https://github.com/ternii-ai/tritq-vllm)
  (`runtime/llama.cpp/PINNED_BASE` + `patches/NNNN-*.patch`). Using such a
  repository as the Repo URL failed with *"does not appear to contain
  CMakeLists.txt"*. The build assistant now detects the patch series, clones
  the upstream repository named in `apply.sh` (default `ggml-org/llama.cpp`),
  checks out the pinned commit, applies all patches with `git am` in
  `<checkout>/_patched` and configures CMake from there. The patched tree is
  reused and re-patched on later builds; the build output stays in
  `<checkout>/build`. Works on Windows, Linux and macOS.
- A repository with neither `CMakeLists.txt` nor a patch series now stops with
  a clear message about the Repo URL instead of a CMake error.

## Validation

- All **82 non-GUI regression tests passed**.
- Applied all 12 patches of `ternii-ai/tritq-vllm` (r5, base `ff5a233`) with
  both the PowerShell and the Bash implementation, including a second run that
  reuses the existing patched tree.

## Downloads

Choose the Windows ZIP, Linux executable or macOS ZIP below.
On Windows, unzip `Llama.cpp-Build-Assistant-Windows.zip` and start
`Llama.cpp-Build-Assistant-Windows.exe` inside the folder; keep the EXE together
with its folder. On Linux, mark the downloaded executable as executable with
`chmod +x`.
