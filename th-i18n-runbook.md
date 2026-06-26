# Thai i18n Translation Pipeline

This runbook is for adding Thai (`th`) to WAP locale literals with low Codex chat-token usage.

## Recommended Roles

- Node.js script: extracts leaf strings, splits chunks, merges translations, validates keys and placeholders.
- GPT CLI or OpenAI API: translates one chunk at a time.
- Antigravity CLI: optional orchestration helper. Do not make it the source of truth for merge or validation.

## Why This Saves Codex Tokens

Codex only needs to maintain the script and process. The large `literals.json` content stays on disk and is processed by Node.js and GPT CLI chunk calls. Translation still consumes GPT/API tokens, but it avoids loading the full locale file into Codex conversation context.

## Basic Commands

Run from the folder containing `i18n-th-pipeline.mjs`, or use the absolute path to the script.

```powershell
node .\i18n-th-pipeline.mjs extract `
  --literals D:\WAP_ssa\jsx\sys\locale\literals.json `
  --outDir D:\WAP_ssa\jsx\sys\locale\th-work `
  --batchSize 150
```

```powershell
node .\i18n-th-pipeline.mjs translate `
  --literals D:\WAP_ssa\jsx\sys\locale\literals.json `
  --outDir D:\WAP_ssa\jsx\sys\locale\th-work `
  --gptCommand "gpt"
```

```powershell
node .\i18n-th-pipeline.mjs merge `
  --literals D:\WAP_ssa\jsx\sys\locale\literals.json `
  --outDir D:\WAP_ssa\jsx\sys\locale\th-work `
  --output D:\WAP_ssa\jsx\sys\locale\literals.with-th.json
```

```powershell
node .\i18n-th-pipeline.mjs validate `
  --literals D:\WAP_ssa\jsx\sys\locale\literals.json `
  --file D:\WAP_ssa\jsx\sys\locale\literals.with-th.json `
  --outDir D:\WAP_ssa\jsx\sys\locale\th-work
```

## Notes

- The script supports two common shapes:
  - Record shape: each literal object has `en`, `zh_tw`, and eventually `th`.
  - Root-locale shape: top-level `en`, `zh_tw`, and eventually `th` trees.
- If your file uses `zh-tw` instead of `zh_tw`, pass `--zhTwKey zh-tw`.
- The script validates missing Thai strings and placeholder mismatch.
- Keep the original `literals.json` unchanged until validation passes.
- After validation passes, compare `literals.with-th.json` against the original, then replace the original through your normal review process.

## GPT CLI Guidance

Different GPT CLIs accept prompts differently. This script sends the translation prompt through stdin to the command configured by `--gptCommand`.

If your CLI needs a model flag, use something like:

```powershell
node .\i18n-th-pipeline.mjs translate `
  --literals D:\WAP_ssa\jsx\sys\locale\literals.json `
  --outDir D:\WAP_ssa\jsx\sys\locale\th-work `
  --gptCommand "gpt --model gpt-4.1-mini"
```

Use a cheaper model for first pass translation, then run a smaller review pass on validation failures or high-risk UI strings.
