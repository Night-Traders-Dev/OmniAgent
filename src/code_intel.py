"""
Tier 3: Code Understanding + Multi-File Awareness

Provides:
- Import/dependency graph extraction (Python, JS/TS, Go, Rust, Java)
- Symbol extraction (functions, classes, methods)
- File relationship mapping
- Semantic codebase indexing with optional ChromaDB

Works without tree-sitter — uses regex-based parsing for zero-dependency operation.
Falls back gracefully if ChromaDB isn't installed.
"""
import os
import re
import json
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    kind: str  # "function", "class", "method", "variable", "import"
    file: str
    line: int
    signature: str = ""


@dataclass
class FileInfo:
    path: str
    language: str
    imports: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    imported_by: list[str] = field(default_factory=list)


# Language detection by extension
LANG_MAP = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".rb": "ruby",
    ".sh": "shell", ".bash": "shell",
}

# Regex patterns per language for import extraction
IMPORT_PATTERNS = {
    "python": [
        re.compile(r'^import\s+([\w.]+)', re.MULTILINE),
        re.compile(r'^from\s+([\w.]+)\s+import', re.MULTILINE),
    ],
    "javascript": [
        re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE),
        re.compile(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', re.MULTILINE),
    ],
    "typescript": [
        re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE),
    ],
    "go": [
        re.compile(r'"([^"]+)"', re.MULTILINE),  # Inside import blocks
    ],
    "rust": [
        re.compile(r'^use\s+([\w:]+)', re.MULTILINE),
    ],
    "java": [
        re.compile(r'^import\s+([\w.]+);', re.MULTILINE),
    ],
    "kotlin": [
        re.compile(r'^import\s+([\w.]+)', re.MULTILINE),
    ],
}

