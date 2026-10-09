#!/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
"""Prompt Box: paste a rough prompt, get a structured Markdown version back.

UI lives in promptbox.html (shown in a native window via pywebview). The window floats
above every app (including full-screen ones) in the bottom-right corner:
a bubble when tucked away, a compact panel when open, or a big two-pane view.
Each conversion is saved to SAVE_DIR as <stamp>.md + <stamp>.original.txt.

Providers: any OpenAI-compatible chat API (presets below, or Custom).
Keys live in the OS credential store (macOS Keychain / Windows Credential Manager),
one entry per provider; the app's Settings saves them.
Non-secret settings (active provider, model names, custom URL) live in CONFIG.

macOS:   ~/Applications/Prompt Box.app, or run this file.  Needs: pip install pywebview
Windows: double-click promptbox_windows.cmd (installs pywebview, keyring, pyperclip on first run).
Self-check: promptbox.py --selftest
"""
import os, re, subprocess, sys, json, time, urllib.error, urllib.request, webbrowser
from urllib.parse import urlsplit
from uuid import uuid4
from datetime import datetime
from pathlib import Path

MAC, WIN = sys.platform == "darwin", sys.platform == "win32"
HERE = Path(__file__).resolve().parent
SAVE_DIR = Path.home() / "Documents" / "Prompts"
APP_DIR = (Path(os.environ.get("APPDATA", Path.home())) if WIN
           else Path.home() / "Library" / "Application Support") / "Prompt Box"
CONFIG = APP_DIR / "config.json"

# All of these speak the OpenAI /chat/completions format. Model names change often,
# so they are only defaults; the user can edit them in Settings.
PROVIDERS = {
    "nvidia": {"name": "NVIDIA", "base": "https://integrate.api.nvidia.com/v1",
               "keys": "https://build.nvidia.com", "service": "nvidia-api",
               "fast": "meta/llama-3.1-8b-instruct", "careful": "meta/llama-3.3-70b-instruct"},
    "openrouter": {"name": "OpenRouter", "base": "https://openrouter.ai/api/v1",
                   "keys": "https://openrouter.ai/keys",
                   "fast": "meta/llama-3.1-8b-instruct:free", "careful": "meta/llama-3.3-70b-instruct:free"},
    "groq": {"name": "Groq", "base": "https://api.groq.com/openai/v1",
             "keys": "https://console.groq.com/keys",
             "fast": "llama-3.1-8b-instant", "careful": "llama-3.3-70b-versatile"},
    # OpenAI reasoning models reject temperature/max_tokens, so send neither
    "openai": {"name": "OpenAI", "base": "https://api.openai.com/v1",
               "keys": "https://platform.openai.com/api-keys", "plain": True,
               "fast": "gpt-5-mini", "careful": "gpt-5"},
    "custom": {"name": "Custom", "base": "", "keys": "", "fast": "", "careful": ""},
}
# Earlier built-in defaults may still be stored as user model edits. Treat only
# these exact old defaults as stale; leave every other saved model untouched.
OLD_NVIDIA_DEFAULTS = {"fast": "nvidia/nemotron-3.5-lightning-30b-a3b",
                       "careful": "nvidia/nemotron-3-super-120b-a12b"}
COMMON_RULES = """Edit the user's text into a prompt. Return only the rewritten prompt. Do not copy these editing directions into the result.
Preserve the user's requirements, exclusions, uncertainty, numbers, units, names, paths, commands, and code exactly. Keep pasted code/logs in fenced blocks. Do not turn a tentative idea into a decision. Remove only filler and repetition."""

STRUCTURE = COMMON_RULES + """
Structure mode: Reorganize only the user's content. Use these headings only when needed: ## Goal, ## Context, ## Constraints, ## Out of scope, ## Done when, ## Open questions.
Put each requirement in one section. Constraints must come from the user's text. Put exclusions in Out of scope and unresolved choices in Open questions. Add Done when only for checks the user actually stated. Do not add advice, instructions, tools, or steps."""

BUILD = COMMON_RULES + """
Turn the description into a minimal execution prompt. Use these ## headings in order where useful:
Goal; Features (### per feature, with acceptance checks); Design; Tech; Steps (smallest working version first); Out of scope; Done when; Assumptions; Open questions.
Infer only necessary steps and checks. Put every unstated decision exclusively in Assumptions as a proposal for review, never as an approved requirement. Put blocking unknowns in Open questions. Do not invent a stack, visual values, or scope to fill headings."""

