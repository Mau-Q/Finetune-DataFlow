"""Static source inventory; signatures are evidence of code, not execution."""
import ast
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess


WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUT = WORKSPACE / "outputs/dataflow-mm-research-2026-10-19"


def signature(node):
    return ast.unparse(node.args) if node else None


def scan(repo, groups):
    operators, pipelines = [], []
    for group in groups:
        base = repo / "dataflow/operators" / group
        init = base / "__init__.py"
        exports = {a.name for n in ast.walk(ast.parse(init.read_text()))
                   if isinstance(n, ast.ImportFrom) for a in n.names} if init.exists() else set()
        for path in sorted(base.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
                if not any("OPERATOR_REGISTRY.register" in ast.unparse(d) for d in cls.decorator_list):
                    continue
                methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
                operators.append({"class": cls.name, "category": group,
                    "path": str(path.relative_to(repo)), "line": cls.lineno,
                    "public_lazy_export": cls.name in exports,
                    "init": signature(methods.get("__init__")), "run": signature(methods.get("run")),
                    "imports": [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]})
    for path in sorted((repo / "dataflow/statics").rglob("*.py")):
        if "pipelines" not in path.parts:
            continue
        if not any(s in path.stem for s in ["image", "vision", "vqa", "text_sft", "text2qa", "kbcleaning"]):
            continue
        tree = ast.parse(path.read_text())
        imports = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
            forward = methods.get("forward")
            calls = [ast.unparse(n) for n in ast.walk(forward) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and n.func.attr == "run"] if forward else []
            pipelines.append({"class": cls.name, "path": str(path.relative_to(repo)),
                "line": cls.lineno, "init": signature(methods.get("__init__")),
                "imports": imports, "operator_calls": calls})
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    return {"revision": revision, "operators": operators, "pipelines": pipelines,
            "operator_counts": dict(Counter(r["category"] for r in operators)),
            "public_export_count": sum(r["public_lazy_export"] for r in operators)}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {"core": scan(WORKSPACE / "repos/dataflow", ["core_text", "text_sft", "knowledge_cleaning", "core_vision", "pdf2vqa"]),
              "mm": scan(WORKSPACE / "repos/dataflow-mm", ["core_vision"])}
    from packaging.requirements import Requirement
    requirements = []
    for line in (WORKSPACE / "repos/dataflow-mm/requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        try:
            version = importlib.metadata.version(req.name)
        except importlib.metadata.PackageNotFoundError:
            version = None
        requirements.append({"requirement": line, "available_in_shared_research_dependencies": version,
                             "satisfies_declared_specifier": version is not None and version in req.specifier})
    report["mm_dependency_audit"] = requirements
    path = OUTPUT / "inventory.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    concise = {k: {"revision": v["revision"], "operators": v["operator_counts"],
                  "public_export_count": v["public_export_count"], "pipelines": len(v["pipelines"])}
               for k, v in report.items() if k in ["core", "mm"]}
    concise["inventory_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUTPUT / "inventory-summary.json").write_text(json.dumps(concise, indent=2) + "\n")
    lines = ["# DataFlow 与 DataFlow-MM 相关源码索引", "",
             "本索引由 `scripts/research/inventory_dataflow_vision.py` 从固定源码生成。它列出声明与调用位置，不代表全部算子已安装依赖、执行或通过质量验收。完整签名和 Pipeline 调用见本地 `outputs/dataflow-mm-research-2026-10-19/inventory.json`。", ""]
    for key, dirname in [("core", "dataflow"), ("mm", "dataflow-mm")]:
        data = report[key]
        lines += [f"## {key}：`{data['revision']}`", "", "### 算子", "",
                  "| 类 | 类别/步骤 | 父模块惰性导出 | 源码 |", "| --- | --- | --- | --- |"]
        for row in data["operators"]:
            path = row["path"]
            lines.append(f"| `{row['class']}` | {row['category']}/{Path(path).parent.name} | {'是' if row['public_lazy_export'] else '否'} | [文件](../../repos/{dirname}/{path}) |")
        lines += ["", "### 相关 Pipeline（包括仅供后续参考的高级流程）", "",
                  "| 类 | 实际 run 调用数 | 源码 |", "| --- | --- | --- |"]
        for row in data["pipelines"]:
            lines.append(f"| `{row['class']}` | {len(row['operator_calls'])} | [文件](../../repos/{dirname}/{row['path']}) |")
        lines.append("")
    index = WORKSPACE / "docs/research/dataflow-vision-source-index.md"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("\n".join(lines).rstrip() + "\n")
    print(json.dumps(concise))


if __name__ == "__main__":
    main()
