"""MinerU 4 runs in its own environment; only files cross that boundary."""

import hashlib
import json
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

import pandas as pd
from dataflow.core import OperatorABC
from dataflow.utils.registry import OPERATOR_REGISTRY
from dataflow.utils.storage import DataFlowStorage


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_input(storage, input_key, *output_keys):
    frame = storage.read("dataframe")
    if input_key not in frame.columns:
        raise ValueError(f"Missing {input_key!r}; available columns: {list(frame.columns)}")
    if len(set(output_keys)) != len(output_keys) or set(output_keys) & set(frame.columns):
        raise ValueError(f"Output fields must be new and distinct: {output_keys}")
    if frame.empty:
        raise ValueError("Input dataset is empty")
    return frame


@OPERATOR_REGISTRY.register()
class MinerU4PDFParser(OperatorABC):
    def __init__(self, mineru_script: str, output_dir: str, tier: str = "standard", timeout_seconds: int = 900):
        super().__init__()
        self.script = Path(mineru_script).expanduser().resolve(strict=True)
        self.output_dir = Path(output_dir).expanduser().resolve()
        if tier not in {"basic", "standard", "advanced"}:
            raise ValueError("MinerU tier must be basic, standard or advanced")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.tier, self.timeout_seconds = tier, timeout_seconds

    @staticmethod
    def get_desc(lang: str = "zh"):
        return ("通过独立环境运行 MinerU 4；保存 PDF 快照、SHA-256、结构化 ZIP 和解析日志。输入 source_path，输出 parsed_document。"
                if lang == "zh" else "Run MinerU 4 in its isolated environment; retain PDF snapshot, SHA-256, structured ZIP and log.")

    def run(self, storage: DataFlowStorage, input_key: str = "source_path", output_key: str = "parsed_document"):
        frame = read_input(storage, input_key, output_key)
        results = []
        for value in frame[input_key]:
            source = Path(value).expanduser().resolve(strict=True)
            if source.suffix.lower() != ".pdf" or not source.is_file():
                raise ValueError(f"Expected a local PDF: {source}")
            run_dir = self.output_dir / uuid.uuid4().hex
            run_dir.mkdir(parents=True, exist_ok=False)
            snapshot = run_dir / "source.pdf"
            shutil.copyfile(source, snapshot)
            document_id = sha256(snapshot)
            archive = run_dir / "parsed.zip"
            log_path = run_dir / "parse.log"
            command = [str(self.script), "parse", str(snapshot), "-o", str(archive), "--format", "zip", "--tier", self.tier]
            with log_path.open("w") as log:
                try:
                    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=self.timeout_seconds)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    raise RuntimeError(f"MinerU parsing failed; see {log_path}") from exc
            with zipfile.ZipFile(archive) as bundle:
                document = json.loads(bundle.read("structured_content.json"))
            producer = document.get("metadata", {}).get("producer", {})
            if not str(producer.get("version", "")).startswith("4."):
                raise ValueError(f"Expected MinerU 4 output; producer={producer}")
            if document.get("is_full_document") is not True or not document.get("pages"):
                raise ValueError("MinerU output is incomplete or has no pages")
            result = {
                "document_id": document_id, "source_path": str(source), "snapshot_path": str(snapshot),
                "archive_path": str(archive), "archive_sha256": sha256(archive),
                "producer": producer, "tier": self.tier, "log_path": str(log_path),
                "wrapper_sha256": sha256(self.script),
            }
            (run_dir / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            results.append(result)
        frame[output_key] = results
        storage.write(frame)
        return [output_key]


@OPERATOR_REGISTRY.register()
class MinerU4PageExtractor(OperatorABC):
    def __init__(self):
        super().__init__()

    @staticmethod
    def get_desc(lang: str = "zh"):
        return ("从 MinerU 4 ZIP 提取逐页原文和表格 Markdown，保留物理页码、块坐标与字符区间；空白页明确标记。"
                if lang == "zh" else "Extract page text and Markdown tables with physical page numbers, block boxes and character offsets; flag empty pages.")

    def run(self, storage: DataFlowStorage, input_key: str = "parsed_document", output_key: str = "source_page"):
        frame = read_input(storage, input_key, output_key)
        rows = []
        for row in frame.to_dict("records"):
            parsed = row[input_key]
            if sha256(parsed["archive_path"]) != parsed["archive_sha256"]:
                raise ValueError("Parsed archive changed since the parser produced its manifest")
            with zipfile.ZipFile(parsed["archive_path"]) as bundle:
                document = json.loads(bundle.read("structured_content.json"))
            seen = set()
            for page in document["pages"]:
                page_idx = page["page_idx"]
                if not isinstance(page_idx, int) or page_idx < 0 or page_idx in seen:
                    raise ValueError(f"Invalid or duplicate physical page index: {page_idx}")
                seen.add(page_idx)
                text, blocks = "", []
                for index, block in enumerate(page.get("blocks", [])):
                    content = block.get("content", "")
                    if not isinstance(content, str):
                        raise ValueError(f"Unsupported block content on page {page_idx + 1}: {type(content)}")
                    # Keep captions/footnotes in the evidence stream, too.
                    parts = [content]
                    for field in ("captions", "footnotes"):
                        for item in block.get(field, []) or []:
                            if isinstance(item, dict) and isinstance(item.get("content"), str):
                                parts.append(item["content"])
                            elif isinstance(item, str):
                                parts.append(item)
                            else:
                                raise ValueError(f"Unsupported {field} structure on page {page_idx + 1}")
                    content = "\n".join(part for part in parts if part)
                    start = len(text) + (1 if text and content else 0)
                    if content:
                        text += ("\n" if text else "") + content
                    blocks.append({"block_id": f"p{page_idx + 1}-b{index}", "type": block.get("type"),
                                   "bbox": block.get("bbox"), "char_start": start, "char_end": len(text),
                                   "content": content, "image_source": block.get("image_source"),
                                   "captions": block.get("captions", []),
                                   "footnotes": block.get("footnotes", [])})
                result = {"document_id": parsed["document_id"], "page_number": page_idx + 1,
                          "text": text, "blocks": blocks, "status": "ready" if text.strip() else "empty_page",
                          "offset_unit": "unicode_codepoint", "bbox_coordinate_system": "mineru_normalized"}
                rows.append({**row, output_key: result})
        if not rows:
            raise ValueError("No pages found in MinerU output")
        storage.write(pd.DataFrame(rows))
        return [output_key]


@OPERATOR_REGISTRY.register()
class PaperEvidenceChunker(OperatorABC):
    def __init__(self, tokenizer_path: str, chunk_size: int = 512, chunk_overlap: int = 64):
        super().__init__()
        if chunk_size < 8 or not 0 <= chunk_overlap < chunk_size:
            raise ValueError("Require chunk_size >= 8 and 0 <= chunk_overlap < chunk_size")
        from transformers import AutoTokenizer
        path = Path(tokenizer_path).expanduser().resolve(strict=True)
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, use_fast=True)
        if not self.tokenizer.is_fast:
            raise ValueError("A fast tokenizer with character offsets is required")
        self.tokenizer_files = {p.name: sha256(p) for p in sorted(path.glob("*")) if p.is_file()}
        self.chunk_size, self.chunk_overlap = chunk_size, chunk_overlap

    @staticmethod
    def get_desc(lang: str = "zh"):
        return ("按本地 tokenizer 逐页分块，原文不改写；输出 raw_chunk 和 chunk_metadata，保存文档哈希、页码、字符区间、块坐标和 tokenizer 指纹。空页保留为不可生成 QA 的记录。"
                if lang == "zh" else "Tokenize locally, preserving exact page substrings, document/page IDs, character offsets, block boxes and tokenizer fingerprints. Flag empty evidence.")

    def _encode(self, text):
        return self.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)

    def chunks(self, text):
        if not text.strip():
            yield 0, len(text), 0
            return
        start = 0
        while start < len(text):
            encoded = self._encode(text[start:])
            offsets = encoded["offset_mapping"]
            end = len(text) if len(offsets) <= self.chunk_size else start + offsets[self.chunk_size - 1][1]
            # Byte-level tokenizers can split one Unicode character into several
            # tokens. Retokenize the exact substring so the stated budget is true.
            while end > start and len(self._encode(text[start:end])["input_ids"]) > self.chunk_size:
                end -= 1
            if end <= start:
                raise ValueError("Cannot fit the next character into the token budget")
            chunk = self._encode(text[start:end])
            yield start, end, len(chunk["input_ids"])
            if end == len(text):
                break
            if self.chunk_overlap:
                offset_index = max(0, len(chunk["offset_mapping"]) - self.chunk_overlap)
                candidate = start + chunk["offset_mapping"][offset_index][0]
                start = candidate if candidate > start else end
            else:
                start = end

    def run(self, storage: DataFlowStorage, input_key: str = "source_page", output_key: str = "raw_chunk", output_meta_key: str = "chunk_metadata"):
        frame = read_input(storage, input_key, output_key, output_meta_key)
        rows = []
        for row in frame.to_dict("records"):
            page = row[input_key]
            for index, (start, end, token_count) in enumerate(self.chunks(page["text"])):
                chunk = page["text"][start:end]
                identity = f"{page['document_id']}:{page['page_number']}:{start}:{end}:{chunk}"
                meta = {"chunk_id": hashlib.sha256(identity.encode()).hexdigest(),
                        "document_id": page["document_id"], "page_number": page["page_number"],
                        "chunk_index": index, "char_start": start, "char_end": end,
                        "offset_unit": "unicode_codepoint", "token_count": token_count,
                        "chunk_size": self.chunk_size, "chunk_overlap": self.chunk_overlap,
                        "tokenizer_files_sha256": self.tokenizer_files,
                        "eligible_for_qa": bool(chunk.strip()),
                        "blocks": [b for b in page["blocks"] if b["char_end"] > start and b["char_start"] < end]}
                rows.append({**row, output_key: chunk, output_meta_key: meta})
        storage.write(pd.DataFrame(rows))
        return [output_key, output_meta_key]
