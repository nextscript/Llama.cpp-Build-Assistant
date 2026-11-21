# v2.4.4 — tritq-vllm builds with Visual Studio

## What's changed

- **Patch series now compile with MSVC (Windows):** The `ternii-ai/tritq-vllm`
  patches are written for GCC/Clang (Linux, macOS). With Visual Studio the
  CUDA build failed in `ggml/src/ggml-cpu/quants.c` (error C2143 and friends)
  because of `__attribute__((always_inline))`, and the MoE expert cache
  (`src/llama-moe-cache.cpp`) needs `<unistd.h>` and `pread`. After applying a
  patch series on Windows the build assistant now adjusts only the files the
  series touched: `__attribute__((always_inline))` becomes `__forceinline`,
  and `<unistd.h>` is replaced by a small generated `tq-win-compat.h`
  (`pread` via `ReadFile`, `ssize_t`, `S_ISREG`) in files without their own
  Windows handling. The changes stay in the working tree of
  `<checkout>\_patched` and are redone on every build.
- Note: the SSD expert cache of the series (`LLAMA_MOE_SSD=1`) is a macOS
  feature upstream and is not functional on Windows; normal inference is
  unaffected.

## Validation

- All **82 non-GUI regression tests passed**.
- Applied all 12 patches of `ternii-ai/tritq-vllm` (r5) and built the patched
  tree with Visual Studio 2022 (MSVC 19.44): `llama-server`, `llama-cli` and
  `test-backend-ops` build; the CUDA backend (`ggml-cuda`, sm_120a) compiled in
  the user's build. Only two upstream unit tests (`test-batch-alloc`,
  `test-server-component`) fail to compile, which the existing test-only
  handling reports as skipped.

## Downloads

Choose the Windows ZIP, Linux executable or macOS ZIP below.
On Windows, unzip `Llama.cpp-Build-Assistant-Windows.zip` and start
`Llama.cpp-Build-Assistant-Windows.exe` inside the folder; keep the EXE together
with its folder. On Linux, mark the downloaded executable as executable with
`chmod +x`.
