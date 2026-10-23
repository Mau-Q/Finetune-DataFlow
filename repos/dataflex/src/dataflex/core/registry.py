import inspect
from typing import Dict, Type, Any, Optional

class Registry:
    def __init__(self):
        self._store: Dict[str, Dict[str, Type]] = {}

    def register(self, kind: str, name: str):
        def deco(cls: Type):
            self._store.setdefault(kind, {})
            if name in self._store[kind]:
                raise ValueError(f"{kind}.{name} already registered")
            self._store[kind][name] = cls
            return cls
        return deco

    def get(self, kind: str, name: str) -> Type:
        return self._store[kind][name]

    def build(self, kind: str, name: str, *, runtime: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None):
        cls = self.get(kind, name)
        cfg = cfg or {}
        merged = {**cfg, **runtime}                     # Runtime dependencies take precedence
        sig = inspect.signature(cls.__init__)
        parameters = list(sig.parameters.values())[1:]
        accepted = {p.name for p in parameters if p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)}
        filtered = {k: v for k, v in merged.items() if k in accepted}   # Only feed needed
        if any(p.kind == p.VAR_KEYWORD for p in parameters):
            # Forward user configuration accepted through **kwargs, but do not
            # leak unrelated trainer runtime objects into a component's bases.
            filtered.update({k: merged[k] for k in cfg if k not in accepted})
        return cls(**filtered)

REGISTRY = Registry()
def register_selector(name: str): return REGISTRY.register("selector", name)
def register_mixer(name: str):    return REGISTRY.register("mixer", name)
def register_weighter(name: str):    return REGISTRY.register("weighter", name)
def register_reorder(name: str):   return REGISTRY.register("reorder", name)
