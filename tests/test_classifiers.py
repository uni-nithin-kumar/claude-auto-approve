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


class TestIsafeCurl(unittest.TestCase):
    def test_no_flag_is_get_safe(self):
        self.assertTrue(h.is_safe_curl("curl https://api.github.com/repos/foo"))

    def test_explicit_get_safe(self):
        self.assertTrue(h.is_safe_curl("curl -X GET https://example.com"))

    def test_post_localhost_safe_when_allowed(self):
        self.assertTrue(h.is_safe_curl("curl -X POST http://localhost:8089/api -d '{}'", allow_localhost_post=True))

    def test_post_localhost_not_safe_when_disallowed(self):
        self.assertFalse(h.is_safe_curl("curl -X POST http://localhost:8089/api -d '{}'", allow_localhost_post=False))

    def test_post_127_safe_when_allowed(self):
        self.assertTrue(h.is_safe_curl("curl -X POST http://127.0.0.1:9080/v1/chat -d '{}'", allow_localhost_post=True))

    def test_post_external_not_safe(self):
        self.assertFalse(h.is_safe_curl("curl -X POST https://api.external.com/data -d '{}'", allow_localhost_post=True))

    def test_delete_not_safe(self):
        self.assertFalse(h.is_safe_curl("curl -X DELETE https://api.example.com/resource"))

    def test_put_localhost_safe(self):
        self.assertTrue(h.is_safe_curl("curl -X PUT http://localhost:8080/config -d '{}'", allow_localhost_post=True))

    def test_put_external_not_safe(self):
        self.assertFalse(h.is_safe_curl("curl -X PUT https://external.com/resource -d '{}'", allow_localhost_post=True))


class TestIsafeGit(unittest.TestCase):
    def test_log_safe_readonly(self):
        self.assertTrue(h.is_safe_git("git log --oneline -5", allow_writes=False))

    def test_status_safe_readonly(self):
        self.assertTrue(h.is_safe_git("git status", allow_writes=False))

    def test_commit_not_safe_readonly(self):
        self.assertFalse(h.is_safe_git("git commit -m 'fix'", allow_writes=False))

    def test_add_not_safe_readonly(self):
        self.assertFalse(h.is_safe_git("git add .", allow_writes=False))

    def test_commit_safe_writes(self):
        self.assertTrue(h.is_safe_git("git commit -m 'fix'", allow_writes=True))

    def test_add_safe_writes(self):
        self.assertTrue(h.is_safe_git("git add .", allow_writes=True))

    def test_push_safe_writes(self):
        self.assertTrue(h.is_safe_git("git push origin main", allow_writes=True))

    def test_push_force_not_safe(self):
        self.assertFalse(h.is_safe_git("git push --force", allow_writes=True))

    def test_push_f_not_safe(self):
        self.assertFalse(h.is_safe_git("git push -f", allow_writes=True))

    def test_reset_hard_not_safe(self):
        self.assertFalse(h.is_safe_git("git reset --hard HEAD~1", allow_writes=True))

    def test_rebase_interactive_not_safe(self):
        self.assertFalse(h.is_safe_git("git rebase -i HEAD~3", allow_writes=True))

    def test_rebase_non_interactive_safe(self):
        self.assertTrue(h.is_safe_git("git rebase origin/main", allow_writes=True))

    def test_dash_c_log_safe(self):
        self.assertTrue(h.is_safe_git("git -C /some/path log --oneline -3", allow_writes=False))

    def test_config_get_safe(self):
        self.assertTrue(h.is_safe_git("git config --get user.email", allow_writes=False))

    def test_config_set_not_safe(self):
        self.assertFalse(h.is_safe_git("git config user.email foo@bar.com", allow_writes=False))

    def test_unknown_subcommand_not_safe(self):
        self.assertFalse(h.is_safe_git("git bisect start", allow_writes=True))


class TestIsafeKubectl(unittest.TestCase):
    def test_get_safe(self):
        self.assertTrue(h.is_safe_kubectl("kubectl get pods"))

    def test_describe_safe(self):
        self.assertTrue(h.is_safe_kubectl("kubectl describe svc myservice"))

    def test_logs_safe(self):
        self.assertTrue(h.is_safe_kubectl("kubectl logs deploy/myapp --tail=50"))

    def test_apply_not_safe(self):
        self.assertFalse(h.is_safe_kubectl("kubectl apply -f deployment.yaml"))

    def test_delete_not_safe(self):
        self.assertFalse(h.is_safe_kubectl("kubectl delete pod mypod"))

    def test_create_not_safe(self):
        self.assertFalse(h.is_safe_kubectl("kubectl create secret generic mysecret"))


