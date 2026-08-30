"""Isolierte Regressionstests für Key-Auflösung, Temp-Konfiguration und Doku."""

import io
import json
import os
import re
import shlex
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


def _pid_file(marker):
    return Path(tempfile.gettempdir()) / (marker + ".pid")


def _own_pids(marker):
    """Prueft die von den Hilfsprozessen selbst geschriebenen PIDs ohne externes pgrep."""
    result = []
    pattern = marker + "*.pid"
    for path in Path(tempfile.gettempdir()).glob(pattern):
        try:
            pid = int(path.read_text(encoding="ascii"))
            os.kill(pid, 0)
        except (OSError, ValueError):
            continue
        result.append(pid)
    return result


def _kill_own(marker):
    """Notbremse fuer den Aufraeumpfad der Tests: beendet nur die eigenen Hilfsprozesse."""
    for pid in _own_pids(marker):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for path in Path(tempfile.gettempdir()).glob(marker + "*.pid"):
        try:
            path.unlink()
        except FileNotFoundError:
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


class _BrokenStream:
    """Ausgabesenke, deren Binärstrom wie eine abgerissene Pipe reagiert."""

    class _Buffer:
        def write(self, _data):
            raise BrokenPipeError("synthetic closed sink")

        def flush(self):
            pass

    def __init__(self):
        self.buffer = self._Buffer()


class ApiKeyResolutionTests(unittest.TestCase):
    def test_custom_url_rejects_implicit_minimax_environment_key(self):
        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-secret"}, clear=True):
            with mock.patch.object(minimax_agent.sys, "platform", "darwin"):
                with mock.patch.object(minimax_agent.subprocess, "run") as run_mock:
                    key = minimax_agent.get_api_key(None, CUSTOM_URL)

        self.assertIsNone(key)
        run_mock.assert_not_called()

    def test_custom_url_accepts_explicit_key_command(self):
        proc = mock.Mock()
        proc.communicate.return_value = ("provider-secret\n", "")
        proc.returncode = 0
        with mock.patch.object(minimax_agent.subprocess, "Popen", return_value=proc) as popen:
            key = minimax_agent.get_api_key("provider-key-helper", CUSTOM_URL)

        self.assertEqual(key, "provider-secret")
        popen.assert_called_once_with(
            "provider-key-helper", shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        proc.communicate.assert_called_once_with(timeout=minimax_agent.KEY_COMMAND_TIMEOUT)

    def test_failed_key_command_never_falls_back_to_environment(self):
        proc = mock.Mock()
        proc.communicate.return_value = ("not-a-key\n", "secret diagnostic\n")
        proc.returncode = 3
        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "fallback-secret"}, clear=True):
            with mock.patch.object(minimax_agent.subprocess, "Popen", return_value=proc):
                with mock.patch.object(minimax_agent.sys, "stderr", io.StringIO()) as error:
                    key = minimax_agent.get_api_key("provider-key-helper")

        self.assertIsNone(key)
        self.assertNotIn("secret diagnostic", error.getvalue())
        self.assertIn("exit code 3", error.getvalue())

    def test_key_command_rejects_multiple_output_lines(self):
        proc = mock.Mock()
        proc.communicate.return_value = ("warning\nprovider-secret\n", "")
        proc.returncode = 0
        with mock.patch.object(minimax_agent.subprocess, "Popen", return_value=proc):
            key = minimax_agent.get_api_key("provider-key-helper")

        self.assertIsNone(key)

    def test_key_command_timeout_is_a_hard_failure(self):
        proc = mock.Mock()
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired("provider-key-helper", 30), ("", "")
        ]
        with mock.patch.object(minimax_agent.subprocess, "Popen", return_value=proc):
            with mock.patch.object(minimax_agent, "kill_process_group") as kill_group:
                key = minimax_agent.get_api_key("provider-key-helper")

        self.assertIsNone(key)
        kill_group.assert_called_once_with(proc)
        self.assertEqual(proc.communicate.call_count, 2)

    def test_key_command_timeout_kills_its_descendants(self):
        marker = _marker()
        pidfile = _pid_file(marker + "-key-helper")
        child = (
            "import os,sys,time; open(sys.argv[1], 'w').write(str(os.getpid())); "
            "time.sleep(60)"
        )
        parent = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable, '-c', %r, %r]); time.sleep(60)"
            % (child, str(pidfile))
        )
        command = "%s -c %s" % (shlex.quote(sys.executable), shlex.quote(parent))
        try:
            with mock.patch.object(minimax_agent, "KEY_COMMAND_TIMEOUT", 0.2):
                key = minimax_agent.get_api_key(command)

            self.assertIsNone(key)
            self.assertTrue(pidfile.exists(), "Key-Hilfsprozess startete nicht")
            self.assertTrue(_wait_until(lambda: not _own_pids(marker), 5),
                            "Key-Hilfsprozess lief nach dem Timeout weiter")
        finally:
            _kill_own(marker)

    def test_default_url_keeps_environment_fallback(self):
        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-secret"}, clear=True):
            with mock.patch.object(minimax_agent.subprocess, "run") as run_mock:
                key = minimax_agent.get_api_key(None, minimax_agent.DEFAULT_BASE_URL)

        self.assertEqual(key, "minimax-secret")
        run_mock.assert_not_called()

    def test_default_url_with_trailing_slash_keeps_environment_fallback(self):
        with mock.patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-secret"}, clear=True):
            key = minimax_agent.get_api_key(None, minimax_agent.DEFAULT_BASE_URL + "/")

        self.assertEqual(key, "minimax-secret")

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
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_custom_url_") as td:
            with mock.patch.dict(
                os.environ, {"MINIMAX_API_KEY": "minimax-secret"}, clear=True
            ):
                with mock.patch.object(minimax_agent.shutil, "which", return_value="/bin/true"):
                    with mock.patch.object(minimax_agent, "run") as agent_run:
                        result = minimax_agent.main(
                            ["--dir", td, "--base-url", CUSTOM_URL, "synthetic task"]
                        )

        self.assertEqual(result, 2)
        agent_run.assert_not_called()
        self.assertEqual(
            {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}, before
        )


