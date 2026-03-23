"""Tests for src/code_intel.py — code understanding and multi-file awareness."""
import os
import pytest
from src.code_intel import (
    detect_language, extract_imports, extract_symbols,
    analyze_file, build_dependency_graph, find_symbol,
    get_file_context, project_summary, FileInfo, Symbol,
)


class TestLanguageDetection:
    def test_python(self):
        assert detect_language("app.py") == "python"
        assert detect_language("test.pyi") == "python"

    def test_javascript(self):
        assert detect_language("index.js") == "javascript"
        assert detect_language("App.jsx") == "javascript"

    def test_typescript(self):
        assert detect_language("main.ts") == "typescript"
        assert detect_language("App.tsx") == "typescript"

    def test_go(self):
        assert detect_language("main.go") == "go"

    def test_rust(self):
        assert detect_language("lib.rs") == "rust"

    def test_kotlin(self):
        assert detect_language("Main.kt") == "kotlin"

    def test_unknown(self):
        assert detect_language("data.csv") == ""
        assert detect_language("README.md") == ""


class TestImportExtraction:
    def test_python_import(self):
        code = "import os\nimport json\nfrom pathlib import Path\n"
        imports = extract_imports(code, "python")
        assert "os" in imports
        assert "json" in imports
        assert "pathlib" in imports

    def test_javascript_import(self):
        code = 'import React from "react";\nimport { useState } from "react";\n'
        imports = extract_imports(code, "javascript")
        assert "react" in imports

    def test_go_import(self):
        code = 'import (\n\t"fmt"\n\t"os"\n)\n'
        imports = extract_imports(code, "go")
        assert "fmt" in imports

    def test_rust_use(self):
        code = "use std::io;\nuse std::collections::HashMap;\n"
        imports = extract_imports(code, "rust")
        assert "std::io" in imports

    def test_kotlin_import(self):
        code = "import com.example.app.MainActivity\nimport android.os.Bundle\n"
        imports = extract_imports(code, "kotlin")
        assert "com.example.app.MainActivity" in imports


class TestSymbolExtraction:
    def test_python_function(self):
        code = "def greet(name: str) -> str:\n    return f'Hello {name}'\n"
        symbols = extract_symbols(code, "python", "test.py")
        assert any(s.name == "greet" and s.kind == "function" for s in symbols)

    def test_python_class(self):
        code = "class MyAgent(BaseAgent):\n    pass\n"
        symbols = extract_symbols(code, "python", "test.py")
        assert any(s.name == "MyAgent" and s.kind == "class" for s in symbols)

    def test_python_async_function(self):
        code = "async def execute(self, task: str) -> str:\n    pass\n"
        symbols = extract_symbols(code, "python", "test.py")
        assert any(s.name == "execute" and s.kind == "function" for s in symbols)

    def test_javascript_function(self):
        code = "function handleClick(event) {\n  console.log(event);\n}\n"
        symbols = extract_symbols(code, "javascript", "app.js")
        assert any(s.name == "handleClick" for s in symbols)

    def test_go_function(self):
        code = "func main() {\n\tfmt.Println(\"hello\")\n}\n"
        symbols = extract_symbols(code, "go", "main.go")
        assert any(s.name == "main" for s in symbols)

    def test_line_numbers(self):
        code = "x = 1\n\ndef foo():\n    pass\n\ndef bar(a, b):\n    pass\n"
        symbols = extract_symbols(code, "python", "test.py")
        foo = next(s for s in symbols if s.name == "foo")
        bar = next(s for s in symbols if s.name == "bar")
        assert foo.line == 3
        assert bar.line == 6


class TestAnalyzeFile:
    def test_analyze_python_file(self):
        info = analyze_file("src/tools.py")
        assert info is not None
        assert info.language == "python"
        assert len(info.imports) > 0
        assert len(info.symbols) > 0
        assert any(s.name == "execute_tool" for s in info.symbols)

    def test_analyze_nonexistent(self):
        assert analyze_file("/nonexistent/file.py") is None

    def test_analyze_non_code(self):
        assert analyze_file("README.md") is None


class TestDependencyGraph:
    def test_builds_graph(self):
        graph = build_dependency_graph("src")
        assert len(graph) > 0
        # tools.py should be in the graph
        tool_files = [k for k in graph if "tools.py" in k]
        assert len(tool_files) > 0

    def test_finds_imports(self):
        graph = build_dependency_graph("src")
        base_files = [k for k in graph if "base.py" in k]
        if base_files:
            info = graph[base_files[0]]
            assert len(info.imports) > 0

    def test_reverse_deps(self):
        graph = build_dependency_graph("src")
        # config.py should be imported by many files
        config_files = [k for k in graph if "config.py" in k]
        if config_files:
            info = graph[config_files[0]]
            assert len(info.imported_by) > 0


class TestFindSymbol:
    def test_finds_known_symbol(self):
        graph = build_dependency_graph("src")
        results = find_symbol(graph, "execute_tool")
        assert len(results) >= 1
        assert results[0].kind == "function"

    def test_not_found(self):
        graph = build_dependency_graph("src")
        results = find_symbol(graph, "nonexistent_symbol_xyz")
        assert len(results) == 0


class TestProjectSummary:
    def test_summary(self):
        summary = project_summary("src")
        assert "PROJECT ANALYSIS" in summary
        assert "python" in summary.lower()
        assert "symbols" in summary.lower()

    def test_empty_dir(self, tmp_path):
        summary = project_summary(str(tmp_path))
        assert "No analyzable" in summary


class TestGetFileContext:
    def test_returns_context(self):
        ctx = get_file_context("src/tools.py")
        assert "python" in ctx.lower()
        assert "IMPORTS" in ctx
        assert "SYMBOLS" in ctx