MODES = {"structure": STRUCTURE, "build": BUILD}


def leaked_instructions(original, md, instructions):
    """Catch copied editing directions before treating a conversion as usable."""
    legacy_markers = ("output only concise markdown", "remove only repetition and conversational filler",
                      "never trade fidelity for brevity", "omit empty sections",
                      "aim for no expansion beyond headings", "done when (stated checkable outcomes)")
    if any(marker in md.lower() and marker not in original.lower() for marker in legacy_markers):
        return True
    words = lambda s: re.findall(r"[a-z0-9]+", s.lower())
    source, result, user = (words(s) for s in (instructions, md, original))
    source_phrases = {tuple(source[i:i + 5]) for i in range(len(source) - 4)}
    user_phrases = {tuple(user[i:i + 5]) for i in range(len(user) - 4)}
    return any(tuple(result[i:i + 5]) in source_phrases - user_phrases
               for i in range(len(result) - 4))


# ---------- settings + keys ----------

def load_config():
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    if cfg.get("provider") not in PROVIDERS:
        cfg["provider"] = "nvidia"
    if not isinstance(cfg.get("models"), dict):
        cfg["models"] = {}
    return cfg


def save_config(cfg):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def provider_settings(pid, cfg=None):
    """Preset merged with the user's edits."""
    cfg = load_config() if cfg is None else cfg
    p = dict(PROVIDERS[pid], id=pid)
    edits = cfg.get("models", {}).get(pid, {})
    if isinstance(edits, dict):
        p.update({k: v.strip() for k, v in edits.items()
                  if k in ("fast", "careful") and isinstance(v, str) and v.strip()
                  and not (pid == "nvidia" and v.strip() == OLD_NVIDIA_DEFAULTS[k])})
    if pid == "custom":
        p["base"] = cfg.get("custom_base", "")
    p.setdefault("service", f"promptbox-{pid}")
    return p


def get_key(service):
    if not MAC:  # Windows Credential Manager (or the Linux keyring)
        import keyring
        return keyring.get_password(service, Path.home().name)
    # macOS: the `security` CLI, so reading keys never triggers a Keychain permission prompt
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def set_key(service, key):
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-.]{16,}", key):
        raise ValueError("That doesn't look like an API key. Paste the whole key with no spaces.")
    if not MAC:
        import keyring
        keyring.set_password(service, Path.home().name, key)
    else:  # via `security -i` stdin so the key never shows up in the process list
        cmd = f'add-generic-password -U -a "{Path.home().name}" -s {service} -w "{key}"\n'
        subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True)
    if get_key(service) != key:
        raise RuntimeError("The system credential store refused the key.")


# ---------- conversion ----------

class IncompleteResponse(RuntimeError):
    def __init__(self, message, usage, model):
        super().__init__(message)
        self.usage = usage
        self.model = model


def reported_usage(result):
    raw = result.get("usage")
    return {k: v for k, v in (raw.items() if isinstance(raw, dict) else [])
            if k in ("prompt_tokens", "completion_tokens", "total_tokens")
            and type(v) is int and v >= 0}

def validate_base(base):
    url = urlsplit(base)
    local = url.hostname in ("localhost", "127.0.0.1", "::1")
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or not (url.scheme == "https" or (url.scheme == "http" and local))):
        raise ValueError("Use an HTTPS base URL, or HTTP on localhost for a local model; no credentials, query, or fragment.")
    return base.rstrip("/")


