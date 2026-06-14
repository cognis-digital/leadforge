"""LEADFORGE MCP server — exposes pipeline() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
import json
import sys

from leadforge.core import Engine, LeadForgeError


def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-leadforge[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print(
            "Install the MCP extra: pip install 'cognis-leadforge[mcp]'",
            file=sys.stderr,
        )
        return 1
    app = FastMCP("leadforge")

    @app.tool()
    def leadforge_pipeline() -> str:
        """Return a JSON pipeline summary (stage counts + values + win-rate)."""
        try:
            eng = Engine()
            return json.dumps(eng.pipeline(), indent=2)
        except LeadForgeError as exc:
            return json.dumps({"error": str(exc)})

    app.run()
    return 0
