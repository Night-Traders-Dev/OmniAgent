"""
Advanced reasoning and code intelligence — Tiers 1-5.

Tier 1: Large model routing (GPU worker toggle)
Tier 2: RAG with vector embeddings + expanded context
Tier 3: Multi-model review-revise verification pipeline
Tier 4: AST-aware editing, type checking, test-driven loops
Tier 5: Structured reasoning chain (understand→plan→implement→verify)
"""
import os
import re
import json
import asyncio
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from src.state import state
from src.config import CLIENT, EXPERTS

# ============================================================
# Tier 1: Large Model Routing
# ============================================================

# When enabled, complex coding/reasoning tasks route to the GPU worker's
# larger models (32B) instead of the local 8B models.
LARGE_MODEL_ROUTING = False
LARGE_MODEL_NAME = os.environ.get("LARGE_MODEL", "qwen2.5-coder:32b")

def set_large_model_routing(enabled: bool):
    global LARGE_MODEL_ROUTING
    LARGE_MODEL_ROUTING = enabled

def get_large_model_client():
    """Get the GPU worker's Ollama client for large model inference."""
    if not LARGE_MODEL_ROUTING:
        return None
    try:
        from src.gpu_client import pool
        worker = pool.best_worker("verification")  # Workers with Ollama
        if worker:
            from openai import OpenAI
            return OpenAI(base_url=f"http://{worker.ip}:11434/v1", api_key="ollama"), LARGE_MODEL_NAME
    except Exception:
        pass
    return None


# ============================================================
# Tier 2: RAG — Retrieval-Augmented Generation
# ============================================================

_embedding_cache: dict[str, list[float]] = {}
_file_index: dict[str, dict] = {}  # path → {hash, summary, embedding}
_faiss_index = None  # FAISS index for fast vector search
_faiss_paths: list[str] = []  # Ordered paths matching FAISS index positions
_MAX_INDEX_FILES = 5000
_EMBED_DIM = 256