def convert(prompt, tier="fast", instructions=STRUCTURE, *, with_usage=False):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Paste a prompt first.")
    if tier not in ("fast", "careful"):
        raise ValueError("Unknown model tier.")
    p = provider_settings(load_config().get("provider", "nvidia"))
    key, model, name = get_key(p["service"]), p.get(tier) or p.get("fast"), p["name"]
    if not key and p["id"] != "custom":
        raise RuntimeError(f"No {name} API key yet. Open Settings to add one.")
    if not p["base"] or not model:
        raise RuntimeError(f"{name} needs a base URL and model name. Open Settings to fill them in.")
    base = validate_base(p["base"])
    body = {"model": model,
            "messages": [{"role": "system", "content": instructions},
                         {"role": "user", "content": prompt}]}
    if not p.get("plain"):
        # Structure should stay near the input length. A smaller ceiling stops
        # runaway generations sooner; the response is rejected if truncated.
        limit = min(4096, max(512, len(prompt) * 2)) if instructions == STRUCTURE else 4096
        body.update(temperature=0, max_tokens=limit)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(base + "/chat/completions",
                                 data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.load(resp)
        choice = result["choices"][0]
        if choice.get("finish_reason") not in (None, "stop"):
            reason = choice["finish_reason"]
            message = (f"{name} hit the output limit (length). Nothing saved. Try another model."
                       if reason == "length" else
                       f"{name} stopped before finishing ({reason}). Nothing saved.")
            raise IncompleteResponse(
                message, reported_usage(result), model)
        text = choice["message"]["content"]
        if not isinstance(text, str):
            raise ValueError("No text content")
    except urllib.error.HTTPError as e:
        retry = e.headers.get("Retry-After") if e.headers else None
        wait = f" Retry after {retry}." if retry else " Try again later."
        e.close()
        msg = {401: f"{name} rejected the key. Check it in Settings.",
               403: f"{name} refused access to `{model}`.",
               404: f"{name} doesn't know the model `{model}`. Check Settings.",
               429: f"{name} rate limit hit.{wait} No automatic retry."}.get(e.code)
        raise RuntimeError(msg or f"{name} API error {e.code}.") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"Can't reach {name}. Check your connection and try again.") from e
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as e:
        raise RuntimeError(f"{name} sent back a response Prompt Box couldn't read.") from e
    # reasoning models sometimes prepend a <think> block
    text = re.sub(r"\A\s*<think>.*?</think>\s*", "", text, count=1, flags=re.S).strip()
    if not text or text.startswith("<think>"):
        raise RuntimeError(f"{name} returned no usable text. Nothing saved.")
    usage = reported_usage(result)
    return {"md": text, "usage": usage, "model": model} if with_usage else text


# ---------- detail check: hard facts in the original that must survive ----------

_DETAIL_PATTERNS = [
    r"`([^`\n]+)`",                                      # `code`
    r"[\"“]([^\"”\n]{2,80})[\"”]",                       # "quoted text"
    r"(https?://[^\s)\]>\"']+)",                         # URLs
    r"((?:~|\.{1,2})?/?(?:[\w.-]+/)+[\w.-]+)",           # paths with slashes
    r"\b([\w-]+\.(?:py|js|ts|tsx|jsx|json|md|html|css|sh|zsh|ya?ml|toml|txt|csv|sql|go|rs|java|c|cpp|h|swift|rb|php|env|lock|plist))\b",
    r"(?<![\w&])(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3})(?![0-9A-Za-z])",  # hex colors
    r"(?<![\w-])(--[a-zA-Z][\w-]+)",                     # --flags
    r"\b([a-z][a-z0-9]*_[a-z0-9_]+)\b",                  # snake_case
    r"\b([a-z]+[A-Z][A-Za-z0-9]*)\b",                    # camelCase
    r"(?<![\w.])(\d+(?:[.:,]\d+)*%?)(?!\d)",             # numbers, versions, times (30 in "30s")
]


def extract_details(text):
    out = []
    for pat in _DETAIL_PATTERNS:
        for m in re.finditer(pat, text):
            item = m.group(1).strip().rstrip(".,;:")
            # skip pieces of something already listed (main.py inside src/cli/main.py)
            if item and not any(_has(o, item) or (not item[0].isdigit() and item in o) for o in out):
                out.append(item)
    return out


def _has(md, item):
    # digits get digit-only boundaries so "30" matches "30s" but not "300"
    numeric = item[0].isdigit()
    left = r"(?<![\w.])" if numeric else r"(?<![\w/.-])"
    right = r"(?!\d|[.,:]\d)" if numeric else r"(?![\w/-]|\.[\w])"
    flags = re.I if re.fullmatch(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?", item) else 0
    return bool(re.search(left + re.escape(item) + right, md, flags))


def check_details(original, md):
    """Each hard detail of the original, and whether the converted text still has it."""
    return [{"item": d, "kept": _has(md, d)} for d in extract_details(original)]


# ---------- history ----------

def save(original, md):
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y-%m-%d_%H%M%S_%f}_{uuid4().hex[:8]}"
    (SAVE_DIR / f"{stamp}.md").write_text(md + "\n", encoding="utf-8")
    (SAVE_DIR / f"{stamp}.original.txt").write_text(original + "\n", encoding="utf-8")
    return stamp