class _RunStubMixin:
    def _run_with_stub(self, root, inspect, **overrides):
        key = overrides.pop("key", "synthetic-key")
        options = {
            "model": minimax_agent.DEFAULT_MODEL,
            "base_url": minimax_agent.DEFAULT_BASE_URL,
            "context": minimax_agent.DEFAULT_CONTEXT,
            "max_output": minimax_agent.DEFAULT_MAX_OUTPUT,
            "system_prompt": None,
            "timeout": 1,
            "retries": 0,
            "sandbox": False,
        }
        options.update(overrides)
        with mock.patch.dict(os.environ, {"TMPDIR": str(root)}, clear=False):
            # tempfile caches its chosen directory. Reset the cache so this test's TMPDIR
            # produces a fresh, uniquely named opencode-minimax-* directory.
            with mock.patch.object(minimax_agent.tempfile, "tempdir", None):
                with mock.patch.object(
                    minimax_agent, "run_with_timeout", side_effect=inspect
                ):
                    result = minimax_agent.run(
                        "synthetic task", str(root), key, **options
                    )
        self.assertEqual(list(Path(root).glob("opencode-minimax-*")), [])
        return result


class TemporaryConfigTests(_RunStubMixin, unittest.TestCase):
    def test_config_is_private_and_removed_after_normal_exit(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_test_") as td:
            def inspect_run(_cmd, env, _timeout, _retries):
                cfg_path = Path(env["OPENCODE_CONFIG"])
                self.assertEqual(cfg_path.parent.parent, Path(td))
                self.assertEqual(stat.S_IMODE(cfg_path.parent.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(cfg_path.stat().st_mode), 0o600)
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    cfg["provider"]["minimax"]["options"]["apiKey"], "synthetic-key"
                )
                return 0

            result = self._run_with_stub(td, inspect_run)

            self.assertEqual(result, 0)

    def test_cleanup_recovers_from_permissions_changed_by_an_unsandboxed_child(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_cleanup_") as td:
            def inspect_run(_cmd, env, _timeout, _retries):
                cfg = Path(env["OPENCODE_CONFIG"])
                runtime = Path(env["XDG_DATA_HOME"]).parent
                (runtime / "state").mkdir(parents=True)
                (runtime / "state" / "child-data").write_text("leftover")
                os.chmod(runtime / "state", 0)
                os.chmod(runtime, 0)
                os.chmod(cfg.parent, 0)
                return 0

            result = self._run_with_stub(td, inspect_run)

        self.assertEqual(result, 0)

    def test_cleanup_failure_changes_a_successful_run_to_an_error(self):
        real_remove = minimax_agent.remove_temp_home
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_cleanup_error_") as td:
            def inspect_run(_cmd, _env, _timeout, _retries):
                return 0

            def remove_but_report_failure(path):
                real_remove(path)
                return False

            with mock.patch.object(
                minimax_agent, "remove_temp_home", side_effect=remove_but_report_failure
            ):
                result = self._run_with_stub(td, inspect_run)

        self.assertEqual(result, 2)

    def test_custom_provider_child_environment_excludes_minimax_key(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_custom_env_") as td:
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
                result = self._run_with_stub(
                    td, inspect_run, key="provider-key", base_url=CUSTOM_URL
                )

            self.assertEqual(result, 0)


class SandboxConfinementTests(_RunStubMixin, unittest.TestCase):
    """Die Sandbox darf nur das Arbeitsverzeichnis und das eigene Temp-Home freigeben."""

    def _require_working_sandbox_exec(self):
        probe = subprocess.run(
            ["sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"],
            capture_output=True, text=True,
        )
        if probe.returncode == 71:
            self.skipTest("der aufrufende Runner verbietet verschachteltes sandbox_apply")
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_profile_allows_only_the_directories_it_is_given(self):
        profile = minimax_agent.build_seatbelt_profile(["/private/tmp/work-x",
                                                        "/private/tmp/home-y"])

        self.assertIn("(allow default)", profile)
        self.assertIn("(deny file-write*)", profile)
        subpaths = [line.strip() for line in profile.splitlines()
                    if line.strip().startswith("(subpath ")]
        self.assertEqual(subpaths, [
            '(subpath "/private/tmp/work-x")',
            '(subpath "/private/tmp/home-y")',
            '(subpath "/dev/fd")',
        ])
        # Die gemeinsam genutzten Temp-Verzeichnisse des Kontos bleiben zu: sonst koennte
        # ein eingesperrter Lauf die Temp- und Cache-Dateien anderer Prozesse aendern.
        for shared in ('(subpath "/private/tmp")',
                       '(subpath "/private/var/tmp")',
                       '(subpath "/private/var/folders")'):
            self.assertNotIn(shared, profile)

    def test_profile_quotes_paths_without_rule_injection(self):
        profile = minimax_agent.build_seatbelt_profile(['/tmp/a"b\\c'])

        self.assertIn('(subpath "/tmp/a\\"b\\\\c")', profile)
        with self.assertRaisesRegex(ValueError, "control characters"):
            minimax_agent.build_seatbelt_profile(["/tmp/bad\npath"])

    @unittest.skipUnless(sys.platform == "darwin", "seatbelt gibt es nur auf macOS")
    def test_sandbox_exec_blocks_writes_outside_the_work_dir(self):
        self._require_working_sandbox_exec()

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
            self.assertEqual(denied.returncode, 1, denied.stderr)
            self.assertIn("Operation not permitted", denied.stderr)
            self.assertFalse((outside / "no").exists())

    @unittest.skipUnless(sys.platform == "darwin", "seatbelt gibt es nur auf macOS")
    def test_sandbox_exec_accepts_quoted_and_backslashed_work_paths(self):
        self._require_working_sandbox_exec()
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_sandbox_quote_") as td:
            work = Path(td) / 'a"b\\c'
            work.mkdir()
            profile = Path(td) / "profile.sb"
            profile.write_text(
                minimax_agent.build_seatbelt_profile([os.path.realpath(work)])
            )

            allowed = subprocess.run(
                ["sandbox-exec", "-f", str(profile), "/usr/bin/touch", str(work / "ok")],
                capture_output=True, text=True,
            )

            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_run_passes_the_generated_profile_to_sandbox_exec(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_sandbox_cmd_") as td:
            def inspect_run(cmd, _env, _timeout, _retries):
                self.assertEqual(cmd[:2], ["sandbox-exec", "-f"])
                profile = Path(cmd[2]).read_text(encoding="utf-8")
                self.assertIn("(deny file-write*)", profile)
                self.assertEqual(cmd[3], "opencode")
                cfg = Path(_env["OPENCODE_CONFIG"])
                runtime = Path(_env["XDG_DATA_HOME"]).parent
                self.assertNotEqual(cfg.parent, runtime)
                self.assertIn('(subpath "%s")' % runtime.resolve(), profile)
                self.assertNotIn('(subpath "%s")' % cfg.parent.resolve(), profile)
                return 0

            with mock.patch.object(minimax_agent.sys, "platform", "darwin"):
                result = self._run_with_stub(td, inspect_run, sandbox=True)

        self.assertEqual(result, 0)

    def test_run_points_tool_scratch_files_at_the_run_home(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_scratch_") as td:
            def inspect_run(_cmd, env, _timeout, _retries):
                scratch = Path(env["TMPDIR"])
                self.assertEqual(env["TMP"], env["TMPDIR"])
                self.assertEqual(env["TEMP"], env["TMPDIR"])
                self.assertEqual(scratch.parent.parent.parent, Path(td))
                self.assertEqual(scratch.parent.name, "runtime")
                self.assertTrue(scratch.parent.parent.name.startswith("opencode-minimax-"))
                self.assertTrue(scratch.is_dir())
                return 0

            result = self._run_with_stub(td, inspect_run)

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

    def test_stderr_output_also_resets_the_silence_timer(self):
        body = (
            "import sys, time\n"
            "for _ in range(8):\n"
            "    sys.stderr.write('working\\n'); sys.stderr.flush(); time.sleep(0.25)\n"
        )
        with mock.patch.object(minimax_agent.sys, "stderr", _CapturedStream()) as err:
            rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 0)

        self.assertEqual(rc, 0)
        self.assertIn(b"working", err.buffer.getvalue())

    def test_broken_output_sink_does_not_create_a_false_silence_timeout(self):
        body = (
            "import sys, time\n"
            "for _ in range(8):\n"
            "    sys.stdout.write('working\\n'); sys.stdout.flush(); time.sleep(0.25)\n"
        )
        with mock.patch.object(minimax_agent.sys, "stdout", _BrokenStream()):
            rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 0)

        self.assertEqual(rc, 0)

    def test_text_only_output_stream_does_not_orphan_the_child(self):
        with mock.patch.object(minimax_agent.sys, "stdout", io.StringIO()) as out:
            rc = minimax_agent.run_with_timeout(
                self._helper("print('working', flush=True)"), os.environ.copy(), 2, 0
            )

        self.assertEqual(rc, 0)
        self.assertIn("working", out.getvalue())

    def test_normal_exit_does_not_wait_for_inherited_pipe_descriptors(self):
        marker = _marker()
        pidfile = _pid_file(marker + "-background")
        body = (
            "import subprocess, sys\n"
            "subprocess.Popen([sys.executable, '-c', "
            "'import os,sys,time; open(sys.argv[1], \\\"w\\\").write(str(os.getpid())); "
            "time.sleep(60)', %r])\n"
            "print('parent done', flush=True)\n" % str(pidfile)
        )
        started = time.monotonic()
        try:
            with mock.patch.object(minimax_agent.sys, "stdout", _CapturedStream()):
                rc = minimax_agent.run_with_timeout(
                    self._helper(body), os.environ.copy(), 5, 0
                )

            self.assertEqual(rc, 0)
            self.assertLess(time.monotonic() - started, 2)
            self.assertTrue(_wait_until(lambda: not _own_pids(marker), 5),
                            "Enkelprozess lief nach normalem Ende weiter")
        finally:
            _kill_own(marker)

    def test_timeout_does_not_wait_for_an_escaped_pipe_holder(self):
        marker = _marker()
        pidfile = _pid_file(marker + "-escaped")
        body = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', "
            "'import os,sys,time; os.setsid(); open(sys.argv[1], \\\"w\\\").write("
            "str(os.getpid())); time.sleep(60)', %r])\n"
            "print('session started', flush=True)\n"
            "time.sleep(60)\n" % str(pidfile)
        )
        started = time.monotonic()
        try:
            with mock.patch.object(minimax_agent.sys, "stdout", _CapturedStream()):
                rc = minimax_agent.run_with_timeout(
                    self._helper(body), os.environ.copy(), 1, 0
                )

            self.assertEqual(rc, 124)
            self.assertLess(time.monotonic() - started, 3)
        finally:
            _kill_own(marker)

    def test_default_silent_start_is_not_retried_after_a_possible_side_effect(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_stall_") as td:
            attempts = Path(td) / "attempts"
            body = (
                "import time\n"
                "open(%r, 'a').write('x')\n"
                "time.sleep(60)\n" % str(attempts)
            )
            rc = minimax_agent.run_with_timeout(
                self._helper(body), os.environ.copy(), 1, minimax_agent.DEFAULT_RETRIES
            )

            self.assertEqual(rc, 124)
            self.assertEqual(attempts.read_text(), "x")

    def test_explicit_retry_remains_available_for_side_effect_free_starts(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_retry_opt_in_") as td:
            attempts = Path(td) / "attempts"
            body = (
                "import time\n"
                "open(%r, 'a').write('x')\n"
                "time.sleep(60)\n" % str(attempts)
            )
            rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 1)

            self.assertEqual(rc, 124)
            self.assertEqual(attempts.read_text(), "xx")

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
        pidfile = _pid_file(marker + "-grandchild")
        body = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', "
            "'import os,sys,time; open(sys.argv[1], \\\"w\\\").write(str(os.getpid())); "
            "time.sleep(60)', %r])\n"
            "time.sleep(60)\n" % str(pidfile)
        )
        try:
            rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 1, 0)

            self.assertEqual(rc, 124)
            self.assertTrue(_wait_until(lambda: not _own_pids(marker)),
                            "Enkelprozess lief nach dem Timeout weiter")
        finally:
            _kill_own(marker)

    def test_signal_exit_is_reported_as_128_plus_signal(self):
        body = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"
        rc = minimax_agent.run_with_timeout(self._helper(body), os.environ.copy(), 5, 0)

        self.assertEqual(rc, 128 + int(signal.SIGKILL))

    def test_missing_executable_returns_a_plain_exit_code(self):
        rc = minimax_agent.run_with_timeout(
            ["definitely-missing-opencode-minimax-test"], os.environ.copy(), 5, 0
        )

        self.assertEqual(rc, 2)

    def test_finished_child_without_remaining_group_is_not_signalled_again(self):
        proc = mock.Mock()
        proc.poll.return_value = 0
        with mock.patch.object(
            minimax_agent.os, "killpg", side_effect=ProcessLookupError
        ) as killpg:
            minimax_agent.kill_process_group(proc, grace=0.01)

        killpg.assert_called_once_with(proc.pid, 0)

    def test_group_kill_escalates_past_an_exited_parent(self):
        marker = _marker()
        pidfile = _pid_file(marker + "-grandchild")
        body = (
            "import signal, subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', "
            "'import os,signal,sys,time; open(sys.argv[1], \\\"w\\\").write("
            "str(os.getpid())); signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(60)', %r])\n"
            "time.sleep(60)\n" % str(pidfile)
        )
        proc = subprocess.Popen(
            self._helper(body) + [marker], start_new_session=True
        )
        try:
            self.assertTrue(
                _wait_until(lambda: _own_pids(marker + "-grandchild"), 10),
                "SIGTERM ignorierender Enkelprozess startete nicht",
            )
            minimax_agent.kill_process_group(proc, grace=0.2)

            self.assertIsNotNone(proc.poll())
            self.assertTrue(
                _wait_until(lambda: not _own_pids(marker), 10),
                "Prozessgruppe lief nach der SIGKILL-Eskalation weiter",
            )
        finally:
            _kill_own(marker)
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)


