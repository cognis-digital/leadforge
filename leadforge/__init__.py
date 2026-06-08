"""LEADFORGE: MCP-native CRM pipeline with email sequences (stdlib-only)."""

from .core import (
    TOOL_NAME,
    TOOL_VERSION,
    STAGES,
    Engine,
    Lead,
    LeadForgeError,
    DEFAULT_SEQUENCES,
)

__all__ = [
    "TOOL_NAME",
    "TOOL_VERSION",
    "STAGES",
    "Engine",
    "Lead",
    "LeadForgeError",
    "DEFAULT_SEQUENCES",
]
