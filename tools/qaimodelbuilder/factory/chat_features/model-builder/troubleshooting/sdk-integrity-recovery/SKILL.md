---
skill_id: sdk-integrity-recovery
tier: base
triggers: ["0-byte qnn-context-binary-generator.exe", "WinError 193", "需要修改 SDK 文件", "B9", "SDK 文件损坏"]
sources: ["SKILL.md 179-217", "SKILL.md B8/B9"]
---

# SDK Integrity & Recovery (base)

> 🧭 通用诊断骨架（四阶段 + 三铁律 + 反向追溯 + 多层加固）见 [`../_diagnosis-framework.md`](../_diagnosis-framework.md)；本 SKILL 是该总纲在"SDK 写保护/损坏恢复"领域的症状库。

> 🔴 **This is the most dangerous skill. The default answer to "modify an SDK file" is NO.**
> The QAIRT SDK (`C:\Qualcomm\AIStack\QAIRT\<version>\` = `$QAIRT_SDK_ROOT`/`$QNN_SDK_ROOT`) is a
> shared third-party install. Editing it corrupts shared state for everyone. **Never** treat an SDK
> file edit as a fix. If a file is damaged, RECOVER it from a kept backup — do not "repair/regenerate" it.

## Responsibility

Enforce the "Do Not Modify QAIRT SDK Files" discipline (B9), correctly diagnose a damaged
`qnn-context-binary-generator.exe` (0-byte / `WinError 193`) **read-only**, and recover the single
damaged file from the kept SDK zip / launcher-script backup without a ~2 GB reinstall.

## Trigger signals

- `[WinError 193] %1 is not a valid Win32 application` when launching the generator
- A generator/tool is 0-byte or corrupt
- You are about to conclude "the fix requires editing an SDK file" → **STOP, this is B9**

## Core knowledge

### Do NOT modify any file under the QAIRT SDK (hard B9)

Applies without exception to: `.exe`/`.dll`/`.so`/`.lib`/`.cat`, all SDK-shipped Python modules
(`__init__.py`, converters, schemas, `*.pyc`), backend-extension JSON/config/headers, HTP runtime files.
Reaching the conclusion "the fix needs an SDK file change" is **itself B9** → stop and ask the user for
explicit, scoped permission citing the exact file path (generic "go ahead" is not consent). Record
approval (file + user msg + timestamp) before touching anything.

**Forbidden** (incl. via sub-agent/sub-shell): silent edits, "temporary" patches, hot-fix DLL replacement,
rewriting SDK Python sources, in-place schema edits, any command whose write target lands in the SDK tree
(`Copy-Item -Destination $SDK/...`, `del`, `Out-File`, `Move-Item`, `xcopy /Y`, `pip install --target=$SDK/...`,
`python setup.py install` against an SDK package, `git apply`/`patch` rooted under SDK), re-asking after a "no" with reworded prompts.

**Correct workaround:** copy the SDK file into `${WORKDIR}`/workspace `output/`, edit the **copy**, point
tooling at it via documented overrides (`--config_file`, `QNN_*` env vars, CLI flags, workspace-local
`backend_extensions.json`). No override exists → escalate B9.

**Pre-flight check before every write/exec** — does the absolute write target (incl. all redirections /
`-Destination` / `--prefix` / `--target` / `>` / `>>`) start with `$QAIRT_SDK_ROOT` / `$QNN_SDK_ROOT` /
`C:/Qualcomm/AIStack/QAIRT/...`? If yes → **STOP, trigger B9.** Three escape hatches to self-check:
1. **Relative path / redirection** — resolve against CWD first; `>`/`>>` clears the target so a failure leaves a 0-byte file.
2. **CWD set inside the SDK** — all relative writes then land in the SDK; never set CWD inside the SDK tree for write ops. When the generator's CWD rule is needed, copy HTP runtime into the **workspace** and run there (`qai_dev_gen_contextbin.py` does this).
3. **Indirect commands** — `cmd /c "... > file"`, sub-agents, `.bat`, Python `open(p,"w")`/`subprocess` write targets are all subject to the check.

> ✅ **Reading the SDK is allowed** (`dir`, `ls`, `read`, `grep`). The read/write boundary: after the op,
> did any SDK file's content/timestamp/size change? No → allowed. Yes → B9, stop immediately.

The whole `C:\Qualcomm` tree is **write-protected at the tool layer** (ALWAYS ON): `write`/`edit`/`apply_patch`,
`exec` write targets, and Python child-process writes into it are denied automatically — so an accidental write cannot corrupt the SDK.

### Diagnosing `WinError 193` / 0-byte generator (READ-ONLY only)

> 🔴 **Real incident (2026-06-16):** `bin/aarch64-windows-msvc/qnn-context-binary-generator.exe` was
> overwritten to 0 bytes (only that one exe; neighbors intact), then Step 3 reported `WinError 193`,
> misjudged as "SDK shipped corrupt". Root cause: **some command's output landed on that exe** — exactly
> what B9 prevents. The vast majority of 0-byte generators are **damaged by overwrite**, not a factory defect.

- **Do NOT misjudge `WinError 193` as "x64 Python cannot spawn an ARM64 exe."** An x64 process starting a
  new ARM64 process via `subprocess`/`CreateProcess` is fully feasible (both `run_pipeline.py` and `run_pipeline_legacy.py` rely on this pattern for `qai_dev_gen_contextbin.py`).
  Here `WinError 193` is 100% caused by the exe itself being 0-byte/corrupt. Do NOT "fix" it by switching
  `qai_dev_gen_contextbin.py` to `cmd /c` or altering the conversion chain — that is a wrong fix on a false premise.
- **Diagnose read-only, never "try-write/try-clear":** to check if it's corrupt use `Get-Item ... | Select Length`
  (read-only). If genuinely 0-byte → fall back per B8 to direct `.dll` inference, and recover the exe (below).
  Verify: a generator/exe must be non-zero and start with `MZ`; a launcher script must be readable text starting with `#!`.

### Self-heal (automatic)

`qai_dev_gen_contextbin.py` self-heals before launch: it re-extracts just the damaged
`qnn-context-binary-generator.exe` from the kept SDK zip (`data/sdk/qairt/v<version>.zip`, or
`vendor/qairt/v<version>.zip`), then the file-level backup — no 2 GB reinstall. If self-heal reports no usable zip → do Manual SDK file recovery.

### Manual SDK file recovery (fallback)

Two repair sources are kept OUTSIDE `C:\Qualcomm`. Recover the single file, then retry:

1. **Find the kept SDK zip** (first that exists): `${APP_ROOT}\data\sdk\qairt\v<version>.zip` or `${APP_ROOT}\vendor\qairt\v<version>.zip`. `<version>` = basename of `$QAIRT_SDK_ROOT`.
2. **Identify the damaged file's path relative to SDK root** (e.g. `bin/aarch64-windows-msvc/qnn-context-binary-generator.exe`); inside the zip it is nested under `QAIRT/<version>/` — match by suffix.
3. **Re-extract ONLY that one file** (do NOT expand the whole archive):
   ```powershell
   $zip = "${APP_ROOT}\data\sdk\qairt\v<version>.zip"
   $suffix = "bin/aarch64-windows-msvc/qnn-context-binary-generator.exe"
   Add-Type -AssemblyName System.IO.Compression.FileSystem
   $za = [System.IO.Compression.ZipFile]::OpenRead($zip)
   $e = $za.Entries | Where-Object { $_.FullName.ToLower().EndsWith($suffix.ToLower()) } | Select-Object -First 1
   [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, "$env:QAIRT_SDK_ROOT\$($suffix -replace '/','\')", $true)
   $za.Dispose()
   ```
   > Writing into `$QAIRT_SDK_ROOT` is normally blocked by the protected-paths guard. This recovery is the
   > **one legitimate exception** — set `QAI_PROTECTED_PATHS_BYPASS=1` ONLY around this single extract, then clear it immediately.
4. **Damaged launcher SCRIPT** (no-extension Python tools: `qnn-onnx-converter`, `qairt-converter`, `qairt-quantizer`, `qnn-model-lib-generator`) — file-level backup at `${APP_ROOT}\data\sdk\qairt-scripts\<arch>\<name>`; copy back (same bypass rule). Missing → extract from zip as step 3.
4b. **Damaged `qnn-context-binary-generator.exe`** — Setup.bat also backs it up to `${APP_ROOT}\data\sdk\qairt-scripts\aarch64-windows-msvc\qnn-context-binary-generator.exe` (~4 MB, faster than the zip). Copy back (same bypass rule).
5. **Verify (READ-ONLY)** then re-run the pipeline. If no kept zip and no script backup exist → STOP and ask the user to re-run `Setup.bat` to reinstall the SDK.

## Related Blocking Conditions

- **B9** — concluding a fix needs editing any file inside the SDK → **STOP IMMEDIATELY.** Document exact path + proposed change + root cause. Recover missing/corrupt files from the kept zip/backup instead of editing. Ask with the explicit prompt: *"This needs editing `<sdk_path>/<file>`. May I proceed? [y/N]"*. Act only after a scoped **yes** naming the file.
- **B8** — context binary generation fails on Windows ARM. Do not silently degrade to `.dll`; a 0-byte generator = damaged SDK file → self-heal / manual recovery. Diagnose READ-ONLY. Escalate further only if B3/B4/B7 met.

## Escalation path

Any time recovery would require writing into the SDK beyond the single sanctioned extract, or no backup source exists → STOP and ask the user (B9). Never edit, copy-over, rename, delete, or "regenerate" an SDK file to work around a problem.
