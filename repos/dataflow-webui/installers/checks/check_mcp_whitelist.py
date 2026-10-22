#!/usr/bin/env python3
"""Compatibility entry point: ensure the removed product Agent/MCP server stays removed."""
from pathlib import Path
root=Path(__file__).resolve().parents[2]
for path in ('backend/app/mcp_server.py','backend/app/api/v1/endpoints/agent.py','frontend/src/components/manage/chatPanel'):
    assert not (root/path).exists(), f'Removed product entry returned: {path}'
print('No product Agent or MCP entry points')