# Symbol extraction patterns
SYMBOL_PATTERNS = {
    "python": [
        (re.compile(r'^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)', re.MULTILINE), "function"),
        (re.compile(r'^class\s+(\w+)(?:\(([^)]*)\))?:', re.MULTILINE), "class"),
    ],
    "javascript": [
        (re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)', re.MULTILINE), "function"),
        (re.compile(r'(?:export\s+)?class\s+(\w+)', re.MULTILINE), "class"),
        (re.compile(r'(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', re.MULTILINE), "function"),
    ],
    "typescript": [
        (re.compile(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*[\(<]', re.MULTILINE), "function"),
        (re.compile(r'(?:export\s+)?class\s+(\w+)', re.MULTILINE), "class"),
        (re.compile(r'(?:export\s+)?interface\s+(\w+)', re.MULTILINE), "class"),
    ],
    "go": [
        (re.compile(r'^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)', re.MULTILINE), "function"),
        (re.compile(r'^type\s+(\w+)\s+struct', re.MULTILINE), "class"),
    ],
    "rust": [
        (re.compile(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', re.MULTILINE), "function"),
        (re.compile(r'(?:pub\s+)?struct\s+(\w+)', re.MULTILINE), "class"),
        (re.compile(r'(?:pub\s+)?trait\s+(\w+)', re.MULTILINE), "class"),
    ],
    "java": [
        (re.compile(r'(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)?(\w+)\s*\(([^)]*)\)\s*(?:throws|\{)', re.MULTILINE), "function"),
        (re.compile(r'(?:public|private)?\s*class\s+(\w+)', re.MULTILINE), "class"),
    ],
    "kotlin": [
        (re.compile(r'(?:fun|suspend\s+fun)\s+(\w+)\s*[\(<]', re.MULTILINE), "function"),
        (re.compile(r'(?:data\s+)?class\s+(\w+)', re.MULTILINE), "class"),
    ],
}

IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'build', 'dist', '.idea', '.vscode', 'target'}


def detect_language(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    return LANG_MAP.get(ext, "")


def extract_imports(content: str, language: str) -> list[str]:
    patterns = IMPORT_PATTERNS.get(language, [])
    imports = []
    for pat in patterns:
        imports.extend(pat.findall(content))
    return imports


def extract_symbols(content: str, language: str, filepath: str) -> list[Symbol]:
    patterns = SYMBOL_PATTERNS.get(language, [])
    symbols = []
    lines = content.split('\n')
    for pat, kind in patterns:
        for match in pat.finditer(content):
            name = match.group(1)
            sig = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
            line_num = content[:match.start()].count('\n') + 1
            symbols.append(Symbol(name=name, kind=kind, file=filepath, line=line_num,
                                  signature=f"{name}({sig})" if sig else name))
    return symbols


def analyze_file(filepath: str) -> FileInfo | None:
    """Analyze a single file for imports and symbols."""
    lang = detect_language(filepath)
    if not lang:
        return None
    try:
        with open(filepath, 'r', errors='replace') as f:
            content = f.read()
    except (IOError, PermissionError):
        return None
    if len(content) > 500_000:  # Skip very large files
        return None
    imports = extract_imports(content, lang)
    symbols = extract_symbols(content, lang, filepath)
    return FileInfo(path=filepath, language=lang, imports=imports, symbols=symbols)


def build_dependency_graph(root: str = ".") -> dict[str, FileInfo]:
    """Build a dependency graph for the entire project."""
    graph: dict[str, FileInfo] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            info = analyze_file(filepath)
            if info:
                graph[filepath] = info
    # Build reverse dependency (imported_by)
    all_files = set(graph.keys())
    for filepath, info in graph.items():
        for imp in info.imports:
            # Resolve import to file (best-effort)
            imp_path = imp.replace('.', '/').replace('::', '/')
            for candidate in all_files:
                if imp_path in candidate:
                    if candidate in graph:
                        graph[candidate].imported_by.append(filepath)
                    break
    return graph


def find_symbol(graph: dict[str, FileInfo], symbol_name: str) -> list[Symbol]:
    """Find all definitions of a symbol across the project."""
    results = []
    for info in graph.values():
        for sym in info.symbols:
            if sym.name == symbol_name:
                results.append(sym)
    return results


def get_file_context(filepath: str, graph: dict[str, FileInfo] = None) -> str:
    """Get context for a file — its imports, symbols, and what imports it."""
    if graph is None:
        graph = {}
    info = graph.get(filepath) or analyze_file(filepath)
    if not info:
        return f"Could not analyze {filepath}"
    lines = [f"FILE: {filepath} ({info.language})"]
    if info.imports:
        lines.append(f"IMPORTS: {', '.join(info.imports[:20])}")
    if info.symbols:
        lines.append("SYMBOLS:")
        for sym in info.symbols[:30]:
            lines.append(f"  {sym.kind}: {sym.signature} (line {sym.line})")
    if info.imported_by:
        lines.append(f"IMPORTED BY: {', '.join(info.imported_by[:10])}")
    return "\n".join(lines)


def project_summary(root: str = ".") -> str:
    """Generate a project intelligence summary."""
    graph = build_dependency_graph(root)
    if not graph:
        return "No analyzable source files found."
    # Count by language
    lang_counts: dict[str, int] = {}
    total_symbols = 0
    for info in graph.values():
        lang_counts[info.language] = lang_counts.get(info.language, 0) + 1
        total_symbols += len(info.symbols)
    # Find most-imported files (core modules)
    core_files = sorted(graph.values(), key=lambda f: len(f.imported_by), reverse=True)[:5]
    lines = [
        f"PROJECT ANALYSIS ({len(graph)} files, {total_symbols} symbols)",
        f"Languages: {', '.join(f'{lang}: {count}' for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]))}",
    ]
    if core_files and core_files[0].imported_by:
        lines.append("Core modules (most imported):")
        for f in core_files:
            if f.imported_by:
                lines.append(f"  {f.path} ({len(f.imported_by)} dependents)")
    return "\n".join(lines)


# ============================================================
# Tier 3: RAG / Semantic Search (optional ChromaDB)
# ============================================================

_chroma_client = None
_chroma_collection = None


def _init_chromadb():
    """Initialize ChromaDB for semantic search. Fails gracefully if not installed."""
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return True
    try:
        import chromadb
        _chroma_client = chromadb.Client()
        _chroma_collection = _chroma_client.get_or_create_collection(
            name="omni_codebase",
            metadata={"hnsw:space": "cosine"},
        )
        return True
    except ImportError:
        return False
    except Exception:
        return False


def index_codebase(root: str = "."):
    """Index the codebase into ChromaDB for semantic search."""
    if not _init_chromadb():
        return "ChromaDB not available. Install with: pip install chromadb"
    graph = build_dependency_graph(root)
    documents = []
    ids = []
    metadatas = []
    for filepath, info in graph.items():
        try:
            with open(filepath, 'r', errors='replace') as f:
                content = f.read()[:4000]
        except Exception:
            continue
        # Create a searchable document with symbols and imports
        doc = f"FILE: {filepath}\nLANGUAGE: {info.language}\n"
        if info.symbols:
            doc += "SYMBOLS: " + ", ".join(s.signature for s in info.symbols[:20]) + "\n"
        if info.imports:
            doc += "IMPORTS: " + ", ".join(info.imports[:10]) + "\n"
        doc += f"\nCODE:\n{content[:2000]}"
        documents.append(doc)
        ids.append(filepath)
        metadatas.append({"language": info.language, "path": filepath})

    if documents:
        # ChromaDB handles batching
        _chroma_collection.upsert(documents=documents, ids=ids, metadatas=metadatas)
    return f"Indexed {len(documents)} files"


def semantic_search(query: str, n_results: int = 5) -> str:
    """Search the codebase semantically."""
    if not _init_chromadb() or _chroma_collection is None:
        return "ChromaDB not available."
    try:
        results = _chroma_collection.query(query_texts=[query], n_results=n_results)
        if not results or not results.get("documents"):
            return "No results found."
        lines = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            lines.append(f"--- {meta.get('path', 'unknown')} ---")
            lines.append(doc[:500])
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"
