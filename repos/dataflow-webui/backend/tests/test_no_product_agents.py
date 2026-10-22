"""The product has no Agent process launcher, chat route or MCP transport."""
from pathlib import Path


def test_removed_agent_surface():
    root=Path(__file__).resolve().parents[2]
    for name in ('backend/app/mcp_server.py','backend/app/api/v1/endpoints/agent.py','backend/app/services/agent_session.py','backend/app/services/agents','frontend/src/components/manage/chatPanel'):
        assert not (root/name).exists()
    router=(root/'backend/app/api/v1/router.py').read_text()
    assert 'agent.router' not in router
    main=(root/'backend/app/main.py').read_text()
    assert 'create_mcp_server' not in main
    frontend=(root/'frontend/src/views/manage/dataflow/index.vue').read_text()
    assert 'chatPanel' not in frontend and 'agentSyncPayload' not in frontend and 'AI Assistant' not in frontend