def _title(md):
    m = re.search(r"^##\s*Goal\s*\n+(?:[-*]\s*)?(.+)", md, re.M | re.I)
    line = (m.group(1) if m else next((l for l in md.splitlines() if l.strip() and not l.startswith("#")), "Untitled"))
    line = re.sub(r"[`*_]", "", line).strip()
    return line[:70] + ("…" if len(line) > 70 else "")


def history(limit=60):
    if not SAVE_DIR.exists():
        return []
    items = []
    for p in sorted(SAVE_DIR.glob("*.md"), reverse=True)[:limit]:
        try:
            when = datetime.strptime(p.stem, "%Y-%m-%d_%H%M%S").isoformat()
        except ValueError:
            when = datetime.fromtimestamp(p.stat().st_mtime).isoformat()
        items.append({"id": p.stem, "title": _title(p.read_text(encoding="utf-8")), "when": when})
    return items


def load(stamp):
    if not re.fullmatch(r"[\w.-]+", stamp):
        raise ValueError("bad id")
    md = (SAVE_DIR / f"{stamp}.md").read_text(encoding="utf-8").strip()
    orig_path = SAVE_DIR / f"{stamp}.original.txt"
    original = orig_path.read_text(encoding="utf-8").strip() if orig_path.exists() else ""
    return {"original": original, "md": md, "details": check_details(original, md) if original else []}


# ---------- bridge exposed to the page as window.pywebview.api ----------

class Api:
    def __init__(self):
        self._window = None

    def status(self):
        p = provider_settings(load_config().get("provider", "nvidia"))
        return {"has_key": get_key(p["service"]) is not None or p["id"] == "custom", "provider": p["name"],
                "fast": p.get("fast", ""), "careful": p.get("careful", "")}

    def providers(self):
        cfg = load_config()
        out = []
        for pid in PROVIDERS:
            p = provider_settings(pid, cfg)
            out.append({k: p.get(k, "") for k in ("id", "name", "base", "keys", "fast", "careful")}
                       | {"has_key": get_key(p["service"]) is not None,
                          "active": pid == cfg.get("provider", "nvidia")})
        return out

    def save_provider(self, pid, key, fast, careful, base):
        try:
            if pid not in PROVIDERS:
                raise ValueError("Unknown provider")
            if pid == "custom":
                base = validate_base(base.strip())
                if not fast.strip():
                    raise ValueError("Custom needs a Fast model name.")
            p = provider_settings(pid)
            if key.strip():
                set_key(p["service"], key)
            elif pid != "custom" and not get_key(p["service"]):
                raise ValueError(f"Paste your {p['name']} API key first.")
            cfg = load_config()
            cfg["provider"] = pid
            cfg.setdefault("models", {})[pid] = {"fast": fast.strip(), "careful": careful.strip()}
            if pid == "custom":
                cfg["custom_base"] = base.strip()
            save_config(cfg)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def convert(self, prompt, tier="fast", mode="structure"):
        started = time.monotonic()
        try:
            if mode not in MODES:
                raise ValueError("Unknown conversion mode.")
            result = convert(prompt, tier, MODES[mode], with_usage=True)
            md = result["md"]
            if leaked_instructions(prompt, md, MODES[mode]):
                return {"ok": False,
                        "error": "The model copied Prompt Box's editing directions into the result. Nothing saved. Use the original prompt or try a different model after checking Settings.",
                        "usage": result["usage"], "model": result["model"],
                        "elapsed_seconds": round(time.monotonic() - started, 1)}
            # A disk failure must not discard a successful (possibly paid) response.
            result.update(ok=True, id=None, details=check_details(prompt, md))
            try:
                result["id"] = save(prompt, md)
            except OSError:
                result["warning"] = "Converted, but history could not be saved. Copy the result before closing."
            result["elapsed_seconds"] = round(time.monotonic() - started, 1)
            return result
        except Exception as e:
            error = {"ok": False, "error": str(e),
                     "elapsed_seconds": round(time.monotonic() - started, 1)}
            if isinstance(e, IncompleteResponse):
                error.update(usage=e.usage, model=e.model)
            return error

    def check(self, original, md):
        return check_details(original, md)

    def history(self):
        return history()

    def load(self, stamp):
        return load(stamp)

    def copy(self, text):
        if MAC:
            subprocess.run(["pbcopy"], input=text, text=True)
        else:
            import pyperclip
            pyperclip.copy(text)
        return True

    def open_folder(self):
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        if WIN:
            os.startfile(SAVE_DIR)
        else:
            subprocess.run(["open" if MAC else "xdg-open", str(SAVE_DIR)])

    def open_url(self, url):
        if re.match(r"https://", url):
            webbrowser.open(url)

    def platform(self):
        return "mac" if MAC else "win" if WIN else "other"

    def layout(self, mode):
        if MAC:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(_apply_layout, mode)
        else:
            _win_layout(self._window, mode)

    def move_by(self, dx, dy):
        if MAC:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(_move_by, dx, dy)
        else:
            self._window.move(self._window.x + dx, self._window.y + dy)

    def quit(self):
        if MAC:
            from AppKit import NSApplication
            from PyObjCTools import AppHelper
            AppHelper.callAfter(NSApplication.sharedApplication().terminate_, None)
        else:
            self._window.destroy()