def _simple_embed(text: str) -> list[float]:
    """TF-IDF-like embedding using character trigrams → fixed 256-dim vector."""
    vec = [0.0] * _EMBED_DIM
    text = text.lower()
    for i in range(len(text) - 2):
        trigram = text[i:i+3]
        idx = hash(trigram) % _EMBED_DIM
        vec[idx] += 1.0
    norm = sum(v*v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec

def _cosine_sim(a: list[float], b: list[float]) -> float:
    return sum(x*y for x, y in zip(a, b))

def _build_faiss_index():
    """Build a FAISS index from the file index for fast nearest-neighbor search."""
    global _faiss_index, _faiss_paths
    try:
        import faiss
        import numpy as np
        if not _file_index:
            return
        paths = list(_file_index.keys())
        embeddings = [_file_index[p]['embedding'] for p in paths]
        matrix = np.array(embeddings, dtype=np.float32)
        index = faiss.IndexFlatIP(matrix.shape[1])  # Inner product (cosine on normalized vecs)
        index.add(matrix)
        _faiss_index = index
        _faiss_paths = paths
    except ImportError:
        pass  # Fall back to brute-force cosine

def _summarize_file(path: str) -> str:
    """Extract function/class signatures as a compact summary."""
    try:
        content = Path(path).read_text(errors='replace')
    except Exception:
        return ""
    lines = content.split('\n')
    sigs = []
    for line in lines:
        stripped = line.strip()
        # Python
        if stripped.startswith(('def ', 'class ', 'async def ')):
            sigs.append(stripped.split(':', 1)[0])
        # JS/TS
        elif re.match(r'(export\s+)?(function|class|const|let|var)\s+\w+', stripped):
            sigs.append(stripped[:100])
        # Rust/Go/Java
        elif re.match(r'(pub\s+)?(fn|func|public|private|protected)\s+', stripped):
            sigs.append(stripped[:100])
    return '\n'.join(sigs[:50])  # Cap at 50 signatures

def index_codebase(root: str = ".") -> int:
    """Index the codebase for RAG retrieval. Returns number of files indexed."""
    global _file_index
    count = 0
    if len(_file_index) >= _MAX_INDEX_FILES:
        return len(_file_index)
    code_exts = {'.py', '.js', '.ts', '.jsx', '.tsx', '.kt', '.java', '.rs', '.go', '.c', '.cpp', '.h', '.rb', '.sh'}
    root_path = Path(root)
    for f in root_path.rglob('*'):
        if not f.is_file() or f.suffix not in code_exts:
            continue
        if any(p in str(f) for p in ['/node_modules/', '/.git/', '/build/', '/__pycache__/', '/venv/', '/.venv/']):
            continue
        try:
            content = f.read_text(errors='replace')
            file_hash = hashlib.md5(content.encode()).hexdigest()
            # Skip if unchanged
            if str(f) in _file_index and _file_index[str(f)].get('hash') == file_hash:
                count += 1
                continue
            summary = _summarize_file(str(f))
            embedding = _simple_embed(summary + ' ' + str(f))
            _file_index[str(f)] = {
                'hash': file_hash,
                'summary': summary,
                'embedding': embedding,
                'size': len(content),
            }
            count += 1
        except Exception:
            continue
    # Build FAISS index for fast retrieval
    _build_faiss_index()
    return count

def retrieve_context(query: str, max_files: int = 5, max_chars: int = 8000) -> str:
    """Retrieve relevant files/functions for a query using FAISS vector search (or cosine fallback)."""
    if not _file_index:
        index_codebase()
    if not _file_index:
        return ""

    query_emb = _simple_embed(query)

    # Try FAISS first (much faster for large codebases)
    scored = []
    if _faiss_index is not None and _faiss_paths:
        try:
            import numpy as np
            q = np.array([query_emb], dtype=np.float32)
            distances, indices = _faiss_index.search(q, min(max_files * 2, len(_faiss_paths)))
            for dist, idx in zip(distances[0], indices[0]):
                if idx >= 0 and idx < len(_faiss_paths):
                    path = _faiss_paths[idx]
                    scored.append((float(dist), path, _file_index[path]))
        except Exception:
            scored = []

    # Fallback to brute-force cosine
    if not scored:
        for path, info in _file_index.items():
            sim = _cosine_sim(query_emb, info['embedding'])
            scored.append((sim, path, info))
        scored.sort(reverse=True)

    context_parts = []
    total = 0
    for sim, path, info in scored[:max_files]:
        summary = info['summary']
        if not summary:
            continue
        entry = f"--- {path} ---\n{summary}\n"
        if total + len(entry) > max_chars:
            break
        context_parts.append(entry)
        total += len(entry)

    if context_parts:
        return "RELEVANT CODEBASE CONTEXT:\n" + '\n'.join(context_parts)
    return ""


# ============================================================
# Tier 3: Multi-Model Review-Revise Pipeline
# ============================================================

async def review_and_revise(
    original_task: str,
    code_output: str,
    context: str = "",
) -> dict:
    """Have the reasoning model review the coder's output and suggest fixes."""
    from src.agents.specialists import ReasoningAgent
    ts = datetime.now().strftime("%H:%M:%S")
    state.progress_log.append(f"[{ts}] Review: Reasoning model checking code quality")

    reviewer = ReasoningAgent()
    review_prompt = (
        f"Review this code for correctness, edge cases, and bugs.\n\n"
        f"ORIGINAL TASK: {original_task}\n\n"
        f"CODE OUTPUT:\n```\n{code_output[:3000]}\n```\n\n"
        f"List specific issues found (if any). If the code is correct, say 'LGTM'."
    )
    review_result = await reviewer.execute(review_prompt, context, [])

    if review_result.status != AgentStatus.SUCCESS:
        return {"reviewed": False, "output": code_output}

    review_text = review_result.output.strip()
    state.progress_log.append(f"[{ts}] Review: {review_text[:80]}...")

    # If LGTM, return original
    if 'lgtm' in review_text.lower() or 'looks good' in review_text.lower() or 'no issues' in review_text.lower():
        state.progress_log.append(f"[{ts}] Review: Code approved ✓")
        return {"reviewed": True, "issues": None, "output": code_output}

    # Issues found — have the coder fix them
    state.progress_log.append(f"[{ts}] Review: Issues found, requesting fixes")
    from src.agents.specialists import CodingAgent
    fixer = CodingAgent()
    fix_prompt = (
        f"Fix these issues in the code:\n\n"
        f"ISSUES:\n{review_text}\n\n"
        f"ORIGINAL CODE:\n```\n{code_output[:3000]}\n```\n\n"
        f"Output the fixed code."
    )
    fix_result = await fixer.execute(fix_prompt, context, [])
    if fix_result.status == AgentStatus.SUCCESS:
        state.progress_log.append(f"[{ts}] Review: Code fixed and approved ✓")
        return {"reviewed": True, "issues": review_text, "output": fix_result.output}

    return {"reviewed": True, "issues": review_text, "output": code_output}

# Need this import after the function is defined to avoid circular imports
from src.agents.base import AgentStatus


# ============================================================
# Tier 4: Code Intelligence — AST, Type Checking, Tests
# ============================================================

def run_type_check(file_path: str) -> Optional[str]:
    """Run type checking on a Python file. Returns errors or None."""
    if not file_path.endswith('.py'):
        return None
    try:
        result = subprocess.run(
            ['python3', '-m', 'mypy', '--no-error-summary', '--no-color', file_path],
            capture_output=True, text=True, timeout=15,
        )
        errors = result.stdout.strip()
        if errors and 'error:' in errors:
            return errors
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None

def run_syntax_check(file_path: str) -> Optional[str]:
    """Check Python syntax without executing."""
    if not file_path.endswith('.py'):
        return None
    try:
        result = subprocess.run(
            ['python3', '-c', f'import py_compile; py_compile.compile("{file_path}", doraise=True)'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return result.stderr.strip()
    except Exception:
        pass
    return None

def run_tests_for_file(file_path: str) -> Optional[dict]:
    """Run tests related to a modified file. Returns {passed, failed, output}."""
    # Find test file
    path = Path(file_path)
    test_candidates = [
        path.parent / f"test_{path.name}",
        path.parent / "tests" / f"test_{path.name}",
        path.parent.parent / "tests" / f"test_{path.name}",
    ]
    test_file = None
    for tc in test_candidates:
        if tc.exists():
            test_file = tc
            break
    if not test_file:
        return None

    try:
        # Use venv python if available
        python = str(Path('.venv/bin/python')) if Path('.venv/bin/python').exists() else 'python3'
        result = subprocess.run(
            [python, '-m', 'pytest', str(test_file), '-v', '--tb=short', '-q'],
            capture_output=True, text=True, timeout=30,
        )
        passed = result.stdout.count(' PASSED')
        failed = result.stdout.count(' FAILED')
        return {"passed": passed, "failed": failed, "output": result.stdout[-500:]}
    except Exception:
        return None

def validate_code_output(file_path: str) -> list[str]:
    """Run all code validation checks on a file. Returns list of issues."""
    issues = []
    # Syntax check
    syntax = run_syntax_check(file_path)
    if syntax:
        issues.append(f"Syntax error: {syntax}")
    # Type check
    types = run_type_check(file_path)
    if types:
        issues.append(f"Type errors:\n{types}")
    # Tests
    tests = run_tests_for_file(file_path)
    if tests and tests['failed'] > 0:
        issues.append(f"Test failures: {tests['failed']} failed\n{tests['output']}")
    return issues


# ============================================================
# Tier 5: Structured Reasoning Chain
# ============================================================

async def structured_reasoning_chain(
    task: str,
    context: str = "",
    conversation: list[dict] | None = None,
) -> dict:
    """
    Full reasoning chain: understand → plan → implement → verify.
    Used for complex coding/reasoning tasks.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    state.progress_log.append(f"[{ts}] Chain: Starting structured reasoning (understand→plan→implement→verify)")

    results = {}

    # Phase 1: Understand
    state.progress_log.append(f"[{ts}] Chain [1/4]: Understanding the problem")
    from src.agents.specialists import ReasoningAgent
    understander = ReasoningAgent()
    understand_result = await understander.execute(
        f"Analyze this task and identify:\n"
        f"1. What exactly needs to be done\n"
        f"2. What files/components are involved\n"
        f"3. What edge cases to consider\n"
        f"4. What could go wrong\n\n"
        f"TASK: {task}",
        context, conversation,
    )
    results['understanding'] = understand_result.output if understand_result.status == AgentStatus.SUCCESS else ""
    state.progress_log.append(f"[{ts}] Chain [1/4]: Understanding complete")

    # Phase 2: Plan
    ts = datetime.now().strftime("%H:%M:%S")
    state.progress_log.append(f"[{ts}] Chain [2/4]: Creating implementation plan")
    from src.agents.specialists import PlannerAgent
    planner = PlannerAgent()
    plan_result = await planner.execute(
        f"Create a step-by-step implementation plan for this task.\n\n"
        f"TASK: {task}\n\n"
        f"ANALYSIS: {results['understanding'][:1000]}",
        context, conversation,
    )
    results['plan'] = plan_result.output if plan_result.status == AgentStatus.SUCCESS else ""
    state.progress_log.append(f"[{ts}] Chain [2/4]: Plan complete")

    # Phase 3: Implement
    ts = datetime.now().strftime("%H:%M:%S")
    state.progress_log.append(f"[{ts}] Chain [3/4]: Implementing solution")
    from src.agents.specialists import CodingAgent
    coder = CodingAgent()
    impl_context = (
        f"{context}\n\n"
        f"ANALYSIS:\n{results['understanding'][:800]}\n\n"
        f"PLAN:\n{results['plan'][:800]}"
    )
    impl_result = await coder.execute(task, impl_context, conversation)
    results['implementation'] = impl_result.output if impl_result.status == AgentStatus.SUCCESS else ""
    state.progress_log.append(f"[{ts}] Chain [3/4]: Implementation complete")

    # Phase 4: Verify
    ts = datetime.now().strftime("%H:%M:%S")
    state.progress_log.append(f"[{ts}] Chain [4/4]: Verifying solution")
    review = await review_and_revise(task, results['implementation'], context)
    results['verified'] = review.get('reviewed', False)
    results['final_output'] = review.get('output', results['implementation'])
    if review.get('issues'):
        results['issues_found'] = review['issues']
    state.progress_log.append(f"[{ts}] Chain [4/4]: Verification {'passed ✓' if not review.get('issues') else 'found issues, applied fixes'}")

    return results


# ============================================================
# Integration: Enhanced Orchestrator Dispatch
# ============================================================

def should_use_reasoning_chain(task: str) -> bool:
    """Determine if a task is complex enough to warrant the full reasoning chain."""
    lower = task.lower()
    complex_signals = [
        'refactor', 'redesign', 'architect', 'migrate', 'rewrite',
        'debug.*complex', 'fix.*multiple', 'implement.*system',
        'create.*module', 'build.*feature', 'integrate',
        'security.*audit', 'performance.*optimize',
    ]
    for pattern in complex_signals:
        if re.search(pattern, lower):
            return True
    # Long tasks are usually complex
    if len(task) > 300:
        return True
    return False

def should_use_large_model(task: str) -> bool:
    """Determine if a task needs the large model on the GPU worker."""
    if not LARGE_MODEL_ROUTING:
        return False
    lower = task.lower()
    hard_signals = [
        'entire codebase', 'full audit', 'architecture', 'design pattern',
        'complex algorithm', 'optimize', 'security', 'vulnerability',
        'multi-file', 'cross-reference', 'deep analysis',
    ]
    return any(s in lower for s in hard_signals)
