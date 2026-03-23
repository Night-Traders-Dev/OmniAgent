#!/usr/bin/env python3
"""
OmniAgent MCP Server — stdio transport.

Launch this as a subprocess to expose OmniAgent's 47 tools, resources,
and prompts to any MCP client (Claude Desktop, Claude Code, etc.).

Usage:
  python mcp_server.py

Claude Desktop config (~/.config/claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "omniagent": {
        "command": "python",
        "args": ["/path/to/OmniAgent/mcp_server.py"],
        "env": {
          "PYTHONPATH": "/path/to/OmniAgent"
        }
      }
    }
  }

Claude Code config:
  claude mcp add omniagent python /path/to/OmniAgent/mcp_server.py
"""
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MCP] %(message)s",
    stream=sys.stderr,  # Logs go to stderr, protocol goes to stdout
)

from src.mcp import StdioTransport

if __name__ == "__main__":
    transport = StdioTransport()
    transport.run()
