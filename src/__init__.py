"""DevAssistant MCP Server v2.1."""

import sys as _sys

__version__ = "2.1.0"

# Ensure `from src.core...` works identically both when running from repo root
# and when installed as the `dev_assistant_mcp` wheel via pip/uvx.
_sys.modules.setdefault("src", _sys.modules[__name__])
