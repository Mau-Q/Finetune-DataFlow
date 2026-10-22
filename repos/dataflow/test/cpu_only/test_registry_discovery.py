"""Registry discovery must tolerate normal filesystem metadata."""
import dataflow.utils.registry as registry


def test_registry_ignores_metadata_and_non_package_files(tmp_path, monkeypatch):
    package = tmp_path / "dataflow"
    operators = package / "operators"
    operators.mkdir(parents=True)
    for name in ("__init__.py", ".DS_Store", "notes.txt", "loose.py"):
        (operators / name).write_text("")
    for name in ("__pycache__", ".hidden", "invalid-name", "regular", "namespace"):
        (operators / name).mkdir()
    (operators / "regular" / "__init__.py").write_text("")
    monkeypatch.setattr(registry, "__file__", str(package / "utils" / "registry.py"))

    discovered = registry.Registry("operators")
    assert set(discovered.loader_map) == {"regular", "namespace"}


def test_registry_with_only_metadata_has_empty_loader_map(tmp_path, monkeypatch):
    package = tmp_path / "dataflow"
    operators = package / "operators"
    operators.mkdir(parents=True)
    (operators / ".DS_Store").write_text("")
    monkeypatch.setattr(registry, "__file__", str(package / "utils" / "registry.py"))

    assert registry.Registry("operators").loader_map == {}
