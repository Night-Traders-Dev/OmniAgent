"""
OmniAgent Plugin System
~~~~~~~~~~~~~~~~~~~~~~~

Drop Python files into ~/.omniagent/tools/ and they auto-register as tools
available to agents.

Each plugin .py file must define a top-level TOOL dict:

    TOOL = {
        "name": "my_tool",
        "description": "What this tool does",
        "args": "arg1, [arg2]",
        "fn": my_function,  # callable reference
    }

Files starting with '_' or '.' are skipped (use _example.py.disabled as a
template). Only .py files are loaded.
"""

import importlib.util
import logging
import sys
from pathlib import Path

logger = logging.getLogger("omniagent.plugins")

PLUGIN_DIR = Path.home() / ".omniagent" / "tools"

# Tracks loaded plugins: name -> {module, file, tool_dict}
_loaded_plugins: dict[str, dict] = {}


def load_plugins() -> list[str]:
    """Scan ~/.omniagent/tools/ for .py plugin files and register them.

    - Creates the plugin directory if it doesn't exist.
    - Skips files whose stems start with '_' or '.'.
    - Imports each file in isolation; errors are logged, not raised.
    - Registers valid TOOL dicts into TOOL_REGISTRY from src.tools.
    - Returns a list of successfully loaded plugin names.
    """
    from src.tools import TOOL_REGISTRY

    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

    loaded: list[str] = []

    for py_file in sorted(PLUGIN_DIR.glob("*.py")):
        stem = py_file.stem

        # Skip private/hidden files
        if stem.startswith("_") or stem.startswith("."):
            logger.debug("Skipping plugin file: %s (private/hidden)", py_file.name)
            continue

        # Skip if already loaded (use reload_plugins for refresh)
        if stem in _loaded_plugins:
            loaded.append(stem)
            continue

        try:
            module = _import_plugin_file(py_file)
        except Exception as exc:
            logger.error("Failed to import plugin '%s': %s", py_file.name, exc)
            continue

        tool_dict = getattr(module, "TOOL", None)
        if not isinstance(tool_dict, dict):
            logger.warning(
                "Plugin '%s' has no valid TOOL dict at module level -- skipped.",
                py_file.name,
            )
            continue

        # Validate required keys
        missing = [k for k in ("name", "description", "fn") if k not in tool_dict]
        if missing:
            logger.warning(
                "Plugin '%s' TOOL dict missing keys %s -- skipped.",
                py_file.name,
                missing,
            )
            continue

        name = tool_dict["name"]
        fn = tool_dict["fn"]

        if not callable(fn):
            logger.warning(
                "Plugin '%s' TOOL['fn'] is not callable -- skipped.",
                py_file.name,
            )
            continue

        # Register into TOOL_REGISTRY.
        # Plugin functions are stored as direct callables (not string names)
        # so execute_tool needs to handle both styles -- we store a wrapper.
        TOOL_REGISTRY[name] = {
            "fn": fn,  # direct callable (not a string)
            "description": tool_dict.get("description", ""),
            "args": tool_dict.get("args", ""),
            "plugin": True,  # marker so we know this came from a plugin
        }

        _loaded_plugins[name] = {
            "module": module,
            "file": str(py_file),
            "tool_dict": tool_dict,
        }

        loaded.append(name)
        logger.info("Loaded plugin '%s' from %s", name, py_file.name)

    return loaded


def unload_plugin(name: str) -> bool:
    """Remove a loaded plugin by name.

    Returns True if the plugin was found and removed, False otherwise.
    """
    from src.tools import TOOL_REGISTRY

    info = _loaded_plugins.pop(name, None)
    if info is None:
        logger.warning("Cannot unload '%s': not a loaded plugin.", name)
        return False

    # Remove from tool registry
    TOOL_REGISTRY.pop(name, None)

    # Remove from sys.modules to allow clean reimport later
    mod = info.get("module")
    if mod and mod.__name__ in sys.modules:
        del sys.modules[mod.__name__]

    logger.info("Unloaded plugin '%s'.", name)
    return True


def reload_plugins() -> list[str]:
    """Unload all plugins and re-scan the plugin directory.

    Returns the list of freshly loaded plugin names.
    """
    for name in list(_loaded_plugins):
        unload_plugin(name)
    return load_plugins()


def list_plugins() -> list[dict]:
    """Return metadata for all currently loaded plugins."""
    result = []
    for name, info in _loaded_plugins.items():
        td = info["tool_dict"]
        result.append({
            "name": name,
            "description": td.get("description", ""),
            "args": td.get("args", ""),
            "file": info["file"],
        })
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _import_plugin_file(path: Path):
    """Import a single .py file as a module without polluting the package namespace."""
    module_name = f"omniagent_plugin_{path.stem}"

    # Remove stale entry if re-importing
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