class TestIsafeSegment(unittest.TestCase):
    def test_ls_safe(self):
        self.assertTrue(h.is_safe_segment("ls -la"))

    def test_grep_safe(self):
        self.assertTrue(h.is_safe_segment("grep -r 'foo' ."))

    def test_rm_not_safe(self):
        self.assertFalse(h.is_safe_segment("rm -rf /"))

    def test_kill_not_safe(self):
        self.assertFalse(h.is_safe_segment("kill -9 1234"))

    def test_sudo_not_safe(self):
        self.assertFalse(h.is_safe_segment("sudo cat /etc/passwd"))

    def test_env_prefix_stripped(self):
        self.assertTrue(h.is_safe_segment("NODE_ENV=prod ls"))

    def test_awk_no_system_safe(self):
        self.assertTrue(h.is_safe_segment("awk '{print $1}'"))

    def test_awk_with_system_not_safe(self):
        self.assertFalse(h.is_safe_segment("awk '{system(\"rm foo\")}'"))

    def test_sed_without_i_safe(self):
        self.assertTrue(h.is_safe_segment("sed 's/foo/bar/'"))

    def test_sed_with_i_not_safe(self):
        self.assertFalse(h.is_safe_segment("sed -i 's/foo/bar/' file.txt"))

    def test_find_simple_safe(self):
        self.assertTrue(h.is_safe_segment("find . -name '*.py'"))

    def test_find_exec_rm_not_safe(self):
        self.assertFalse(h.is_safe_segment("find . -exec rm {} ;"))

    def test_find_exec_cat_safe(self):
        self.assertTrue(h.is_safe_segment("find . -exec cat {} ;"))

    def test_tee_devnull_safe(self):
        self.assertTrue(h.is_safe_segment("tee /dev/null"))

    def test_tee_file_not_safe(self):
        self.assertFalse(h.is_safe_segment("tee output.txt"))

    def test_pip_show_safe(self):
        self.assertTrue(h.is_safe_segment("pip show requests"))

    def test_pip_install_not_safe(self):
        self.assertFalse(h.is_safe_segment("pip install requests"))

    def test_brew_list_safe(self):
        self.assertTrue(h.is_safe_segment("brew list"))

    def test_brew_install_not_safe(self):
        self.assertFalse(h.is_safe_segment("brew install ripgrep"))

    def test_python3_version_safe(self):
        self.assertTrue(h.is_safe_segment("python3 --version"))

    def test_python3_c_transform_safe(self):
        self.assertTrue(h.is_safe_segment("python3 -c \"import json; print(json.dumps({'a':1}))\""))

    def test_python3_c_file_write_not_safe(self):
        self.assertFalse(h.is_safe_segment("python3 -c \"open('out.txt', 'w').write('data')\""))

    def test_python3_script_not_safe(self):
        self.assertFalse(h.is_safe_segment("python3 myscript.py"))

    def test_git_commit_safe_with_writes(self):
        self.assertTrue(h.is_safe_segment("git commit -m 'fix'", allow_git_writes=True))

    def test_git_commit_not_safe_without_writes(self):
        self.assertFalse(h.is_safe_segment("git commit -m 'fix'", allow_git_writes=False))

    def test_curl_post_localhost_safe_when_allowed(self):
        self.assertTrue(h.is_safe_segment(
            "curl -X POST http://localhost:8089/api -d '{}'",
            allow_localhost_post=True
        ))

    def test_curl_post_localhost_not_safe_when_disallowed(self):
        self.assertFalse(h.is_safe_segment(
            "curl -X POST http://localhost:8089/api -d '{}'",
            allow_localhost_post=False
        ))


