"""Optional LightRAG wiring with local stubs; never executes an API request."""
import asyncio
import builtins
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from dataflow.serving.light_rag_serving import initialize_rag, LightRAGServing

pytestmark = pytest.mark.cpu


def test_initializer_reports_optional_dependency(monkeypatch):
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == 'lightrag' or name.startswith('lightrag.'):
            raise ImportError('fixture missing dependency')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', importing)
    with pytest.raises(ImportError, match='optional lightrag-hku'):
        asyncio.run(initialize_rag('model','url','key','embed','host',8,20))


def test_initializer_and_query_use_lazy_dependencies(monkeypatch):
    modules = {name: ModuleType(name) for name in ('lightrag','lightrag.llm','lightrag.llm.openai',
               'lightrag.llm.ollama','lightrag.utils','lightrag.kg','lightrag.kg.shared_storage')}
    rag = SimpleNamespace(initialize_storages=AsyncMock(), aquery=AsyncMock(return_value='answer'))
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return rag
    modules['lightrag'].LightRAG = factory
    modules['lightrag'].QueryParam = lambda **kwargs: kwargs
    modules['lightrag.llm.openai'].openai_complete_if_cache = AsyncMock(return_value='llm')
    modules['lightrag.llm.ollama'].ollama_embed = AsyncMock(return_value=[[1]])
    modules['lightrag.utils'].EmbeddingFunc = lambda **kwargs: SimpleNamespace(**kwargs)
    modules['lightrag.kg.shared_storage'].initialize_pipeline_status = AsyncMock()
    for name, module in modules.items(): monkeypatch.setitem(sys.modules, name, module)
    assert asyncio.run(initialize_rag('model','url','key','embed','host',8,20)) is rag
    assert asyncio.run(captured['llm_model_func']('prompt')) == 'llm'
    assert asyncio.run(captured['embedding_func'].func(['text'])) == [[1]]
    serving=LightRAGServing.__new__(LightRAGServing); serving.rag=rag
    assert asyncio.run(serving.generate_from_input(['question'], 'system')) == ['answer']
    assert rag.aquery.call_args.kwargs['param'] == {'mode':'hybrid'}
