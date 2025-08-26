"""LEADFORGE MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from leadforge.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-leadforge[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-leadforge[mcp]'")
        return 1
    app = FastMCP("leadforge")

    @app.tool()
    def leadforge_scan(target: str) -> str:
        """Lightweight MCP-native CRM pipeline with email sequences. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
