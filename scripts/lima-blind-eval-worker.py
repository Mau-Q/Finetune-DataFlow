"""Evaluate one reserved LIMA blind batch concurrently without changing its frozen runner."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("lima_blind_eval", ROOT / "scripts/lima-blind-qa-eval.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-index", type=int, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["runner_sha256"] != judge.sha(judge.__file__):
        raise ValueError("Frozen judge runner changed")
    for name, expected in manifest["artifact_sha256"].items():
        if judge.sha(output / name) != expected:
            raise ValueError("Frozen judge artifact changed: " + name)
    batches = json.loads((output / "blind-batches.json").read_text())
    number = args.batch_index
    if not 1 <= number <= len(batches):
        raise ValueError("Invalid batch index")
    batch = batches[number - 1]
    dest = output / "execution" / f"batch-{number:02d}"
    dest.mkdir(exist_ok=False)
    judge.write_json(dest / "batch.json", batch)
    cli = shutil.which("codex")
    if not cli:
        raise ValueError("Codex CLI unavailable")
    with tempfile.TemporaryDirectory(prefix="lima-blind-judge-worker-") as temp:
        workdir = Path(temp)
        shutil.copyfile(output / "schema.json", workdir / "schema.json")
        with (dest / "events.jsonl").open("x") as events, (dest / "stderr.log").open("x") as stderr:
            proc = subprocess.run(judge.cli_command(cli, workdir), input=judge.prompt(batch), text=True,
                                  stdout=events, stderr=stderr, cwd=workdir, timeout=600)
        if proc.returncode:
            raise RuntimeError(f"Judge batch {number} exited {proc.returncode}")
        value = json.loads((workdir / "answer.json").read_text())
        judge.validate(value, batch, json.loads((output / "schema.json").read_text()))
        judge.write_json(dest / "result.json", value)
    print(f"Judged reserved batch {number}", flush=True)


if __name__ == "__main__":
    main()
