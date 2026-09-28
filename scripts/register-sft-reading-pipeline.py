"""Validate and save the 13-paper PDF-to-SFT candidate in the local WebUI.

This command registers a dataset and a pipeline. It never executes the pipeline
or calls a model. Credentials remain in the WebUI Serving Manager.
"""

import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
SOURCE = ROOT / "data/sft-reading-13/documents.jsonl"
CONFIG_FILE = ROOT / "pipelines/sft-reading-13.webui.json"
STATE_FILE = ROOT / "pipelines/sft-reading-13.registration.json"
PIPELINE_NAME = "SFT 阅读论文 13 篇 · PDF → 多跳 QA → 评价筛选"
DATASET_NAME = "SFT 阅读论文 13 篇 · PDF 原件"


def api(path, body=None, method=None):
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        BASE + path,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("success") is False:
        raise RuntimeError(result.get("message", "WebUI API failed"))
    return result.get("data", result)


def operator(name, x, role, init=None, run=None):
    return {
        "name": name,
        "location": [x, 160],
        "pipeline_role": role,
        "params": {
            "init": [{"name": key, "value": value} for key, value in (init or {}).items()],
            "run": [{"name": key, "value": value} for key, value in (run or {}).items()],
        },
    }


def assert_source_manifest():
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines()]
    if len(rows) != 13 or len({row["source"] for row in rows}) != 13:
        raise ValueError("Expected exactly 13 distinct PDF sources")
    for row in rows:
        path = Path(row["source"])
        if not path.is_file() or path.suffix.lower() != ".pdf" or path.name != row["source_name"]:
            raise ValueError(f"Invalid PDF source: {path}")


