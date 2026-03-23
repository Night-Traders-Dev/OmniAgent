"""Tests for src/tools.py — all tool functions."""
import os
import json
import csv
import io
import pytest
from src.tools import (
    parse_json, read_file, write_file, edit_file, run_shell, web_search,
    is_weather_query, extract_location, get_weather, smart_search,
    glob_files, grep_files, project_tree, fetch_url,
    git_status, git_diff, git_log,
    is_dangerous_command, execute_tool, TOOL_REGISTRY,
    export_chat_json, export_chat_markdown, export_chat_text,
    export_chat_csv, export_chat_html,
)

class TestParseJson:
    def test_valid(self): assert parse_json('{"k":"v"}') == {"k": "v"}
    def test_embedded(self): assert parse_json('text {"tool":"web"} done')["tool"] == "web"
    def test_invalid(self): assert parse_json("no json") is None
    def test_empty(self): assert parse_json("") is None
    def test_nested(self): assert parse_json('{"a":{"b":1}}')["a"]["b"] == 1

class TestFileIO:
    def test_write_and_read(self, tmp_path):
        p = str(tmp_path / "t.txt")
        write_file(p, "hello")
        assert "hello" in read_file(p)

    def test_read_nonexistent(self):
        assert "ERROR" in read_file("/nonexistent/xyz.txt")

    def test_write_creates_dirs(self, tmp_path):
        p = str(tmp_path / "a" / "b" / "c.txt")
        write_file(p, "deep")
        assert "deep" in read_file(p)

    def test_read_with_offset_limit(self, tmp_path):
        p = str(tmp_path / "lines.txt")
        write_file(p, "\n".join(f"line {i}" for i in range(100)))
        result = read_file(p, offset=10, limit=5)
        assert "Lines 11-15" in result
        assert "line 10" in result

    def test_large_file_truncation(self, tmp_path):
        p = str(tmp_path / "big.txt")
        write_file(p, "\n".join(f"line {i}" for i in range(1000)))
        result = read_file(p)
        assert "Large file" in result
        assert "Showing first 200" in result

class TestEditFile:
    def test_basic_edit(self, tmp_path):
        p = str(tmp_path / "e.txt")
        write_file(p, "hello world")
        result = edit_file(p, "hello", "goodbye")
        assert "OK" in result
        assert "goodbye world" in read_file(p)

    def test_edit_not_found(self, tmp_path):
        p = str(tmp_path / "e2.txt")
        write_file(p, "hello")
        assert "not found" in edit_file(p, "xyz", "abc")

    def test_edit_ambiguous(self, tmp_path):
        p = str(tmp_path / "e3.txt")
        write_file(p, "aaa bbb aaa")
        assert "matches 2" in edit_file(p, "aaa", "ccc")

class TestRunShell:
    def test_allowed(self):
        r = run_shell("echo hello")
        assert "hello" in r and "EXIT:0" in r
    def test_blocked(self):
        assert "DANGEROUS" in run_shell("rm -rf /") or "BLOCKED" in run_shell("rm -rf /")
    def test_dangerous(self):
        assert "DANGEROUS" in run_shell("dd if=/dev/zero of=/dev/sda")
    def test_blocks_shell_control_operators(self):
        result = run_shell("echo hello && python -c 'print(42)'")
        assert "single command only" in result.lower()

class TestDangerousCommand:
    def test_rm_rf_root(self): assert is_dangerous_command("rm -rf /") is not None
    def test_safe_cmd(self): assert is_dangerous_command("ls -la") is None

class TestCodebaseTools:
    def test_glob(self, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        result = glob_files("*.py", str(tmp_path))
        assert "a.py" in result and "b.py" in result

    def test_grep(self, tmp_path):
        (tmp_path / "f.txt").write_text("hello world\nfoo bar\nhello again")
        result = grep_files("hello", str(tmp_path))
        assert "hello" in result

    def test_tree(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file.txt").write_text("x")
        result = project_tree(str(tmp_path))
        assert len(result) > 0

class TestGitTools:
    def test_git_status_returns_string(self):
        assert isinstance(git_status(), str)
    def test_git_log_returns_string(self):
        assert isinstance(git_log(), str)

class TestFetchUrl:
    def test_fetch_returns_string(self):
        result = fetch_url("https://example.com")
        assert isinstance(result, str)
        assert len(result) > 0

class TestToolRegistry:
    def test_all_tools_registered(self):
        for name in ["read", "write", "edit", "shell", "web", "glob", "grep", "tree", "git_status", "done"]:
            assert name in TOOL_REGISTRY

    def test_execute_tool_echo(self):
        result = execute_tool("shell", {"cmd": "echo hi"})
        assert "hi" in result

    def test_execute_unknown_tool(self):
        assert "ERROR" in execute_tool("nonexistent", {})

class TestWebSearch:
    def test_returns_string(self):
        assert isinstance(web_search("python"), str)
    def test_result_is_json(self):
        parsed = json.loads(web_search("linux"))
        assert isinstance(parsed, (list, dict))

class TestWeatherDetection:
    def test_weather(self): assert is_weather_query("temperature in NYC")
    def test_not_weather(self): assert not is_weather_query("python tutorial")

class TestExtractLocation:
    def test_simple(self): assert "ashland" in extract_location("temperature in Ashland Kentucky").lower()

class TestGetWeather:
    def test_returns_data(self):
        result = get_weather("London")
        assert isinstance(result, str)
        assert len(result) > 50
        # Should contain either forecast data or an error
        assert "WEATHER FOR" in result or "error" in result

class TestSmartSearch:
    def test_weather_routing(self): assert "WEATHER_DATA" in smart_search("temperature in London")
    def test_non_weather(self): assert "WEATHER_DATA" not in smart_search("python programming")

SAMPLE_HISTORY = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi!"},
]

class TestExports:
    def test_json(self): assert json.loads(export_chat_json(SAMPLE_HISTORY))
    def test_markdown(self): assert "# OmniAgent" in export_chat_markdown(SAMPLE_HISTORY)
    def test_text(self): assert "[USER]" in export_chat_text(SAMPLE_HISTORY)
    def test_csv(self):
        reader = csv.reader(io.StringIO(export_chat_csv(SAMPLE_HISTORY)))
        rows = list(reader)
        assert rows[0] == ["role", "content"]
    def test_html(self):
        h = export_chat_html(SAMPLE_HISTORY)
        assert "<!DOCTYPE html>" in h
    def test_html_escapes(self):
        h = export_chat_html([{"role": "user", "content": "<script>"}])
        assert "<script>" not in h
