# Prompt Box

**Paste a messy prompt. Get a structured one back.**

A floating window that lives in the corner of your screen and reformats rough prompts into clean Markdown that coding agents (Claude, ChatGPT, Cursor, etc.) understand better. Works over every app — including full-screen terminals.

![Prompt Box icon](promptbox.png)

---

## Why

Coding agents read prompts better when requirements are split into labeled sections (`Goal`, `Constraints`, `Done when`). Writing that structure by hand every time is friction. Prompt Box does it in one keypress, before you send.

---

## Two modes

| Mode | Input | Output |
|---|---|---|
| **Structure** | A rough prompt you already wrote | The same requirements, reorganized into labeled Markdown sections |
| **Build** | A plain-English description of what you want | A full execution prompt with Goal, Features, Steps, Acceptance criteria, and Assumptions |

### Structure output example
```
## Goal
Add dark mode toggle to the settings page.

## Constraints
- Use the existing `useTheme` hook, don't introduce a new one
- No new dependencies

## Done when
- Toggle visible in Settings → Appearance
- `localStorage` key `theme` is set to `"dark"` or `"light"` on change
- All existing Cypress tests still pass
```

### Build output example
```
## Goal
Build a habit tracker web app with streaks and a weekly progress chart.

## Features
### Daily streaks
Mark a habit done for today; streak counts consecutive days.
  - Acceptance: streak resets after a missed day

### Weekly progress chart
Bar chart of completions for the last 7 days.
  - Acceptance: shows 7 bars, today on the right

## Design
- Background `#0F172A`, accent mint green `#3EB489`

## Assumptions
- Chart drawn with plain SVG, no charting library
- Local storage for persistence; no backend
```

---

## Features

- **Floats above everything** — appears over full-screen terminals, Claude, ChatGPT desktop, VS Code. macOS uses an NSPanel; Windows uses an always-on-top overlay.
- **Three sizes** — orb (56×56 bubble), panel (320×460 corner), full (1180×760 workspace)
- **Fidelity check** — after conversion, highlights any numbers, file paths, hex colors, or flags from your original that didn't survive into the output
- **History sidebar** — every conversion saved locally as `<timestamp>.md` + `<timestamp>.original.txt`
- **Six API providers** — all free-tier friendly, all OpenAI-compatible:

| Provider | Get a key |
|---|---|
| NVIDIA | [build.nvidia.com](https://build.nvidia.com) |
| Google AI Studio | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| OpenRouter (free models) | [openrouter.ai/keys](https://openrouter.ai/keys) |
| Groq | [console.groq.com/keys](https://console.groq.com/keys) |
| OpenAI | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Custom | Any OpenAI-compatible endpoint |

- **Two quality tiers** — Fast (smaller model, instant) and Careful (larger model, better output)
- **API keys stored securely** — macOS Keychain / Windows Credential Manager, never in plain text

---

## Install

### macOS

```bash
pip3 install pywebview pyobjc-framework-Cocoa
python3 promptbox.py
```

**Or as an app:** drag `Prompt Box.app` to `/Applications` if provided, or build one:
```bash
pip3 install py2app   # then follow standard py2app packaging
```

### Windows

Double-click `promptbox_windows.cmd`. On first run it installs dependencies automatically:
```
pywebview   keyring   pyperclip
```

Requirements: Python 3.10–3.13 from [python.org](https://python.org). Python 3.14 may not yet be supported by pywebview's Windows backend.

---

## Usage

1. **Click the orb** to expand the panel
2. **Paste your prompt** into the text area
3. **Choose a mode**: Structure or Build
4. Press **⌘↩** (macOS) or **Ctrl+Enter** (Windows) to convert
5. **⇧⌘C** / **Ctrl+Shift+C** to copy the result, or click Copy

**First run:** click ⚙ → enter an API key for your chosen provider → Save.

### Keyboard shortcuts

| Action | macOS | Windows |
|---|---|---|
| Convert | ⌘↩ | Ctrl+Enter |
| Copy result | ⇧⌘C | Ctrl+Shift+C |
| Toggle panel/orb | click orb | click orb |

---

## Configuration

Settings are stored in:
- **macOS:** `~/Library/Application Support/Prompt Box/config.json`
- **Windows:** `%APPDATA%\Prompt Box\config.json`

You can override the model name for any provider in Settings → ⚙.

Conversions are saved to `~/Documents/Prompts/`.

---

## How it works

```
Your rough prompt
       │
       ▼
  System prompt (STRUCTURE or BUILD rules)
       │
       ▼
  API call (your chosen provider)
       │
       ▼
  Structured Markdown
       │
       ├─── Fidelity check: did every key detail survive?
       ├─── Saved to ~/Documents/Prompts/<timestamp>.md
       └─── Displayed + ready to copy
```

The system prompts enforce specific rules: keep every number, file name, and error text verbatim; delete filler; never add requirements the user didn't mention; output only Markdown with no preamble.

---

## Platform notes

| | macOS | Windows |
|---|---|---|
| Floating above full-screen | NSPanel (non-activating, joins all Spaces) | Always-on-top frameless window |
| API key storage | Keychain (`security` CLI) | Credential Manager (`keyring`) |
| Copy | `pbcopy` | `pyperclip` |
| Fonts | SF Pro / SF Mono | Segoe UI / Cascadia Mono |

> **Games in exclusive full-screen mode** can't be overlaid on either platform — this is a system-level restriction, not a Prompt Box limitation.

---

## License

MIT