def find_serving(name):
    matches = [item for item in api("/serving/") if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected one WebUI serving named {name!r}, found {len(matches)}")
    return matches[0]["id"]


def ensure_dataset():
    matches = [item for item in api("/datasets/") if item.get("root") == str(SOURCE)]
    if len(matches) > 1:
        raise ValueError("Several WebUI datasets point to the same source manifest")
    if matches:
        dataset = matches[0]
    else:
        dataset = api("/datasets/", {
            "name": DATASET_NAME,
            "root": str(SOURCE),
            "pipeline": "SFTReading13",
            "meta": {"scope": "13 local SFT-related paper PDFs selected by user"},
        })
    columns = api(f"/datasets/columns/{dataset['id']}")
    if not {"source", "source_name"}.issubset(set(columns)):
        raise ValueError(f"Unexpected dataset columns: {columns}")
    return dataset["id"]


def build_config(dataset_id, qwen_plain, deepseek_plain):
    # PandasOperator.run(output_key=...) does not control its transformation; it
    # makes each newly produced field visible to the WebUI field-flow validator.
    expose_question = (
        "lambda df: df.explode('QA_pairs', ignore_index=True).assign("
        "question=lambda d: d['QA_pairs'].map("
        "lambda q: q.get('question', '') if isinstance(q, dict) else ''))"
    )
    expose_answer = (
        "lambda df: df.assign(answer=lambda d: d['QA_pairs'].map("
        "lambda q: q.get('answer', '') if isinstance(q, dict) else ''))"
    )
    valid_qa = (
        "lambda df: df['question'].fillna('').astype(str).str.strip().ne('') "
        "& df['answer'].fillna('').astype(str).str.strip().ne('')"
    )
    score_rule = (
        "lambda df: (df['question_quality_grades'] >= 4) "
        "& (df['answer_alignment_grades'] >= 4) "
        "& (df['answer_verifiability_grades'] >= 4) "
        "& (df['downstream_value_grades'] >= 4) "
        "& (df['AlpagasusScore'] >= 4)"
    )
    export_fields = (
        "lambda df: df.assign(instruction=lambda d: d.get('question', ''), "
        "input=lambda d: d.get('raw_chunk', ''), output=lambda d: d.get('answer', ''))"
    )
    ops = [
        operator("MinerU4PDFParser", 340,
                 "将每篇论文 PDF 交给 MinerU 4 解析，产出后续页面提取所需的结构化文档。",
                 {"mineru_script": str(ROOT / "scripts/mineru.sh"),
                  "output_dir": str(ROOT / "outputs/sft-reading-13/parsing"),
                  "tier": "standard", "timeout_seconds": 900},
                 {"input_key": "source", "output_key": "parsed_document"}),
        operator("MinerU4PageExtractor", 650,
                 "从解析结果中按物理页提取正文和表格，并保留页码与位置证据。",
                 run={"input_key": "parsed_document", "output_key": "source_page"}),
        operator("PaperEvidenceChunker", 960,
                 "将逐页内容切成适合模型处理的重叠文本块，并记录可追溯元数据。",
                 {"tokenizer_path": str(ROOT / "models/tokenizers/Qwen2.5-7B-Instruct"),
                  "chunk_size": 512, "chunk_overlap": 64},
                 {"input_key": "source_page", "output_key": "raw_chunk",
                  "output_meta_key": "chunk_metadata"}),
        operator("KBCTextCleaner", 1270,
                 "清理文本块中的格式噪声，生成用于问答生成的规范论文片段。",
                 {"llm_serving": qwen_plain, "lang": "en"},
                 {"input_key": "raw_chunk", "output_key": "cleaned_chunk"}),
        operator("Text2MultiHopQAGenerator", 1580,
                 "基于清洗后的论文片段生成需要跨信息推理的中文问题、答案和支撑事实。",
                 {"llm_serving": qwen_plain, "lang": "en", "num_q": 2,
                  "prompt_template": {"cls_name": "Text2MultiHopQAGeneratorPrompt",
                                      "params": [{"name": "lang", "value": "zh"}]}},
                 {"input_key": "cleaned_chunk", "output_key": "QA_pairs",
                  "output_meta_key": "QA_metadata"}),
        operator("PandasOperator", 1890,
                 "将每个 QA 对展开成独立样本，并提取 question 字段。",
                 {"process_fn": expose_question},
                 {"output_key": "question"}),
        operator("PandasOperator", 2200,
                 "从已展开的 QA 对中提取 answer 字段。",
                 {"process_fn": expose_answer},
                 {"output_key": "answer"}),
        operator("GeneralFilter", 2510,
                 "剔除问题或答案为空的无效 QA 样本。",
                 {"filter_rules": valid_qa}),
        operator("Text2QASampleEvaluator", 2820,
                 "结合论文原文和支撑事实，从四个维度评价每个 QA 样本。",
                 {"llm_serving": deepseek_plain},
                 {"input_question_key": "question", "input_answer_key": "answer",
                  "input_context_key": "raw_chunk",
                  "input_supporting_facts_key": "QA_pairs",
                  "output_question_quality_key": "question_quality_grades",
                  "output_question_quality_feedback_key": "question_quality_feedbacks",
                  "output_answer_alignment_key": "answer_alignment_grades",
                  "output_answer_alignment_feedback_key": "answer_alignment_feedbacks",
                  "output_answer_verifiability_key": "answer_verifiability_grades",
                  "output_answer_verifiability_feedback_key": "answer_verifiability_feedbacks",
                  "output_downstream_value_key": "downstream_value_grades",
                  "output_downstream_value_feedback_key": "downstream_value_feedbacks"}),
        operator("AlpagasusSampleEvaluator", 3130,
                 "为每个 QA 样本追加整体指令质量评分，作为第二路质量信号。",
                 {"llm_serving": deepseek_plain, "dimension": "quality"},
                 {"input_instruction_key": "question", "input_input_key": "raw_chunk",
                  "input_output_key": "answer", "output_key": "AlpagasusScore"}),
        operator("GeneralFilter", 3440,
                 "仅保留五项质量评分均至少为 4 分的候选样本。",
                 {"filter_rules": score_rule}),
        operator("HashDeduplicateFilter", 3750,
                 "按问题与答案的组合删除重复 QA，避免产生重复训练样本。",
                 run={"input_keys": ["question", "answer"],
                      "output_key": "hash_deduplicated_label"}),
        operator("PandasOperator", 4060,
                 "将通过筛选的记录整理为 instruction、input、output 训练格式。",
                 {"process_fn": export_fields},
                 {"output_key": "instruction"}),
    ]
    return {
        "file_path": str(CONFIG_FILE),
        "input_dataset": {
            "id": dataset_id,
            "location": [30, 160],
            "pipeline_role": "提供 13 篇论文 PDF，作为这条 Pipeline 的原始输入。",
        },
        "operators": ops,
    }


def main():
    assert_source_manifest()
    dataset_id = ensure_dataset()
    config = build_config(dataset_id, find_serving("SFT阅读·Qwen纯文本"),
                          find_serving("SFT阅读·DeepSeek纯文本"))
    validation = api("/pipelines/validate", config)
    if not validation.get("valid"):
        raise RuntimeError(json.dumps(validation.get("errors"), ensure_ascii=False))
    payload = {
        "name": PIPELINE_NAME,
        "config": config,
        "tags": ["paper", "sft", "13-pdf", "candidate", "not-executed"],
    }
    existing = [item for item in api("/pipelines/") if item.get("name") == PIPELINE_NAME]
    if len(existing) > 1:
        raise ValueError("Several WebUI pipelines have the target name")
    if existing:
        pipeline = api(f"/pipelines/{existing[0]['id']}", payload, "PUT")
    else:
        pipeline = api("/pipelines/", payload)
    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    state = {
        "pipeline_id": pipeline["id"], "dataset_id": dataset_id,
        "operator_count": len(config["operators"]), "validation": validation,
        "status": "registered_not_executed",
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset_id,
                      "operators": len(config["operators"]), "valid": validation["valid"],
                      "warnings": len(validation.get("warnings", [])),
                      "status": state["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
