"""Research-only probes. Uses real upstream operators with a loopback fixture API.

No remote model is called. Run in separate processes with the chosen repo on
PYTHONPATH; do not import DataFlow and DataFlow-MM into the same interpreter.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


QUESTION = "What color is the square?"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def prepare(root, workspace):
    """Generate a synthetic one-page PDF and actually parse it with local MinerU."""
    import pymupdf
    from PIL import Image, ImageDraw
    assets = root / "fixtures"
    if assets.exists():
        raise FileExistsError("Use a fresh --output directory to preserve earlier evidence")
    assets.mkdir(parents=True)
    image = Image.new("RGB", (180, 180), "white")
    ImageDraw.Draw(image).rectangle((35, 35, 145, 145), fill="red")
    image.save(assets / "red-square.png")
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 60), "Research fixture: visual SFT interoperability", fontsize=16)
        page.insert_text((50, 90), "A red square is shown below. Equation: E = m c^2.", fontsize=12)
        page.insert_image(pymupdf.Rect(50, 120, 230, 300), filename=str(assets / "red-square.png"))
        page.insert_text((50, 340), "Item       Value\nAlpha      0.1\nBeta       0.7", fontsize=12)
        doc.save(assets / "one-page.pdf")
        page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(assets / "page-1.png")
    command = [str(workspace / "scripts/mineru.sh"), "parse", str(assets / "one-page.pdf"),
               "-o", str(root / "mineru4.zip"), "--format", "zip", "--pages", "1",
               "--tier", "standard", "--disable-image-analysis"]
    with (root / "mineru4.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    with zipfile.ZipFile(root / "mineru4.zip") as archive:
        document = json.loads(archive.read("structured_content.json"))
        image_sources = [b["image_source"] for p in document["pages"] for b in p.get("blocks", []) if b.get("image_source")]
        assert len(document["pages"]) == 1 and image_sources
        (assets / "mineru4-crop.jpg").write_bytes(archive.read(image_sources[0]))
        report = {"pages": 1, "members": archive.namelist(), "image_sources": image_sources,
                  "old_content_list_present": any(n.endswith("_content_list.json") for n in archive.namelist())}
    dump(root / "prepare-report.json", report)
    dump(root / "fixtures-manifest.json", {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
         "bytes": p.stat().st_size} for p in assets.iterdir() if p.is_file()})
    print(json.dumps(report))


class FixtureServer:
    """Deterministic transport fixture, explicitly not a vision model."""

    def __init__(self):
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompts, image_hashes = [], []
                for msg in body["messages"]:
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        if msg["role"] == "user":
                            prompts.append(content)
                    else:
                        for item in content:
                            if item["type"] == "text" and msg["role"] == "user":
                                prompts.append(item["text"])
                            if item["type"] == "image_url":
                                url = item["image_url"]["url"]
                                assert url.startswith("data:image/")
                                image_hashes.append(hashlib.sha256(base64.b64decode(url.split(",", 1)[1])).hexdigest())
                text = "\n".join(prompts)
                owner.requests.append({"path": self.path, "prompts": prompts,
                                       "image_hashes": image_hashes,
                                       "response_format": body.get("response_format"),
                                       "stream": body.get("stream", False)})
                if "FAIL_REQUEST" in text:
                    self.send_response(400)
                    result = {"error": {"message": "fixture failure", "type": "invalid_request_error"}}
                else:
                    self.send_response(200)
                    if "JSON_QA" in text:
                        answer = json.dumps({"question": QUESTION, "answer": "red"})
                    elif "TASK_QUESTION" in text:
                        answer = QUESTION
                    elif "What color" in text:
                        answer = "red"
                    else:
                        answer = "fixture caption"
                    result = {"id": "fixture-response", "object": "chat.completion", "created": 0,
                              "model": "fixture-vlm", "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": answer}}]}
                payload = json.dumps(result).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def probe(engine, root, workspace):
    import dataflow
    import inspect
    import pandas as pd
    from dataflow.utils.storage import FileStorage, DummyStorage
    from dataflow.operators.core_vision import PromptedVQAGenerator
    from dataflow.serving.api_vlm_serving_openai import APIVLMServing_openai

    if engine == "core":
        class ProbeMemoryStorage(DummyStorage):
            # The installed core DummyStorage omits this abstract method.
            def get_keys_from_dataframe(self):
                return list(self._data.columns)
        DummyStorage = ProbeMemoryStorage

    expected = workspace / "repos" / ("dataflow" if engine == "core" else "dataflow-mm")
    assert Path(dataflow.__file__).resolve().is_relative_to(expected)
    out = root / engine
    out.mkdir(parents=True, exist_ok=True)
    images = [root / "fixtures" / name for name in ("red-square.png", "page-1.png")]
    crop = root / "fixtures/mineru4-crop.jpg"
    if crop.exists():
        images.append(crop)
    expected_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in images]
    checks, observations = [], {}
    os.environ["DF_RESEARCH_FIXTURE_KEY"] = "local-fixture-only-not-a-real-key"

    with FixtureServer() as api:
        serving = APIVLMServing_openai(api_url=api.url,
            key_name_of_api_key="DF_RESEARCH_FIXTURE_KEY", model_name="fixture-vlm", max_workers=1, timeout=5)
        serving.client = serving.client.with_options(max_retries=0)
        if engine == "core":
            input_file = out / "input.jsonl"
            input_file.write_text("\n".join(json.dumps({"id": i, "raw_content": str(p)}) for i, p in enumerate(images)) + "\n")
            store = FileStorage(str(input_file), cache_path=str(out / "cache"), cache_type="jsonl")
            op = PromptedVQAGenerator(llm_serving=serving, system_prompt="JSON_QA")
            op.run(store.step(), input_key="raw_content", output_key="generated")
            result = store.step().read("dataframe")
            assert len(result) == len(images) and all(json.loads(x)["answer"] == "red" for x in result["generated"])
            checks.append("core_real_operator_http_and_jsonl")
            assert [r["image_hashes"] for r in api.requests] == [[h] for h in expected_hashes]
            checks.append("core_transmitted_exact_image_bytes")
            schema = {"type": "object", "properties": {"question": {"type": "string"}, "answer": {"type": "string"}}, "required": ["question", "answer"], "additionalProperties": False}
            serving.generate_from_input([str(images[0])], "JSON_QA", json_schema=schema)
            assert api.requests[-1]["response_format"]["json_schema"]["schema"] == schema
            checks.append("core_serving_schema_forwarding")
            bad = DummyStorage()
            bad.set_data(pd.DataFrame({"raw_content": [str(images[0]), ""]}))
            try:
                op.run(bad, input_key="raw_content", output_key="generated")
            except ValueError as exc:
                observations["empty_input_row"] = str(exc)
            else:
                raise AssertionError("Expected upstream row-count mismatch was not reproduced")
            checks.append("core_empty_row_alignment_gap_reproduced")
            from dataflow.operators.core_text import PromptedGenerator
            from dataflow.serving import APILLMServing_request
            from paper_dataflow.operators.paper.generate.preparation import MinerU4PageExtractor
            archive = root / "mineru4.zip"
            page_store = DummyStorage()
            page_store.set_data(pd.DataFrame([{"parsed_document": {
                "document_id": "fixture-pdf",
                "archive_path": str(archive),
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}}]))
            MinerU4PageExtractor().run(page_store)
            pages = page_store.read("dataframe").to_dict("records")
            assert len(pages) == 1 and pages[0]["source_page"]["page_number"] == 1
            assert "red square" in pages[0]["source_page"]["text"]
            dump(out / "extracted-pages.json", pages)
            checks.append("real_mineru4_archive_to_existing_page_extractor")
            text_store = DummyStorage()
            text_store.set_data(pd.DataFrame([{"text": pages[0]["source_page"]["text"]}]))
            text_serving = APILLMServing_request(api_url=api.url + "/chat/completions",
                key_name_of_api_key="DF_RESEARCH_FIXTURE_KEY", model_name="fixture-vlm", max_workers=1, max_retries=1)
            PromptedGenerator(llm_serving=text_serving, user_prompt="JSON_QA ", json_schema=schema).run(
                text_store, input_key="text", output_key="qa")
            assert json.loads(text_store.read("dataframe").iloc[0]["qa"])["answer"] == "red"
            assert api.requests[-1]["image_hashes"] == [] and api.requests[-1]["response_format"]
            text_serving.cleanup()
            checks.append("pdf_text_to_real_core_generator_schema_http")
            observations["core_retry_parameter"] = "max_retries counts attempts, used 1 for one request; 0 would send no requests"
            rows = [{"id": int(r["id"]), "question": json.loads(r["generated"])["question"],
                     "answer": json.loads(r["generated"])["answer"], "image": r["raw_content"]}
                    for r in result.to_dict("records")]
        else:
            from dataflow.operators.core_vision import PromptTemplatedVQAGenerator, BatchVQAGenerator
            from dataflow.prompts.prompt_template import NamedPlaceholderPromptTemplate

            # Execute upstream image_vqa.py forward(), overriding only fixture
            # credentials, endpoint, input path and cache. Upstream source stays intact.
            spec = importlib.util.spec_from_file_location("research_image_vqa",
                expected / "dataflow/statics/pipelines/api_pipelines/image_vqa.py")
            module = importlib.util.module_from_spec(spec)
            original_key = os.environ.get("DF_API_KEY")
            try:
                spec.loader.exec_module(module)
            finally:
                if original_key is None:
                    os.environ.pop("DF_API_KEY", None)
                else:
                    os.environ["DF_API_KEY"] = original_key
            module.APIVLMServing_openai = lambda **_: serving
            pipe = module.ImageVQAPipeline()
            input_file = out / "input.jsonl"
            input_file.write_text("\n".join(json.dumps({"id": i, "image": [str(p)],
                "conversation": [{"from": "human", "value": "TASK_QUESTION"}]}) for i, p in enumerate(images)) + "\n")
            pipe.storage = FileStorage(str(input_file), cache_path=str(out / "cache"), cache_type="jsonl")
            pipe.forward()
            result = pipe.storage.step().read("dataframe")
            assert result["question"].tolist() == [QUESTION] * len(images) and result["answer"].tolist() == ["red"] * len(images)
            checks.append("mm_official_two_stage_image_vqa_pipeline_http_and_jsonl")
            assert [r["image_hashes"] for r in api.requests] == [[h] for h in expected_hashes] * 2
            assert api.requests[len(images)]["prompts"] == [QUESTION]
            checks.append("mm_exact_image_bytes_and_question_forwarding")

            templated = PromptTemplatedVQAGenerator(serving=serving,
                prompt_template=NamedPlaceholderPromptTemplate("JSON_QA {topic}"))
            memory = DummyStorage()
            memory.set_data(pd.DataFrame([{"image": [str(images[0]), str(images[1])], "topic": "square"}]))
            templated.run(memory, input_image_key="image", topic="topic")
            assert api.requests[-1]["image_hashes"] == expected_hashes[:2]
            assert "JSON_QA square" in api.requests[-1]["prompts"]
            assert json.loads(memory.read("dataframe").iloc[0]["answer"])["answer"] == "red"
            checks.append("mm_multi_image_dynamic_template")
            observations["mm_messages_schema_parameter"] = "json_schema" in inspect.signature(serving.generate_from_input_messages).parameters

            batch = DummyStorage()
            batch.set_data(pd.DataFrame([{"image": [str(images[0])], "questions": [QUESTION, QUESTION]}]))
            BatchVQAGenerator(serving=serving).run(batch, input_prompts_key="questions", input_image_key="image", output_key="answers")
            assert batch.read("dataframe").iloc[0]["answers"] == ["red", "red"]
            checks.append("mm_one_image_many_questions")

            absent = DummyStorage()
            absent.set_data(pd.DataFrame([{"conversation": [{"from": "human", "value": "JSON_QA"}]}]))
            missing_op = PromptedVQAGenerator(serving=serving)
            missing_op.run(absent, input_image_key="missing_image", output_answer_key="generated")
            assert api.requests[-1]["image_hashes"] == []
            observations["missing_image_column"] = "silently falls back to text-only"
            checks.append("mm_missing_image_fallback_gap_reproduced")

            failed = DummyStorage()
            failed.set_data(pd.DataFrame([{"image": [str(images[0])], "prompt": "FAIL_REQUEST"}]))
            missing_op.run(failed, input_prompt_key="prompt", input_image_key="image", output_answer_key="generated")
            failure = failed.read("dataframe").iloc[0]["generated"]
            assert failure.startswith("Error:")
            observations["http_failure"] = "written as ordinary Error: string, no structured failure status"
            checks.append("mm_error_string_gap_reproduced")
            from dataflow.operators.core_vision import VisionDependentFilter
            dependency = DummyStorage()
            dependency.set_data(pd.DataFrame([{"image": [str(images[0])], "question": QUESTION, "answer": "red"}]))
            try:
                VisionDependentFilter(rollout=serving, verifier=serving).run(dependency)
            except AttributeError as exc:
                assert "generate_from_input_with_message" in str(exc)
                observations["vision_dependency_filter_api"] = str(exc)
            else:
                raise AssertionError("Expected vision filter API mismatch was not reproduced")
            checks.append("mm_optional_vision_filter_api_mismatch_reproduced")
            observations["upstream_pipeline_constructor"] = "ignores llm_serving argument; module overwrites DF_API_KEY with placeholder; fixture overrides both"
            rows = [{"id": int(r["id"]), "question": r["question"], "answer": r["answer"], "image": r["image"][0]}
                    for r in result.to_dict("records")]
        serving.cleanup()
        dump(out / "transport.json", api.requests)
    dump(out / "normalized.json", rows)
    report = {"engine": engine, "source": dataflow.__file__, "validation": "real upstream operators + deterministic loopback HTTP, no real VLM",
              "checks": checks, "observations": observations, "row_count": len(rows)}
    dump(out / "report.json", report)
    print(json.dumps(report, ensure_ascii=False))


def export(root, workspace):
    """Small explicit PoC adapter: MM envelope -> core VQAFormatter -> portable package."""
    import pandas as pd
    import dataflow
    from dataflow.utils.storage import DummyStorage
    from dataflow.operators.pdf2vqa import VQAFormatter

    class ProbeMemoryStorage(DummyStorage):
        def get_keys_from_dataframe(self):
            return list(self._data.columns)

    assert Path(dataflow.__file__).resolve().is_relative_to(workspace / "repos/dataflow")
    package = root / "training-package"
    media = package / "images"
    media.mkdir(parents=True, exist_ok=True)
    rows = json.loads((root / "mm/normalized.json").read_text())
    mapped = []
    for row in rows:
        source = Path(row["image"])
        target = media / (hashlib.sha256(source.read_bytes()).hexdigest() + source.suffix)
        shutil.copyfile(source, target)
        mapped.append({"vqa_pair": {"question": row["question"] + f" ![source]({target})", "answer": row["answer"]}})
    storage = ProbeMemoryStorage()
    storage.set_data(pd.DataFrame(mapped))
    previous = Path.cwd()
    try:
        os.chdir(package)
        VQAFormatter().run(storage, input_qa_item_key="vqa_pair")
    finally:
        os.chdir(previous)
    exported = storage.read("dataframe").to_dict("records")
    for record in exported:
        record["images"] = [str(Path(p).relative_to(package)) for p in record["images"]]
        assert all((package / p).is_file() for p in record["images"])
        assert record["messages"][0]["content"].count("<image>") == len(record["images"])
    (package / "train.jsonl").write_text("\n".join(json.dumps(r) for r in exported) + "\n")
    shutil.make_archive(str(root / "training-package"), "zip", root_dir=package)
    # Demonstrate that the unwrapped formatter also accepts a nonexistent image.
    formatter = VQAFormatter()
    missing = formatter._convert_row({"vqa_pair": {"question": "Q ![x](absent.png)", "answer": "A"}},
        "vqa_pair", "question", "answer", "solution", "messages", "images", str(package), {})
    assert missing and not Path(missing["images"][0]).exists()
    report = {"rows": len(exported), "checks": ["mm_to_core_json_file_boundary", "real_core_vqa_formatter", "all_exported_media_exist", "image_token_count_matches", "portable_relative_paths", "formatter_missing_image_gap_reproduced"],
              "adapter_scope": "research-only explicit field mapping and media copy, not platform integration"}
    dump(root / "export-report.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["prepare", "core", "mm", "export"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[2]
    root = args.output.resolve()
    if args.engine == "prepare":
        prepare(root, workspace)
    elif args.engine == "export":
        export(root, workspace)
    else:
        probe(args.engine, root, workspace)
