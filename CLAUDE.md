# Prompt Box

Floating prompt-structuring tool: paste a rough prompt, get back structured Markdown.

## What it does
- Two modes: **Structure** (reformat existing prompt into labeled sections) and **Build** (expand a description into a full execution prompt with goal, constraints, steps, etc.)
- Calls any OpenAI-compatible API (NVIDIA, Google AI Studio, OpenRouter, Groq, OpenAI, custom)
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