class TestClassifyBash(unittest.TestCase):
    def test_off_defers_ls(self):
        self.assertFalse(h.classify_bash({"command": "ls -la"}, "off"))

    def test_off_defers_git_log(self):
        self.assertFalse(h.classify_bash({"command": "git log"}, "off"))

    def test_force_approves_rm(self):
        self.assertTrue(h.classify_bash({"command": "rm -rf /"}, "force"))

    def test_force_approves_ls(self):
        self.assertTrue(h.classify_bash({"command": "ls"}, "force"))

    def test_readonly_approves_ls(self):
        self.assertTrue(h.classify_bash({"command": "ls -la"}, "read-only"))

    def test_readonly_approves_git_log(self):
        self.assertTrue(h.classify_bash({"command": "git log --oneline -5"}, "read-only"))

    def test_readonly_defers_git_commit(self):
        self.assertFalse(h.classify_bash({"command": "git commit -m 'fix'"}, "read-only"))

    def test_readonly_defers_curl_post_localhost(self):
        self.assertFalse(h.classify_bash(
            {"command": "curl -X POST http://localhost:8089/api -d '{}'"},
            "read-only"
        ))

    def test_readonly_approves_curl_get(self):
        self.assertTrue(h.classify_bash(
            {"command": "curl -s https://api.github.com/repos/foo"},
            "read-only"
        ))

    def test_docswrite_approves_git_commit(self):
        self.assertTrue(h.classify_bash({"command": "git commit -m 'fix'"}, "docs-write"))

    def test_docswrite_approves_curl_post_localhost(self):
        self.assertTrue(h.classify_bash(
            {"command": "curl -X POST http://localhost:8089/api -d '{}'"},
            "docs-write"
        ))

    def test_docswrite_defers_rm(self):
        self.assertFalse(h.classify_bash({"command": "rm -rf /"}, "docs-write"))

    def test_docswrite_defers_git_push_force(self):
        self.assertFalse(h.classify_bash({"command": "git push --force"}, "docs-write"))

    def test_subshell_dollar_defers(self):
        self.assertFalse(h.classify_bash({"command": "ls $(pwd)"}, "docs-write"))

    def test_subshell_backtick_defers(self):
        self.assertFalse(h.classify_bash({"command": "ls `pwd`"}, "docs-write"))

    def test_safe_pipeline_approves(self):
        self.assertTrue(h.classify_bash(
            {"command": "git log --oneline -10 | grep feat | head -5"},
            "docs-write"
        ))

    def test_unsafe_in_pipeline_defers(self):
        self.assertFalse(h.classify_bash({"command": "ls | rm -rf"}, "docs-write"))

    def test_empty_command_defers(self):
        self.assertFalse(h.classify_bash({"command": ""}, "docs-write"))


class TestClassifyEditWrite(unittest.TestCase):
    HOME = str(Path.home())

    def test_off_defers_tmp(self):
        self.assertFalse(h.classify_edit_write({"file_path": "/tmp/x.py"}, "off", ["/tmp"]))

    def test_force_approves_etc(self):
        self.assertTrue(h.classify_edit_write({"file_path": "/etc/hosts"}, "force", ["/tmp"]))

    def test_readonly_approves_tmp(self):
        self.assertTrue(h.classify_edit_write({"file_path": "/tmp/x.py"}, "read-only", ["/tmp"]))

    def test_readonly_defers_workspace(self):
        self.assertFalse(h.classify_edit_write(
            {"file_path": f"{self.HOME}/workspace/main.py"},
            "read-only",
            [f"{self.HOME}/workspace", "/tmp"]
        ))

    def test_docswrite_approves_workspace(self):
        self.assertTrue(h.classify_edit_write(
            {"file_path": f"{self.HOME}/workspace/main.py"},
            "docs-write",
            [f"{self.HOME}/workspace", "/tmp"]
        ))

    def test_docswrite_defers_etc(self):
        self.assertFalse(h.classify_edit_write(
            {"file_path": "/etc/hosts"},
            "docs-write",
            [f"{self.HOME}/workspace", "/tmp"]
        ))

    def test_notebook_path_key_works(self):
        self.assertTrue(h.classify_edit_write(
            {"notebook_path": "/tmp/nb.ipynb"},
            "docs-write",
            ["/tmp"]
        ))

    def test_empty_path_defers(self):
        self.assertFalse(h.classify_edit_write({"file_path": ""}, "docs-write", ["/tmp"]))


class TestClassifyMcp(unittest.TestCase):
    def test_off_defers_snapshot(self):
        self.assertFalse(h.classify_mcp("mcp__browseros__take_snapshot", "off"))

    def test_force_approves_create(self):
        self.assertTrue(h.classify_mcp("mcp__atlassian__createJiraIssue", "force"))

    def test_browseros_snapshot_approved(self):
        self.assertTrue(h.classify_mcp("mcp__browseros__take_snapshot", "docs-write"))

    def test_browseros_click_defers(self):
        self.assertFalse(h.classify_mcp("mcp__browseros__click", "docs-write"))

    def test_atlassian_user_info_approved(self):
        self.assertTrue(h.classify_mcp("mcp__atlassian__atlassianUserInfo", "docs-write"))

    def test_atlassian_create_defers(self):
        self.assertFalse(h.classify_mcp("mcp__atlassian__createJiraIssue", "docs-write"))

    def test_generic_get_prefix_approved(self):
        self.assertTrue(h.classify_mcp("mcp__someserver__get_user", "docs-write"))

    def test_generic_list_prefix_approved(self):
        self.assertTrue(h.classify_mcp("mcp__someserver__list_channels", "docs-write"))

    def test_generic_create_defers(self):
        self.assertFalse(h.classify_mcp("mcp__someserver__create_record", "docs-write"))

    def test_readonly_same_as_docswrite_for_mcp(self):
        self.assertTrue(h.classify_mcp("mcp__someserver__get_user", "read-only"))
        self.assertFalse(h.classify_mcp("mcp__someserver__create_record", "read-only"))


if __name__ == "__main__":
    unittest.main()