class ProcessLifecycleTests(unittest.TestCase):
    """Abbruch per Signal: kein weiterlaufendes OpenCode, kein liegengebliebener Key.

    Statt OpenCode steht ein winziges Skript gleichen Namens im PATH des Wrappers;
    es ahmt nur das Prozessverhalten nach (Enkelkind starten, dann warten).
    """

    def _start_wrapper(self, td, task, fake_body=None):
        bindir = Path(td) / "bin"
        bindir.mkdir()
        fake = bindir / "opencode"
        if fake_body is None:
            grandchild_pidfile = _pid_file(task + "-grandchild")
            foreground_pidfile = _pid_file(task + "-foreground")
            fake_body = (
                "#!/bin/sh\n"
                "# Kein echtes OpenCode: startet zwei markierte Prozesse und wartet.\n"
                "%s -c 'import os,sys,time; open(sys.argv[1], \"w\").write(str(os.getpid())); time.sleep(900)' %s &\n"
                "echo fake-opencode-running\n"
                "exec %s -c 'import os,sys,time; open(sys.argv[1], \"w\").write(str(os.getpid())); time.sleep(900)' %s\n"
                % (sys.executable, grandchild_pidfile,
                   sys.executable, foreground_pidfile)
            )
        fake.write_text(fake_body)
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
            [sys.executable, str(REPO / "minimax_agent.py"), "--dir", str(work), task],
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

    @unittest.skipUnless(hasattr(signal, "SIGHUP"), "SIGHUP gibt es nicht auf dieser Plattform")
    def test_sighup_kills_opencode_and_removes_the_key_directory(self):
        self._assert_clean_abort(signal.SIGHUP, 128 + int(signal.SIGHUP))

    def test_normal_exit_removes_the_key_directory(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_normal_") as td:
            proc, tmp = self._start_wrapper(
                td, "synthetic task", "#!/bin/sh\necho fake-opencode-done\n"
            )
            try:
                stdout, _stderr = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
                self.fail("Wrapper blockierte nach dem normalen OpenCode-Ende")

            self.assertEqual(proc.returncode, 0)
            self.assertIn("fake-opencode-done", stdout)  # Ausgabe kommt durch
            self.assertEqual([p.name for p in tmp.glob("opencode-minimax-*")], [])


class CliValidationTests(unittest.TestCase):
    def test_invalid_numbers_are_rejected_before_starting_opencode(self):
        cases = (("--retries", "-1"), ("--timeout", "-1"),
                 ("--context", "0"), ("--max-output", "0"))
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_args_") as td:
            for flag, value in cases:
                with self.subTest(flag=flag):
                    with self.assertRaises(SystemExit) as raised:
                        minimax_agent.main(["--dir", td, flag, value, "synthetic task"])
                    self.assertEqual(raised.exception.code, 2)

    def test_missing_system_prompt_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_prompt_") as td:
            with self.assertRaises(SystemExit) as raised:
                minimax_agent.main([
                    "--dir", td, "--system-prompt", str(Path(td) / "missing.md"),
                    "synthetic task",
                ])

        self.assertEqual(raised.exception.code, 2)

    def test_root_and_home_are_rejected_as_work_directories(self):
        for path in (os.sep, os.path.expanduser("~")):
            with self.subTest(path=path):
                with self.assertRaises(SystemExit) as raised:
                    minimax_agent.main(["--dir", path, "synthetic task"])
                self.assertEqual(raised.exception.code, 2)

    def test_directory_validation_happens_before_reading_stdin(self):
        missing = str(REPO / "definitely-missing-work-directory")
        with mock.patch.object(minimax_agent.sys.stdin, "read") as read:
            with self.assertRaises(SystemExit):
                minimax_agent.main(["--dir", missing])

        read.assert_not_called()

    def test_missing_opencode_has_no_traceback(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_missing_bin_") as td:
            with mock.patch.object(minimax_agent.shutil, "which", return_value=None):
                result = minimax_agent.main(["--dir", td, "synthetic task"])

        self.assertEqual(result, 2)


class ExampleScriptTests(unittest.TestCase):
    def _fake_path(self, td, *, uname="Linux", uname_rc=0, python_rc=0):
        bindir = Path(td) / "fake-bin"
        bindir.mkdir()
        (bindir / "uname").write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$FAKE_UNAME\"\nexit \"$FAKE_UNAME_RC\"\n"
        )
        (bindir / "python3").write_text(
            "#!/bin/sh\n"
            "case \"${1-}\" in *'_show-worktree-changes.py') "
            "exec \"$FAKE_REAL_PYTHON\" \"$@\";; esac\n"
            "printf '%s\\n' \"$@\" > \"$FAKE_CAPTURE\"\n"
            "exit \"$FAKE_PYTHON_RC\"\n"
        )
        for helper in (bindir / "uname", bindir / "python3"):
            helper.chmod(0o755)
        capture = Path(td) / "python-args"
        env = dict(
            os.environ,
            PATH="%s:/usr/bin:/bin" % bindir,
            FAKE_UNAME=uname,
            FAKE_UNAME_RC=str(uname_rc),
            FAKE_CAPTURE=str(capture),
            FAKE_PYTHON_RC=str(python_rc),
            FAKE_REAL_PYTHON=sys.executable,
        )
        return env, capture

    def test_shared_launcher_adds_sandbox_only_on_darwin(self):
        launcher = REPO / "examples/_run-agent.sh"
        for uname, expected in (("Darwin", True), ("Linux", False)):
            with self.subTest(uname=uname):
                with tempfile.TemporaryDirectory(prefix="opencode_minimax_launcher_") as td:
                    env, capture = self._fake_path(td, uname=uname)
                    proc = subprocess.run(
                        [str(launcher), "--dir", "/tmp/project", "synthetic task"],
                        env=env, capture_output=True, text=True, timeout=10,
                    )

                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    args = capture.read_text(encoding="utf-8").splitlines()
                    self.assertEqual("--sandbox" in args, expected)

    def test_shared_launcher_fails_closed_when_uname_fails(self):
        launcher = REPO / "examples/_run-agent.sh"
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_uname_failure_") as td:
            env, capture = self._fake_path(td, uname="Darwin", uname_rc=1)
            proc = subprocess.run(
                [str(launcher), "--dir", "/tmp/project", "synthetic task"],
                env=env, capture_output=True, text=True, timeout=10,
            )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("could not determine", proc.stderr)
        self.assertFalse(capture.exists(), "agent started after platform detection failed")

    def test_fix_example_keeps_and_reports_partial_work_after_timeout(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_fix_script_") as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            (repo / "tracked.txt").write_text("base\n")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run([
                "git", "-C", str(repo), "-c", "user.name=Test",
                "-c", "user.email=test@example.invalid", "commit", "-qm", "base",
            ], check=True)
            env, _capture = self._fake_path(td, python_rc=124)
            proc = subprocess.run(
                [str(REPO / "examples/fix-in-sandbox.sh"), str(repo), "synthetic task"],
                env=env, capture_output=True, text=True, timeout=30,
            )

            self.assertEqual(proc.returncode, 124, proc.stderr)
            self.assertIn("inspect the partial work", proc.stdout)
            match = re.search(r"^Worktree: (.+)$", proc.stdout, re.MULTILINE)
            self.assertIsNotNone(match)
            worktree = Path(match.group(1))
            try:
                self.assertTrue(worktree.is_dir())
            finally:
                subprocess.run(
                    ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
                    check=False, capture_output=True,
                )
                try:
                    worktree.parent.rmdir()
                except OSError:
                    pass

    def test_fix_example_rejects_uncommitted_source_state(self):
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_dirty_script_") as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            (repo / "untracked.txt").write_text("dirty\n")
            env, capture = self._fake_path(td)
            proc = subprocess.run(
                [str(REPO / "examples/fix-in-sandbox.sh"), str(repo), "synthetic task"],
                env=env, capture_output=True, text=True, timeout=10,
            )

            self.assertEqual(proc.returncode, 2)
            self.assertIn("uncommitted changes", proc.stderr)
            self.assertFalse(capture.exists(), "agent launcher ran despite dirty source")

    def test_trusted_change_view_ignores_replaced_dot_git_and_lists_untracked_files(self):
        helper = REPO / "examples/_show-worktree-changes.py"
        with tempfile.TemporaryDirectory(prefix="opencode_minimax_safe_diff_") as td:
            repo = Path(td) / "repo"
            work = Path(td) / "work"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            (repo / "tracked.txt").write_text("base\n")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run([
                "git", "-C", str(repo), "-c", "user.name=Test",
                "-c", "user.email=test@example.invalid", "commit", "-qm", "base",
            ], check=True)
            base = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()
            git_dir = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"], text=True
            ).strip()
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "add", "-fq", str(work), "HEAD"],
                check=True,
            )
            (work / "tracked.txt").write_text("changed\n")
            (work / "new.txt").write_text("new\n")
            dot_git = work / ".git"
            dot_git.unlink()
            dot_git.mkdir()
            escaped = Path(td) / "escaped"
            evil = Path(td) / "evil.sh"
            evil.write_text("#!/bin/sh\ntouch \"$ESCAPED\"\n")
            evil.chmod(0o755)
            (dot_git / "config").write_text("[diff]\n\texternal = %s\n" % evil)
            subprocess.run(
                ["git", "-C", str(repo), "config", "diff.external", str(evil)], check=True
            )
            env = dict(os.environ, ESCAPED=str(escaped))

            proc = subprocess.run([
                sys.executable, str(helper), "--git-dir", git_dir,
                "--work-tree", str(work), "--base", base,
            ], env=env, capture_output=True, text=True, timeout=10)
            escaped_exists = escaped.exists()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("-base", proc.stdout)
        self.assertIn("+changed", proc.stdout)
        self.assertIn('"?? new.txt"', proc.stdout)
        self.assertFalse(escaped_exists, "agent-controlled external diff ran outside")

    def test_supervisor_forwards_sigterm_to_the_agent_child(self):
        marker = _marker()
        pidfile = _pid_file(marker)
        try:
            with tempfile.TemporaryDirectory(prefix="opencode_minimax_forward_signal_") as td:
                root = Path(td)
                launcher = root / "_run-agent.sh"
                launcher.write_text(
                    "#!/bin/sh\nexec %s -c 'import os,sys,time; "
                    "open(sys.argv[1], \"w\").write(str(os.getpid())); time.sleep(60)' %s\n"
                    % (sys.executable, pidfile)
                )
                launcher.chmod(0o755)
                driver = root / "driver.sh"
                driver.write_text(
                    "#!/usr/bin/env bash\nset -euo pipefail\n"
                    "here=%s\nsource %s\nrun_agent_supervised synthetic\n"
                    % (root, REPO / "examples/_example-lib.sh")
                )
                driver.chmod(0o755)
                proc = subprocess.Popen([str(driver)])
                self.assertTrue(_wait_until(lambda: _own_pids(marker), 10),
                                "Hilfsprozess startete nicht")
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=10)

                self.assertEqual(proc.returncode, 143)
                self.assertTrue(_wait_until(lambda: not _own_pids(marker), 5),
                                "Hilfsprozess lief nach SIGTERM weiter")
        finally:
            _kill_own(marker)


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
        canonical = _squash(
            (REPO / "examples/assistant-instructions.md").read_text(encoding="utf-8")
        )
        self.assertRegex(
            canonical, r"macOS:\s*`?python3 \S*minimax_agent\.py --dir <wt> --sandbox"
        )
        self.assertRegex(canonical, r"Linux/non-macOS:[^.]*without `?--sandbox")
        self.assertIn("bubblewrap", canonical)
        self.assertIn("firejail", canonical)
        for name in ("README.md", "README.de.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("examples/assistant-instructions.md", text)
                self.assertNotIn("## Delegating implementation to MiniMax", text)
                self.assertNotIn("## Implementierung an MiniMax delegieren", text)

    def test_advertised_entry_points_do_not_force_sandbox_on_other_systems(self):
        """Jeder beworbene Copy-and-paste-Einstieg muss auf Nicht-macOS laufen."""
        helper = (REPO / "examples/_run-agent.sh").read_text(encoding="utf-8")
        darwin = re.search(r'Darwin\)(.*?)Linux\)', helper, re.DOTALL)
        linux = re.search(r'Linux\)(.*?)\n  \*\)', helper, re.DOTALL)
        self.assertIsNotNone(darwin)
        self.assertIsNotNone(linux)
        self.assertIn("--sandbox", darwin.group(1))
        self.assertNotIn("--sandbox", linux.group(1))
        self.assertIn("could not determine the operating system", helper)

        scripts = sorted((REPO / "examples").glob("*.sh"))
        self.assertGreaterEqual(len(scripts), 4)
        common = (REPO / "examples/_example-lib.sh").read_text(encoding="utf-8")
        self.assertIn("_run-agent.sh", common)
        for script_path in scripts:
            if script_path.name in ("_run-agent.sh", "_example-lib.sh"):
                continue
            script = script_path.read_text(encoding="utf-8")
            with self.subTest(script=script_path.name):
                self.assertIn("_example-lib.sh", script)
                self.assertNotIn("minimax_agent.py", script)

        for brief in sorted((REPO / "examples/briefs").glob("*.md")):
            text = brief.read_text(encoding="utf-8")
            with self.subTest(brief.name):
                if brief.name == "README.md":
                    self.assertIn("`--sandbox` is macOS-only", _squash(text))
                else:
                    self.assertNotIn("minimax_agent.py", text)
                    self.assertNotIn("\n---\n", text)

    def test_review_example_does_not_overpromise_isolation(self):
        script = (REPO / "examples/review-repo.sh").read_text(encoding="utf-8")

        # Der Wegwerf-Worktree teilt sein Git-Verzeichnis mit dem Original; ohne
        # Sandbox ist "kann physisch nichts aendern" schlicht falsch.
        self.assertNotIn("physically cannot", script)
        self.assertIn("shares its git directory", _squash(script))
        self.assertIn("shared Git directory stays read-only", _squash(script))

    def test_cli_flags_and_security_boundaries_are_documented_in_both_languages(self):
        for name in ("README.md", "README.de.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                for flag in ("--timeout", "--retries", "--context", "--max-output",
                             "--system-prompt", "--variant"):
                    self.assertIn("| `%s` |" % flag, text)
                self.assertIn("DARWIN_USER_TEMP_DIR", text)
                self.assertIn("DARWIN_USER_CACHE_DIR", text)

    def test_all_documented_keychain_writes_update_existing_entries(self):
        for path in (REPO / "README.md", REPO / "README.de.md",
                     *sorted((REPO / "examples").glob("*.sh"))):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "security add-generic-password" in line:
                    with self.subTest(path=path.name, line=line):
                        self.assertIn(" -U ", line)

    def test_agent_structure_map_lists_code_tests_and_runtime_prompt(self):
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("[minimax_agent.py](minimax_agent.py)", agents)
        self.assertIn("`tests/`", agents)
        self.assertIn("Instruktionen, die der Wrapper", agents)


if __name__ == "__main__":
    unittest.main()