# ---------- floating panel (macOS) ----------
# A normal window can only cover another app's full-screen Space by activating its app,
# which switches Spaces. A borderless *non-activating panel* (like Spotlight) can sit on
# top of any Space and still take typing, so the web view is moved into one of those.

# window sizes in points; the page draws its own rounded card inside an 8px transparent margin
SIZES = {"orb": (56, 56), "panel": (320, 460), "full": (1180, 760)}
EDGE = 6  # gap from the screen's bottom-right corner
_panel = None


def _panel_class():
    from AppKit import NSPanel

    class PromptBoxPanel(NSPanel):
        def canBecomeKeyWindow(self):  # borderless panels refuse keyboard focus by default
            return True

    return PromptBoxPanel


def _apply_layout(mode):
    """Resize the panel: a bubble or panel pinned bottom-right, or a big centered view."""
    from AppKit import NSMakeRect, NSScreen
    vf = (_panel.screen() or NSScreen.mainScreen()).visibleFrame()  # excludes menu bar and Dock
    w, h = SIZES[mode]
    w, h = min(w, vf.size.width - 2 * EDGE), min(h, vf.size.height - 2 * EDGE)
    if mode == "full":
        x, y = vf.origin.x + (vf.size.width - w) / 2, vf.origin.y + (vf.size.height - h) / 2
    else:
        x, y = vf.origin.x + vf.size.width - w - EDGE, vf.origin.y + EDGE
    _panel.setFrame_display_animate_(NSMakeRect(x, y, w, h), True, True)
    if mode == "orb":
        _panel.orderFrontRegardless()
    else:  # take keyboard focus without activating the app, so no Space switch
        _panel.makeKeyAndOrderFront_(None)


def _move_by(dx, dy):
    o = _panel.frame().origin
    _panel.setFrameOrigin_((o.x + dx, o.y - dy))  # screen y grows downward in JS, upward in AppKit


def _make_floating(win):
    """Move pywebview's web view into a panel that floats over every app and Space."""
    global _panel
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered,
                        NSColor, NSStatusWindowLevel, NSView, NSWindowCollectionBehaviorCanJoinAllSpaces,
                        NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowCollectionBehaviorIgnoresCycle,
                        NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel)
    # accessory = no Dock icon or menu bar
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    p = _panel_class().alloc().initWithContentRect_styleMask_backing_defer_(
        win.frame(), NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered, False)
    p.setOpaque_(False)
    p.setBackgroundColor_(NSColor.clearColor())
    p.setHasShadow_(False)  # the page draws its own shadow
    p.setFloatingPanel_(True)
    p.setLevel_(NSStatusWindowLevel)  # after setFloatingPanel_, which resets the level to 3
    p.setHidesOnDeactivate_(False)
    p.setReleasedWhenClosed_(False)
    p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                             | NSWindowCollectionBehaviorFullScreenAuxiliary
                             | NSWindowCollectionBehaviorIgnoresCycle)
    webview = win.contentView()
    win.setContentView_(NSView.alloc().init())
    win.orderOut_(None)
    p.setContentView_(webview)
    p.makeFirstResponder_(webview)
    _panel = p
    _apply_layout("panel")


