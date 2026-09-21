"""Observability tests must run without importing pygame or opening a display."""

import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from go_game.observability import configure_logging


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.logger = configure_logging(stream=self.output, log_file="")

    def tearDown(self):
        for handler in tuple(self.logger.handlers):
            if getattr(handler, "_go_game_owned", False):
                self.logger.removeHandler(handler)
                handler.close()

    def test_json_output_contains_event_fields(self):
        configure_logging(stream=self.output, format_name="json", log_file="")
        logging.getLogger("go_game.app").info(
            "Human played", extra={
                "event": "game.move", "game_id": "abc123", "turn": "X", "move": (1, 2),
            },
        )
        record = json.loads(self.output.getvalue().splitlines()[-1])
        self.assertEqual(record["event"], "game.move")
        self.assertEqual(record["game_id"], "abc123")
        self.assertEqual(record["turn"], "X")
        self.assertEqual(record["move"], [1, 2])
        self.assertEqual(record["level"], "INFO")
        self.assertTrue(record["timestamp"].endswith("Z"))

    def test_reconfiguration_does_not_duplicate_handlers(self):
        configure_logging(stream=self.output, log_file="")
        configure_logging(stream=self.output, log_file="")
        self.assertEqual(len(self.logger.handlers), 1)
        self.logger.info("once")
        self.assertEqual(self.output.getvalue().count("once"), 1)

    def test_application_logging_does_not_reconfigure_root(self):
        root = logging.getLogger()
        original_handlers = tuple(root.handlers)
        original_level = root.level
        configure_logging(stream=self.output, log_file="", level="DEBUG")
        self.assertEqual(tuple(root.handlers), original_handlers)
        self.assertEqual(root.level, original_level)
        self.assertFalse(self.logger.propagate)
        self.assertEqual(self.logger.level, logging.DEBUG)

    def test_invalid_level_defaults_to_info(self):
        configure_logging(stream=self.output, log_file="", level="nonsense")
        self.assertEqual(self.logger.level, logging.INFO)

    def test_unwritable_file_falls_back_to_console(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = str(Path(directory) / "missing" / "game.log")
            configure_logging(stream=self.output, log_file=missing, format_name="json")
            self.assertEqual(len(self.logger.handlers), 1)
            record = json.loads(self.output.getvalue().splitlines()[-1])
            self.assertEqual(record["event"], "logging.file_unavailable")

    def test_rotating_file_receives_json_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.log"
            configure_logging(
                stream=self.output, log_file=str(path), format_name="json",
            )
            self.logger.warning("Diagnostic", extra={"event": "test.diagnostic"})
            for handler in self.logger.handlers:
                handler.flush()
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(record["event"], "test.diagnostic")

    def test_browser_disables_file_logging(self):
        with mock.patch("go_game.observability.logging.sys.platform", "emscripten"):
            configure_logging(stream=self.output, log_file="ignored.log", format_name="json")
        self.assertEqual(len(self.logger.handlers), 1)
        record = json.loads(self.output.getvalue().splitlines()[-1])
        self.assertEqual(record["event"], "logging.file_disabled")

    def test_exception_is_serialized_when_provided(self):
        configure_logging(stream=self.output, log_file="", format_name="json")
        try:
            raise ValueError("example failure")
        except ValueError:
            self.logger.exception("Expected failure", extra={"event": "test.error"})
        record = json.loads(self.output.getvalue().splitlines()[-1])
        self.assertIn("ValueError", record["exception"])


if __name__ == "__main__":
    unittest.main()
