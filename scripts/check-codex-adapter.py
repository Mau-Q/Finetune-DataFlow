"""Offline regression check of current Codex JSON events; no model call."""
import asyncio
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
webui = root / "repos/dataflow-webui"
sys.path.insert(0, str(webui / "backend"))
from app.services.agents.codex_adapter import CodexAdapter


async def main():
    adapter = CodexAdapter(cli_path="codex", webui_root=webui,
                           mcp_config_path=webui / ".mcp.json", system_prompt="", allowed_tools="")
    cases = [
        ({"type": "item.completed", "item": {"type": "agent_message", "text": "ready"}}, "text_chunk"),
        ({"type": "item.started", "item": {"id": "1", "type": "mcp_tool_call", "tool": "list_operator_categories"}}, "tool_call_start"),
        ({"type": "item.completed", "item": {"id": "1", "type": "mcp_tool_call", "result": {"ok": True}}}, "tool_call_end"),
        ({"type": "item.completed", "item": {"id": "2", "type": "command_execution", "exit_code": 1}}, "tool_call_end"),
        ({"type": "turn.failed", "error": {"message": "test failure"}}, "error"),
    ]
    for event, expected in cases:
        result = [item async for item in adapter._translate(event)]
        assert len(result) == 1 and result[0]["type"] == expected, result
        if event.get("item", {}).get("exit_code") == 1:
            assert result[0]["is_error"]
    subprocess.run(["codex", "exec", "--cd", str(webui), "--help"], check=True, stdout=subprocess.DEVNULL)
    print("PASS: current CLI directory flag and 5 JSON event cases (no model request)")


asyncio.run(main())
