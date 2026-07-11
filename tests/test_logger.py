"""Tests for src/logger.py — in-memory log, listeners, file output, export."""

import os

from src.logger import AppLogger, LogCategory, LogEntry


class TestAppLogger:
    def test_log_and_get_entries(self):
        log = AppLogger()
        log.info("hello", "world")
        log.error("bad")
        entries = log.get_entries()
        assert len(entries) == 2
        assert entries[0].category == LogCategory.INFO
        assert entries[0].message == "hello"
        assert entries[0].details == "world"
        assert entries[1].category == LogCategory.ERROR

    def test_get_entries_count(self):
        log = AppLogger()
        for i in range(10):
            log.info(f"m{i}")
        last3 = log.get_entries(3)
        assert [e.message for e in last3] == ["m7", "m8", "m9"]

    def test_max_entries_trim(self):
        log = AppLogger(max_entries=5)
        for i in range(12):
            log.info(f"m{i}")
        entries = log.get_entries()
        assert len(entries) == 5
        assert entries[0].message == "m7"

    def test_convenience_categories(self):
        log = AppLogger()
        log.match("m"); log.mismatch("mm"); log.click("c"); log.warning("w")
        cats = [e.category for e in log.get_entries()]
        assert cats == [LogCategory.SCREEN_MATCH, LogCategory.SCREEN_MISMATCH,
                        LogCategory.CLICK_EXECUTED, LogCategory.WARNING]

    def test_listener_fires_and_errors_are_swallowed(self):
        log = AppLogger()
        seen = []

        def bad_listener(entry):
            raise RuntimeError("boom")

        log.add_listener(bad_listener)
        log.add_listener(lambda e: seen.append(e.message))
        log.info("ping")  # must not raise despite bad listener
        assert seen == ["ping"]
        log.remove_listener(bad_listener)
        log.info("pong")
        assert seen == ["ping", "pong"]

    def test_entry_format(self):
        log = AppLogger()
        log.info("msg", "det")
        line = log.get_entries()[0].format()
        assert "[INFO" in line and "msg" in line and "| det" in line

    def test_clear(self):
        log = AppLogger()
        log.info("x")
        log.clear()
        assert log.get_entries() == []

    def test_export(self, tmp_path):
        log = AppLogger()
        log.info("alpha")
        log.error("beta")
        out = tmp_path / "out.txt"
        log.export(str(out))
        content = out.read_text()
        assert "alpha" in content and "beta" in content

    def test_file_logging_writes(self, tmp_path):
        d = str(tmp_path / "logs")
        log = AppLogger(log_dir=d)
        log.info("persisted line")
        files = os.listdir(d)
        assert len(files) == 1
        content = open(os.path.join(d, files[0])).read()
        assert "persisted line" in content

    def test_two_instances_do_not_cross_write(self, tmp_path):
        """Regression: shared logger name used to duplicate writes across files."""
        d1, d2 = str(tmp_path / "l1"), str(tmp_path / "l2")
        log1 = AppLogger(log_dir=d1)
        log2 = AppLogger(log_dir=d2)
        log2.info("only-in-two")
        f1 = os.path.join(d1, os.listdir(d1)[0])
        f2 = os.path.join(d2, os.listdir(d2)[0])
        assert "only-in-two" not in open(f1).read()
        content2 = open(f2).read()
        assert content2.count("only-in-two") == 1
