"""Isolierte Regressionstests für Key-Auflösung, Temp-Konfiguration und Doku."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
# Beim direkten Aufruf (`python3 tests/test_minimax_agent.py`) steht nur dieses
# Verzeichnis im Suchpfad; das Repo-Wurzelverzeichnis kommt hier dazu, damit
# `minimax_agent` importierbar ist. Bei `python3 -m unittest discover` ist es
# ohnehin schon enthalten, der Eintrag schadet dort nicht.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import minimax_agent  # noqa: E402  (Import erst nach dem Suchpfad-Eintrag möglich)


CUSTOM_URL = "https://other-provider.invalid/v1"


class ApiKeyResolutionTests(unittest.TestCase):
    def test_custom_url_rejects_implicit_minimax_environment_key(self):
        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-secret"}, clear=True):
            with mock.patch.object(minimax_agent.sys, "platform", "darwin"):
                with mock.patch.object(minimax_agent.subprocess, "run") as run_mock:
                    key = minimax_agent.get_api_key(None, CUSTOM_URL)

        self.assertIsNone(key)
        run_mock.assert_not_called()

    def test_custom_url_accepts_explicit_key_command(self):
        completed = subprocess.CompletedProcess([], 0, "provider-secret\n", "")
        with mock.patch.object(minimax_agent.subprocess, "run", return_value=completed) as run_mock:
            key = minimax_agent.get_api_key("provider-key-helper", CUSTOM_URL)

        self.assertEqual(key, "provider-secret")
        run_mock.assert_called_once_with(
            "provider-key-helper", shell=True, capture_output=True, text=True
        )

    def test_default_url_keeps_environment_fallback(self):
        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-secret"}, clear=True):
            with mock.patch.object(minimax_agent.subprocess, "run") as run_mock:
                key = minimax_agent.get_api_key(None, minimax_agent.DEFAULT_BASE_URL)

        self.assertEqual(key, "minimax-secret")
        run_mock.assert_not_called()

    def test_keychain_lookup_filters_service_and_login_account(self):
        completed = subprocess.CompletedProcess([], 0, "account-specific-secret\n", "")
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(minimax_agent.sys, "platform", "darwin"):
                with mock.patch.object(
                    minimax_agent, "get_keychain_account", return_value="test-account"
                ):
                    with mock.patch.object(
                        minimax_agent.subprocess, "run", return_value=completed
                    ) as run_mock:
                        key = minimax_agent.get_api_key(None, minimax_agent.DEFAULT_BASE_URL)

        self.assertEqual(key, "account-specific-secret")
        run_mock.assert_called_once_with(
            [
                "security",
                "find-generic-password",
                "-a",
                "test-account",
                "-s",
                minimax_agent.DEFAULT_KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
        )

    def test_main_stops_custom_url_before_agent_run_with_implicit_key(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_custom_url_") as td:
            with mock.patch.dict(
                os.environ, {"MINIMAX_API_KEY": "minimax-secret"}, clear=True
            ):
                with mock.patch.object(minimax_agent, "run") as agent_run:
                    result = minimax_agent.main(
                        ["--dir", td, "--base-url", CUSTOM_URL, "synthetic task"]
                    )

        self.assertEqual(result, 2)
        agent_run.assert_not_called()


class TemporaryConfigTests(unittest.TestCase):
    def test_config_is_private_and_removed_after_normal_exit(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_test_") as td:
            home = Path(td) / "run-home"

            def inspect_run(_cmd, env, _timeout, _retries):
                cfg_path = Path(env["OPENCODE_CONFIG"])
                self.assertEqual(stat.S_IMODE(cfg_path.parent.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(cfg_path.stat().st_mode), 0o600)
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    cfg["provider"]["minimax"]["options"]["apiKey"], "synthetic-key"
                )
                return 0

            with mock.patch.object(minimax_agent.tempfile, "mkdtemp", return_value=str(home)):
                with mock.patch.object(
                    minimax_agent, "run_with_timeout", side_effect=inspect_run
                ):
                    result = minimax_agent.run(
                        "synthetic task",
                        td,
                        "synthetic-key",
                        model=minimax_agent.DEFAULT_MODEL,
                        base_url=minimax_agent.DEFAULT_BASE_URL,
                        context=minimax_agent.DEFAULT_CONTEXT,
                        max_output=minimax_agent.DEFAULT_MAX_OUTPUT,
                        system_prompt=None,
                        timeout=1,
                        retries=0,
                        sandbox=False,
                    )

            self.assertEqual(result, 0)
            self.assertFalse(home.exists())

    def test_custom_provider_child_environment_excludes_minimax_key(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_custom_env_") as td:
            home = Path(td) / "run-home"

            def inspect_run(_cmd, env, _timeout, _retries):
                self.assertNotIn("MINIMAX_API_KEY", env)
                cfg = json.loads(Path(env["OPENCODE_CONFIG"]).read_text(encoding="utf-8"))
                self.assertEqual(
                    cfg["provider"]["minimax"]["options"]["apiKey"], "provider-key"
                )
                return 0

            with mock.patch.dict(
                os.environ, {"MINIMAX_API_KEY": "must-not-reach-child"}, clear=False
            ):
                with mock.patch.object(
                    minimax_agent.tempfile, "mkdtemp", return_value=str(home)
                ):
                    with mock.patch.object(
                        minimax_agent, "run_with_timeout", side_effect=inspect_run
                    ):
                        result = minimax_agent.run(
                            "synthetic task",
                            td,
                            "provider-key",
                            model=minimax_agent.DEFAULT_MODEL,
                            base_url=CUSTOM_URL,
                            context=minimax_agent.DEFAULT_CONTEXT,
                            max_output=minimax_agent.DEFAULT_MAX_OUTPUT,
                            system_prompt=None,
                            timeout=1,
                            retries=0,
                            sandbox=False,
                        )

            self.assertEqual(result, 0)
            self.assertFalse(home.exists())


class DocumentationTests(unittest.TestCase):
    def test_keychain_docs_disclose_temporary_plaintext_and_crash_remainder(self):
        english = (REPO / "README.md").read_text(encoding="utf-8")
        german = (REPO / "README.de.md").read_text(encoding="utf-8")

        self.assertIn("opencode-minimax-*", english)
        self.assertIn("hard crash", english)
        self.assertIn("opencode-minimax-*", german)
        self.assertIn("harter Abbruch", german)

    def test_ready_snippets_branch_between_macos_and_linux(self):
        snippets = [
            (REPO / "examples/assistant-instructions.md").read_text(encoding="utf-8"),
            (REPO / "README.md").read_text(encoding="utf-8"),
            (REPO / "README.de.md").read_text(encoding="utf-8"),
        ]
        for text in snippets:
            self.assertIn("macOS", text)
            self.assertIn("Linux", text)
            self.assertIn("bubblewrap", text)
            self.assertIn("firejail", text)


if __name__ == "__main__":
    unittest.main()
