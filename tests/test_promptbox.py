import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import promptbox as pb


class PromptboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("CONFIG", Path(self.tmp.name) / "config.json"),
                            ("SAVE_DIR", Path(self.tmp.name) / "history")):
            patcher = patch.object(pb, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        key = patch.object(pb, "get_key", return_value="test-key")
        key.start()
        self.addCleanup(key.stop)

    def response(self, text="## Goal\nFix the bug", finish="stop", **extra):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": text},
                                                  "finish_reason": finish}], **extra}).encode())

    def test_removed_provider_and_malformed_config(self):
        for value in ({"provider": "google"}, [], {"models": []}, None):
            pb.CONFIG.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(pb.load_config()["provider"], "nvidia")
            self.assertEqual(pb.Api().status()["provider"], "NVIDIA")

    def test_model_edits_cannot_replace_endpoint(self):
        p = pb.provider_settings("nvidia", {"models": {"nvidia": {"fast": "x", "base": "https://wrong.test"}}})
        self.assertEqual(p["fast"], "x")
        self.assertEqual(p["base"], pb.PROVIDERS["nvidia"]["base"])
        self.assertEqual(pb.provider_settings("nvidia", {"models": {"nvidia": None}})["fast"], pb.PROVIDERS["nvidia"]["fast"])

    def test_old_saved_nvidia_defaults_migrate_without_touching_real_edits(self):
        old = {"models": {"nvidia": dict(pb.OLD_NVIDIA_DEFAULTS)}}
        p = pb.provider_settings("nvidia", old)
        self.assertEqual(p["fast"], pb.PROVIDERS["nvidia"]["fast"])
        self.assertEqual(p["careful"], pb.PROVIDERS["nvidia"]["careful"])
        old["models"]["nvidia"]["fast"] = "my-custom-model"
        self.assertEqual(pb.provider_settings("nvidia", old)["fast"], "my-custom-model")

    def test_usage_and_request(self):
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response(usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30})) as request:
            result = pb.Api().convert("Fix the bug")
        self.assertTrue(result["ok"])
        self.assertEqual(result["usage"]["total_tokens"], 30)
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["messages"][1]["content"], "Fix the bug")
        self.assertEqual(body["messages"][0]["content"], pb.STRUCTURE)
        self.assertEqual(body["max_tokens"], 512)
        self.assertEqual(len(pb.history()), 1)

    def test_structure_limit_grows_for_long_inputs_and_build_keeps_full_limit(self):
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response()) as request:
            pb.convert("x" * 600)
            structure = json.loads(request.call_args.args[0].data)
        self.assertEqual(structure["max_tokens"], 1200)
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response()) as request:
            pb.convert("a feature", instructions=pb.BUILD)
            build = json.loads(request.call_args.args[0].data)
        self.assertEqual(build["max_tokens"], 4096)

    def test_truncated_result_preserves_reported_usage_and_does_not_save(self):
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response("partial", "length", usage={"prompt_tokens": 95, "completion_tokens": 512})) as request:
            result = pb.Api().convert("Fix the timeout")
        self.assertFalse(result["ok"])
        self.assertIn("length", result["error"])
        self.assertEqual(result["usage"], {"prompt_tokens": 95, "completion_tokens": 512})
        self.assertEqual(pb.history(), [])
        request.assert_called_once()

    def test_unreported_usage_is_not_zero(self):
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response()):
            self.assertEqual(pb.Api().convert("Fix")['usage'], {})

    def test_reported_structure_failure_is_rejected_without_retry_or_history(self):
        original = '''Fix the timeout handling in src/App.ts. Keep the timeout at 30s.
Do not add dependencies or modify src/auth.ts.
Maybe use a queue, but ask before choosing that approach.
Preserve this code exactly:
```python
## This heading is code
print("hello")
```'''
        reported = '''## Goal
Fix the timeout handling in src/App.ts. Keep the timeout at 30s.

## Constraints
- Keep timeout at 30s
- Do not add dependencies
- Output only concise Markdown
- Remove only repetition and conversational filler
- Never trade fidelity for brevity or invent features
- Omit empty sections; do not repeat requirements across sections

## Done when (stated checkable outcomes)
- Timeout handling in src/App.ts fixed at 30s

```python
## This heading is code
print("hello")
```'''
        # This reproduces the observed class of failure even if the editing
        # directions change later: no user requirement authorizes these lines.
        self.assertTrue(pb.leaked_instructions(original, reported, pb.STRUCTURE))
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response(reported, usage={"prompt_tokens": 300, "completion_tokens": 170})) as request:
            result = pb.Api().convert(original)
        self.assertFalse(result["ok"])
        self.assertIn("editing directions", result["error"])
        self.assertEqual(result["usage"]["prompt_tokens"], 300)
        self.assertEqual(pb.history(), [])
        request.assert_called_once()

    def test_legitimate_structure_and_user_quoted_rules_are_not_rejected(self):
        original = 'Fix src/App.ts. Keep 30s. Maybe use a queue; ask first. Do not edit src/auth.ts.'
        good = '''## Goal
Fix `src/App.ts`.

## Constraints
- Keep 30s.

## Out of scope
- Do not edit `src/auth.ts`.

## Open questions
- Maybe use a queue; ask first.'''
        self.assertFalse(pb.leaked_instructions(original, good, pb.STRUCTURE))
        self.assertFalse(pb.leaked_instructions('Preserve: Do not add advice instructions tools or steps.',
                                                '## Context\nDo not add advice instructions tools or steps.', pb.STRUCTURE))
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response(good)):
            result = pb.Api().convert(original)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["elapsed_seconds"], 0)
        self.assertEqual(len(pb.history()), 1)

    def test_empty_truncated_blocked_or_malformed_not_saved(self):
        for text, finish in [("", "stop"), ("   ", "stop"), ("partial", "length"),
                             ("blocked", "content_filter"), (None, "stop"),
                             ("<think>only thoughts</think>", "stop"),
                             ("<think>unfinished", "stop")]:
            with self.subTest(text=text, finish=finish), patch.object(pb.urllib.request, "urlopen", return_value=self.response(text, finish)):
                self.assertFalse(pb.Api().convert("Fix")["ok"])
        for malformed in ({}, {"choices": []}, {"choices": [None]}, []):
            with patch.object(pb.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(malformed).encode())):
                self.assertFalse(pb.Api().convert("Fix")["ok"])
        self.assertEqual(pb.history(), [])

    def test_only_leading_reasoning_removed(self):
        text = '<think>reasoning</think>\n## Goal\nKeep `<think>literal</think>`.'
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response(text)):
            self.assertEqual(pb.convert("Fix"), '## Goal\nKeep `<think>literal</think>`.')

    def test_rate_limit_does_not_retry_or_sleep(self):
        error = HTTPError("https://test/v1", 429, "limit", {"Retry-After": "12"}, io.BytesIO())
        with patch.object(pb.urllib.request, "urlopen", side_effect=error) as request, patch.object(pb.time, "sleep") as sleep:
            result = pb.Api().convert("Fix")
        self.assertFalse(result["ok"])
        self.assertIn("12", result["error"])
        request.assert_called_once()
        sleep.assert_not_called()

    def test_network_failure_and_timeout(self):
        for error in (URLError("offline"), TimeoutError()):
            with patch.object(pb.urllib.request, "urlopen", side_effect=error):
                self.assertIn("Can't reach", pb.Api().convert("Fix")["error"])

    def test_save_failure_keeps_successful_output(self):
        with patch.object(pb.urllib.request, "urlopen", return_value=self.response()), patch.object(pb, "save", side_effect=OSError("full")):
            result = pb.Api().convert("Fix")
        self.assertTrue(result["ok"])
        self.assertIn("warning", result)
        self.assertIn("Fix the bug", result["md"])
        self.assertIsNone(result["id"])

    def test_keyless_custom_endpoint(self):
        with patch.object(pb, "get_key", return_value=None):
            result = pb.Api().save_provider("custom", "", "local-model", "", "http://localhost:11434/v1")
            self.assertTrue(result["ok"])
            self.assertTrue(pb.Api().status()["has_key"])
            with patch.object(pb.urllib.request, "urlopen", return_value=self.response()) as request:
                self.assertTrue(pb.Api().convert("Fix")["ok"])
            self.assertIsNone(request.call_args.args[0].get_header("Authorization"))

    def test_url_validation_before_key_write(self):
        for base in ("http://example.com/v1", "https://user:pass@host/v1", "https://host/v1?key=secret", "https://host/v1#fragment", "file:///tmp/model"):
            with patch.object(pb, "set_key") as key:
                self.assertFalse(pb.Api().save_provider("custom", "test-key", "model", "", base)["ok"])
                key.assert_not_called()
        self.assertEqual(pb.validate_base("http://[::1]:1234/v1"), "http://[::1]:1234/v1")

    def test_blank_or_invalid_request_does_not_call_api(self):
        with patch.object(pb.urllib.request, "urlopen") as request:
            for args in ((" ",), ("Fix", "unknown"), ("Fix", "fast", "unknown")):
                self.assertFalse(pb.Api().convert(*args)["ok"])
            request.assert_not_called()

    def test_exact_details(self):
        for original, changed in (("src/App.ts", "src/app.ts"), ("parseArgs", "parseargs"),
                                  ("--dry-run", "--dry-runner"), ("2", "#0F172A"),
                                  ("30", "300"), ("30", "30.5"), ("v1.2", "v1.20"),
                                  ("src/main.py", "other/src/main.py")):
            self.assertFalse(pb._has(changed, original), (original, changed))
        self.assertTrue(pb._has("`#fff`", "#FFF"))
        self.assertTrue(pb._has("wait 30s", "30"))

    def test_history_no_overwrite_and_unicode(self):
        stamps = [pb.save("保留原文", "## Goal\n修复 café") for _ in range(2)]
        self.assertNotEqual(*stamps)
        self.assertEqual(len(pb.history()), 2)
        self.assertEqual(pb.load(stamps[0])["original"], "保留原文")
        self.assertEqual(pb.load(stamps[0])["md"], "## Goal\n修复 café")
        with self.assertRaises(ValueError):
            pb.load("../escape")


if __name__ == "__main__":
    unittest.main()
