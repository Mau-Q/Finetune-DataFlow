#!/usr/bin/env python3
"""Check portable component pins and publication boundaries without dependencies."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main():
    errors = []
    manifest = json.loads((ROOT / "locks/components.json").read_text())
    for component in manifest["components"]:
        path = component["path"]
        if component.get("kind") == "source":
            folder = ROOT / path
            entrypoint = folder / component["entrypoint"]
            if not entrypoint.is_file():
                errors.append(f"{path}: missing repository source {component['entrypoint']}")
            provenance_path = folder / "UPSTREAM.json"
            try:
                provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                if provenance["url"] != component["url"] or provenance["commit"] != component["commit"]:
                    errors.append(f"{path}: source provenance differs from manifest")
            except (OSError, ValueError, KeyError):
                errors.append(f"{path}: invalid UPSTREAM.json")
            entry = git("ls-files", "--stage", "--", str(entrypoint.relative_to(ROOT))).split()
            if not entry or entry[0] not in {"100644", "100755"}:
                errors.append(f"{path}: source must be tracked as ordinary files")
            if (folder / ".git").exists():
                errors.append(f"{path}: unexpected nested Git repository")
            continue
        entry = git("ls-files", "--stage", "--", path).split()
        if len(entry) < 2 or entry[0] != "160000" or entry[1] != component["commit"]:
            errors.append(f"{path}: gitlink differs from locks/components.json")
        if not (ROOT / path / ".git").exists():
            if not component.get("optional"):
                errors.append(f"{path}: initialize with git submodule update --init")
            continue
        actual = git("-C", path, "rev-parse", "HEAD")
        if actual != component["commit"]:
            errors.append(f"{path}: checkout is {actual}, expected {component['commit']}")
        url = git("config", "-f", ".gitmodules", "--get", f"submodule.{path}.url")
        if url != component["url"]:
            errors.append(f"{path}: submodule URL differs from manifest")

    # Check the tracked tree, including accidentally force-added runtime files.
    forbidden = {"data", "models", "logs", "output", "outputs", ".venvs", ".playwright-cli"}
    for name in git("ls-files").splitlines():
        parts = Path(name).parts
        # This tracked frontend file contains public build configuration only.
        public_build_config = name == "repos/dataflow-webui/frontend/.env.production"
        if parts[0] in forbidden or (not public_build_config and any(part == ".env" or part.startswith(".env.") for part in parts)):
            errors.append(f"Runtime or secret file tracked: {name}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Workspace OK: integrated sources, provenance, optional pins and tracked-file boundaries match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