# ---------- floating window (Windows) ----------
# A frameless always-on-top window already sits above other apps, including
# full-screen (F11) Windows Terminal, so only size and position need handling here.

def _win_rect(work, mode):
    """(x, y, w, h) in logical pixels for a work area (left, top, right, bottom)."""
    left, top, right, bottom = work
    w, h = SIZES[mode]
    w, h = min(w, right - left - 2 * EDGE), min(h, bottom - top - 2 * EDGE)
    if mode == "full":
        return left + (right - left - w) / 2, top + (bottom - top - h) / 2, w, h
    return right - w - EDGE, bottom - h - EDGE, w, h


def _win_layout(window, mode):
    import ctypes, ctypes.wintypes as wt
    r = wt.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA: screen minus taskbar
    scale = ctypes.windll.user32.GetDpiForSystem() / 96  # work area is in physical pixels, pywebview wants logical
    x, y, w, h = _win_rect((r.left / scale, r.top / scale, r.right / scale, r.bottom / scale), mode)
    window.resize(int(w), int(h))
    window.move(int(x), int(y))


def _single_instance():
    """Exit if Prompt Box is already running (the bubble is already on screen)."""
    import socket
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 47613))  # a port only one process can hold; works on macOS and Windows
    except OSError:
        sys.exit(0)
    return lock  # keep it open for the life of the process


def _selftest():
    orig = 'Fix `parse_args` in src/cli/main.py so --verbose works; keep timeout at 30s, see https://x.io/a. Call it "Prompt Box", use getUserName.'
    d = extract_details(orig)
    for want in ["parse_args", "src/cli/main.py", "--verbose", "30", "https://x.io/a", "Prompt Box", "getUserName"]:
        assert want in d, (want, d)
    res = {r["item"]: r["kept"] for r in check_details(orig, "Fix `parse_args` in `src/cli/main.py`; timeout 300s")}
    assert res["parse_args"] and res["src/cli/main.py"], res
    assert not res["--verbose"] and not res["30"], res   # "300" must not count as keeping "30"
    assert "main.py" not in d and "/x.io/a" not in d, d   # no duplicate fragments
    assert check_details("wait 30s", "- wait `30s`")[0]["kept"]
    d = extract_details("Background #0F172A, accent #fff, 2 pages")
    assert d == ["#0F172A", "#fff", "2"], d   # hex is one detail, not the number 0
    assert check_details("bg #0F172A", "- Background `#0f172a`")[0]["kept"]
    cfg = {"provider": "groq", "models": {"groq": {"fast": "my-model", "careful": ""}},
           "custom_base": "https://x.test/v1"}
    g = provider_settings("groq", cfg)
    assert g["fast"] == "my-model" and g["careful"] == PROVIDERS["groq"]["careful"], g  # blank edit keeps default
    assert g["service"] == "promptbox-groq" and provider_settings("nvidia", cfg)["service"] == "nvidia-api"
    assert provider_settings("custom", cfg)["base"] == "https://x.test/v1"
    assert _title("## Goal\nMake `x` faster\n\n## Done when\n- ok") == "Make x faster"
    pw, ph = SIZES["panel"]  # Windows: panel pinned above a 40px taskbar on 1920x1080
    assert _win_rect((0, 0, 1920, 1040), "panel") == (1920 - pw - EDGE, 1040 - ph - EDGE, pw, ph)
    assert _win_rect((0, 0, 1000, 600), "full")[2:] == (1000 - 2 * EDGE, 600 - 2 * EDGE)  # clamps to small screens
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
        sys.exit()
    import time, webview
    _lock = _single_instance()
    api = Api()
    api._window = webview.create_window(
        "Prompt Box", url=str(HERE / "promptbox.html"), js_api=api,
        width=SIZES["panel"][0], height=SIZES["panel"][1], min_size=(56, 56),
        frameless=True, easy_drag=False, transparent=True, on_top=True)

    def _setup():
        api._window.events.loaded.wait()  # the web view joins the window only after the page loads
        if WIN:
            _win_layout(api._window, "panel")
            return
        from PyObjCTools import AppHelper
        from WebKit import WKWebView
        while not (api._window.native and api._window.native.contentView().isKindOfClass_(WKWebView)):
            time.sleep(0.05)
        AppHelper.callAfter(_make_floating, api._window.native)

    webview.start(_setup)
