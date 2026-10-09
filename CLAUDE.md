# Prompt Box

Floating prompt-structuring tool: paste a rough prompt, get back structured Markdown.

## What it does
- Two modes: **Structure** (reformat existing prompt into labeled sections) and **Build** (expand a description into a full execution prompt with goal, constraints, steps, etc.)
- Calls any OpenAI-compatible API (NVIDIA, OpenRouter, Groq, OpenAI, custom)
- Floats above every app including full-screen terminals (macOS NSPanel; Windows always-on-top)

## Files
| File | Role |
|---|---|
| `promptbox.py` | Python backend — window management, API calls, key storage |
| `promptbox.html` | Single-file frontend (HTML/CSS/JS, no build step) |
| `promptbox.png` | App icon (1024×1024, Pillow-generated) |
| `promptbox_windows.cmd` | Windows launcher — installs deps on first run |

## Run
```
# macOS
python3 promptbox.py

# Windows — double-click
promptbox_windows.cmd
```

## Dependencies
`pywebview >= 6.2`, `pyobjc-framework-Cocoa` (macOS), `keyring` + `pyperclip` (Windows)

## Off-limits
- `promptbox.png` is generated; regenerate with Pillow if needed, don't hand-edit
- `graphify-out/` if present

## Conventions and checks
- Keep the two-file architecture: stdlib API/history logic in Python; UI and JS in HTML. No build step.
- `tests/`: offline Python unittest and Node test-runner fixtures. Use mocked providers and temporary storage; never real keys or private prompt history.
- Run `python3 promptbox.py --selftest`, `python3 -m unittest discover -s tests -v`, and `node --test tests/frontend.test.cjs` after behavioral changes.
- Preserve prompt constraints, uncertainty, and code. Literal checks are heuristic; characters/4 is not measured usage.
- One conversion request, no hidden retries. Reject incomplete output; keep usable output if history saving fails.
- Treat credentials, local config, generated graphs/icon, vendored files, and lockfiles as off-limits unless the task requires changes. No vendored source or lockfiles currently exist.
- Canonical source is this repository. Do not maintain manual copies in `~/Scripts`; point local launchers here.
