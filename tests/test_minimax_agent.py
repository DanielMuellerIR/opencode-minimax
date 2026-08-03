"""Isolierte Regressionstests für Key-Auflösung, Temp-Konfiguration und Doku."""

import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
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


def _squash(text):
    """Fasst jede Folge von Leerzeichen/Umbruechen zu einem Leerzeichen zusammen.

    So pruefen die Doku-Tests den Wortlaut und nicht den Zeilenumbruch.
    """
    return re.sub(r"\s+", " ", text)


def _marker():
    """Eindeutiges Erkennungswort fuer die Prozesse EINES Testlaufs.

    Alle Prozess-Tests suchen und beenden ausschliesslich Prozesse, deren
    Kommandozeile dieses Wort enthaelt — also nur ihre eigenen Hilfsprozesse.
    """
    return "opencode-minimax-selftest-" + uuid.uuid4().hex


def _own_pids(marker):
    """PIDs der eigenen Hilfsprozesse zu diesem Marker (leer, wenn keiner mehr laeuft)."""
    found = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    return [int(pid) for pid in found.stdout.split()]


def _kill_own(marker):
    """Notbremse fuer den Aufraeumpfad der Tests: beendet nur die eigenen Hilfsprozesse."""
    for pid in _own_pids(marker):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _wait_until(predicate, seconds=30.0, step=0.05):
    """Wartet, bis predicate() zutrifft; gibt zurueck, ob das rechtzeitig geschah."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return bool(predicate())


class _CapturedStream:
    """Ersatz fuer sys.stdout: faengt die durchgereichte Kindausgabe im Test ab."""

    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, text):
        self.buffer.write(text.encode("utf-8", "replace"))

    def flush(self):
        pass


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


class SandboxConfinementTests(unittest.TestCase):
    """Die Sandbox darf nur das Arbeitsverzeichnis und das eigene Temp-Home freigeben."""

    def test_profile_allows_only_the_directories_it_is_given(self):
        profile = minimax_agent.build_seatbelt_profile(["/private/tmp/work-x",
                                                        "/private/tmp/home-y"])

        self.assertIn('(subpath "/private/tmp/work-x")', profile)
        self.assertIn('(subpath "/private/tmp/home-y")', profile)
        # Die gemeinsam genutzten Temp-Verzeichnisse des Kontos bleiben zu: sonst koennte
        # ein eingesperrter Lauf die Temp- und Cache-Dateien anderer Prozesse aendern.
        for shared in ('(subpath "/private/tmp")',
                       '(subpath "/private/var/tmp")',
                       '(subpath "/private/var/folders")'):
            self.assertNotIn(shared + "\n", profile)

    @unittest.skipUnless(sys.platform == "darwin", "seatbelt gibt es nur auf macOS")
    def test_sandbox_exec_blocks_writes_outside_the_work_dir(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_sandbox_") as td:
            work = Path(td) / "work"
            work.mkdir()
            outside = Path(td) / "outside"  # Nachbarverzeichnis im selben System-Temp
            outside.mkdir()
            profile = Path(td) / "profile.sb"
            profile.write_text(
                minimax_agent.build_seatbelt_profile([os.path.realpath(work)]))

            allowed = subprocess.run(
                ["sandbox-exec", "-f", str(profile), "/usr/bin/touch", str(work / "ok")],
                capture_output=True, text=True)
            denied = subprocess.run(
                ["sandbox-exec", "-f", str(profile), "/usr/bin/touch", str(outside / "no")],
                capture_output=True, text=True)

            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertNotEqual(denied.returncode, 0)
            self.assertFalse((outside / "no").exists())

    def test_run_points_tool_scratch_files_at_the_run_home(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_scratch_") as td:
            home = Path(td) / "run-home"

            def inspect_run(_cmd, env, _timeout, _retries):
                scratch = Path(env["TMPDIR"])
                self.assertEqual(env["TMP"], env["TMPDIR"])
                self.assertEqual(env["TEMP"], env["TMPDIR"])
                self.assertEqual(scratch.parent, home)  # innerhalb des Lauf-Temp-Homes
                self.assertTrue(scratch.is_dir())
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


class TimeoutSemanticsTests(unittest.TestCase):
    """`--timeout` begrenzt Stille, nicht die Gesamtlaufzeit.

    Die Tests rufen `run_with_timeout` mit kurzen Python-Hilfsprozessen auf — kein
    OpenCode, keine API. Der Zaehlpfad ist eine Datei, in die jeder Versuch ein
    Zeichen anhaengt; daran ist ablesbar, wie oft neu gestartet wurde.
    """

    def _helper(self, body):
        return [sys.executable, "-c", body]

    def test_long_run_with_output_survives_the_timeout(self):
        # Laeuft rund 3 Sekunden bei 1 Sekunde Timeout, meldet sich aber laufend.
        body = (
            "import sys, time\n"
            "for _ in range(12):\n"
            "    sys.stdout.write('working\\n'); sys.stdout.flush(); time.sleep(0.25)\n"
        )
        with mock.patch.object(minimax_agent.sys, "stdout", _CapturedStream()) as out:
            rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 1)

        self.assertEqual(rc, 0)
        self.assertIn(b"working", out.buffer.getvalue())  # Ausgabe wird durchgereicht

    def test_silent_start_is_killed_and_retried(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_stall_") as td:
            attempts = Path(td) / "attempts"
            body = (
                "import time\n"
                "open(%r, 'a').write('x')\n"
                "time.sleep(60)\n" % str(attempts)
            )
            rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 1)

            self.assertEqual(rc, 124)
            self.assertEqual(attempts.read_text(), "xx")  # Start-Haenger: genau ein Neustart

    def test_stall_after_first_output_is_not_retried(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_progress_") as td:
            attempts = Path(td) / "attempts"
            body = (
                "import sys, time\n"
                "open(%r, 'a').write('x')\n"
                "sys.stdout.write('session started\\n'); sys.stdout.flush()\n"
                "time.sleep(60)\n" % str(attempts)
            )
            with mock.patch.object(minimax_agent.sys, "stdout", _CapturedStream()):
                rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 1)

            self.assertEqual(rc, 124)
            # Der Lauf hat bereits gearbeitet; ein zweiter Versuch wuerde auf einem
            # halbfertigen Arbeitsverzeichnis aufsetzen und unterbleibt deshalb.
            self.assertEqual(attempts.read_text(), "x")

    def test_timeout_kills_the_whole_process_group(self):
        marker = _marker()
        body = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', %r])\n"
            "time.sleep(60)\n" % (marker + "-grandchild")
        )
        try:
            rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 0)

            self.assertEqual(rc, 124)
            self.assertTrue(_wait_until(lambda: not _own_pids(marker)),
                            "Enkelprozess lief nach dem Timeout weiter")
        finally:
            _kill_own(marker)


class ProcessLifecycleTests(unittest.TestCase):
    """Abbruch per Signal: kein weiterlaufendes OpenCode, kein liegengebliebener Key.

    Statt OpenCode steht ein winziges Skript gleichen Namens im PATH des Wrappers;
    es ahmt nur das Prozessverhalten nach (Enkelkind starten, dann warten).
    """

    def _start_wrapper(self, td, marker):
        bindir = Path(td) / "bin"
        bindir.mkdir()
        fake = bindir / "opencode"
        fake.write_text(
            "#!/bin/sh\n"
            "# Kein echtes OpenCode: startet ein Enkelkind und wartet, bis es getoetet wird.\n"
            "# Die Wartezeit ist bewusst viel laenger als jede Testschranke, damit ein\n"
            "# planmaessiges Ende des Hilfsprozesses nicht mit dem Kill verwechselt wird.\n"
            "%s -c 'import time; time.sleep(900)' %s-grandchild &\n"
            "echo fake-opencode-running\n"
            "sleep 900\n" % (sys.executable, marker)
        )
        fake.chmod(0o755)
        work = Path(td) / "work"
        work.mkdir()
        tmp = Path(td) / "tmp"  # eigenes TMPDIR, damit das Temp-Home pruefbar ist
        tmp.mkdir()
        env = dict(
            os.environ,
            PATH="%s:%s" % (bindir, os.environ.get("PATH", "")),
            MINIMAX_API_KEY="synthetic-key",
            TMPDIR=str(tmp),
        )
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "minimax_agent.py"), "--dir", str(work), marker],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc, tmp

    def _assert_clean_abort(self, sig, expected_code):
        marker = _marker()
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_signal_") as td:
            proc, tmp = self._start_wrapper(td, marker)
            try:
                self.assertTrue(_wait_until(lambda: _own_pids(marker + "-grandchild")),
                                "Der gefaelschte OpenCode-Lauf kam nicht hoch")
                proc.send_signal(sig)
                proc.wait(timeout=30)  # wartet nur auf den Wrapper, nicht auf die Pipes

                self.assertEqual(proc.returncode, expected_code)
                self.assertTrue(_wait_until(lambda: not _own_pids(marker), 20),
                                "Prozessgruppe lief nach %s weiter" % sig)
                self.assertEqual([p.name for p in tmp.glob("opencode-minimax-*")], [],
                                 "Temp-Home mit dem Key blieb nach %s liegen" % sig)
            finally:
                _kill_own(marker)
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=30)
                for pipe in (proc.stdout, proc.stderr):
                    pipe.close()

    def test_sigterm_kills_opencode_and_removes_the_key_directory(self):
        self._assert_clean_abort(signal.SIGTERM, 128 + int(signal.SIGTERM))

    def test_sigint_kills_opencode_and_removes_the_key_directory(self):
        self._assert_clean_abort(signal.SIGINT, 130)

    def test_normal_exit_removes_the_key_directory(self):
        marker = _marker()
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_normal_") as td:
            bindir = Path(td) / "bin"
            bindir.mkdir()
            fake = bindir / "opencode"
            fake.write_text("#!/bin/sh\necho fake-opencode-done\n")  # endet sofort
            fake.chmod(0o755)
            work = Path(td) / "work"
            work.mkdir()
            tmp = Path(td) / "tmp"
            tmp.mkdir()
            env = dict(
                os.environ,
                PATH="%s:%s" % (bindir, os.environ.get("PATH", "")),
                MINIMAX_API_KEY="synthetic-key",
                TMPDIR=str(tmp),
            )
            proc = subprocess.run(
                [sys.executable, str(REPO / "minimax_agent.py"), "--dir", str(work), marker],
                env=env, capture_output=True, text=True, check=False)

            self.assertEqual(proc.returncode, 0)
            self.assertIn("fake-opencode-done", proc.stdout)  # Ausgabe kommt durch
            self.assertEqual([p.name for p in tmp.glob("opencode-minimax-*")], [])


class DocumentationTests(unittest.TestCase):
    """Prueft die zugesagten Aussagen selbst, nicht nur einzelne Stichwoerter.

    Alle Vergleiche laufen ueber `_squash`, damit ein anderer Zeilenumbruch im
    Fliesstext keinen Fehlalarm ausloest — der Wortlaut muss stimmen, die
    Formatierung darf sich aendern.
    """

    def test_keychain_docs_disclose_the_full_security_promise(self):
        english = _squash((REPO / "README.md").read_text(encoding="utf-8"))
        german = _squash((REPO / "README.de.md").read_text(encoding="utf-8"))

        # Der Key liegt waehrend des Laufs im Klartext auf der Platte: Ablageort,
        # Rechte, Aufraeumen und die Grenze des Aufraeumens muessen dastehen.
        for phrase in ("in clear text", "mode-`0600` `config.json`",
                       "mode-`0700` system-temp directory named `opencode-minimax-*`",
                       "Ctrl-C, `SIGTERM` or `SIGHUP`", "A hard crash, `SIGKILL`, or power "
                       "loss can leave the temporary copy behind"):
            self.assertIn(phrase, english)
        for phrase in ("im Klartext", "`config.json` mit Modus `0600`",
                       "Modus `0700` und Namen `opencode-minimax-*`",
                       "Strg-C, `SIGTERM` oder `SIGHUP`",
                       "Ein harter Abbruch, `SIGKILL` oder Stromausfall kann die temporäre "
                       "Kopie zurücklassen"):
            self.assertIn(phrase, german)

    def test_ready_snippets_branch_between_macos_and_linux(self):
        for name in ("examples/assistant-instructions.md", "README.md", "README.de.md"):
            text = _squash((REPO / name).read_text(encoding="utf-8"))
            with self.subTest(name):
                # Der macOS-Aufruf MIT --sandbox ...
                self.assertRegex(
                    text, r"macOS:\s*`?python3 \S*minimax_agent\.py --dir <wt> --sandbox")
                # ... und daneben der Aufruf OHNE --sandbox fuer alle anderen Systeme.
                self.assertRegex(
                    text, r"Linux/(non|Nicht)-macOS:[^.]*(without|ohne) `?--sandbox")
                self.assertIn("bubblewrap", text)
                self.assertIn("firejail", text)

    def test_advertised_entry_points_do_not_force_sandbox_on_other_systems(self):
        """Jeder beworbene Copy-and-paste-Einstieg muss auf Nicht-macOS laufen."""
        for name in ("examples/run-demo.sh", "examples/review-repo.sh"):
            script = (REPO / name).read_text(encoding="utf-8")
            calls = [line.strip() for line in script.splitlines()
                     if "minimax_agent.py" in line and not line.strip().startswith("#")]
            with self.subTest(name):
                self.assertIn('uname -s', script)          # Verzweigung nach Plattform
                self.assertEqual(len(calls), 2, calls)     # je ein Zweig
                self.assertEqual([("--sandbox" in c) for c in calls].count(True), 1, calls)

        for brief in sorted((REPO / "examples/briefs").glob("*.md")):
            text = brief.read_text(encoding="utf-8")
            with self.subTest(brief.name):
                if "--sandbox" in text:
                    self.assertIn("`--sandbox` is macOS-only", _squash(text))

    def test_review_example_does_not_overpromise_isolation(self):
        script = (REPO / "examples/review-repo.sh").read_text(encoding="utf-8")

        # Der Wegwerf-Worktree teilt sein Git-Verzeichnis mit dem Original; ohne
        # Sandbox ist "kann physisch nichts aendern" schlicht falsch.
        self.assertNotIn("physically cannot", script)
        self.assertIn("shares its git directory", _squash(script))


if __name__ == "__main__":
    unittest.main()
