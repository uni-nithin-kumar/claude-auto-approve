#!/usr/bin/env python3
"""Tests for claude_auto_approve classifiers and mode I/O."""

import sys
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
import claude_auto_approve as h


class TestReadMode(unittest.TestCase):
    def test_returns_default_when_file_missing(self):
        with patch.object(h, "MODE_FILE", Path("/nonexistent/.approve-mode")):
            self.assertEqual(h.read_mode(), "docs-write")

    def test_reads_valid_mode_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mode", delete=False) as f:
            f.write("read-only\n")
            tmp = Path(f.name)
        try:
            with patch.object(h, "MODE_FILE", tmp):
                self.assertEqual(h.read_mode(), "read-only")
        finally:
            tmp.unlink()

    def test_returns_default_for_unknown_mode_in_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mode", delete=False) as f:
            f.write("banana\n")
            tmp = Path(f.name)
        try:
            with patch.object(h, "MODE_FILE", tmp):
                self.assertEqual(h.read_mode(), "docs-write")
        finally:
            tmp.unlink()

    def test_all_valid_modes_round_trip(self):
        for mode in ("read-only", "docs-write", "force", "off"):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".mode", delete=False) as f:
                f.write(mode + "\n")
                tmp = Path(f.name)
            try:
                with patch.object(h, "MODE_FILE", tmp):
                    self.assertEqual(h.read_mode(), mode)
            finally:
                tmp.unlink()


class TestReadConfig(unittest.TestCase):
    def test_returns_empty_dict_when_missing(self):
        with patch.object(h, "CONFIG_FILE", Path("/nonexistent/config.json")):
            self.assertEqual(h.read_config(), {})

    def test_reads_safe_write_paths(self):
        config = {"safe_write_paths": ["~/projects", "/tmp"]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            tmp = Path(f.name)
        try:
            with patch.object(h, "CONFIG_FILE", tmp):
                result = h.read_config()
                self.assertEqual(result["safe_write_paths"], ["~/projects", "/tmp"])
        finally:
            tmp.unlink()


class TestGetSafeWritePaths(unittest.TestCase):
    def test_uses_defaults_when_config_empty(self):
        paths = h.get_safe_write_paths({})
        self.assertIn("/tmp", paths)
        self.assertTrue(any("workspace" in p for p in paths))

    def test_expands_tilde(self):
        paths = h.get_safe_write_paths({"safe_write_paths": ["~/myprojects"]})
        self.assertFalse(any(p.startswith("~") for p in paths))

    def test_uses_config_paths(self):
        paths = h.get_safe_write_paths({"safe_write_paths": ["/custom/path"]})
        self.assertIn("/custom/path", paths)


class TestIsPathSafe(unittest.TestCase):
    def test_tmp_is_safe(self):
        self.assertTrue(h.is_safe_path("/tmp/scratch.py", ["/tmp"]))

    def test_nested_path_is_safe(self):
        home = str(Path.home())
        self.assertTrue(h.is_safe_path(
            f"{home}/workspace/myrepo/main.py",
            [f"{home}/workspace"]
        ))

    def test_outside_safe_paths_is_not_safe(self):
        self.assertFalse(h.is_safe_path("/etc/hosts", ["/tmp"]))

    def test_empty_path_is_not_safe(self):
        self.assertFalse(h.is_safe_path("", ["/tmp"]))


if __name__ == "__main__":
    unittest.main()
