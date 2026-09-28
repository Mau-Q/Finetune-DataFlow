"""Vendored exact source segments; see vendor_manifest.json."""
from __future__ import annotations
import hashlib, json, re, unicodedata
from functools import lru_cache
from pathlib import Path


SYSTEM_PROMPT = (
    "你是一名专业论文问答助手。请严格依据给定论文证据回答问题，"
    "不得添加证据中不存在的信息。"
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_user(instruction: str, evidence: str) -> str:
    if not instruction.strip():
        raise ValueError("INSTRUCTION_EMPTY")
    if evidence.strip():
        return f"问题：\n{instruction}\n\n论文证据：\n{evidence}"
    return f"问题：\n{instruction}"


def render_qwen36_parts(instruction: str, evidence: str, assistant: str) -> tuple[str, str]:
    user = render_user(instruction, evidence)
    prompt = (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    response = f"{assistant}<|im_end|>\n"
    return prompt, response


class Qwen2BpeTokenizer:
    """Dependency-free Qwen2 tokenizer for exact offline length gates."""

    SPECIAL_TOKENS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>")

    def __init__(self, tokenizer_dir: Path):
        vocab_path = tokenizer_dir / "vocab.json"
        merges_path = tokenizer_dir / "merges.txt"
        if not vocab_path.is_file() or not merges_path.is_file():
            raise FileNotFoundError("Qwen3.6 tokenizer requires vocab.json and merges.txt")
        self.vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
        merge_lines = [
            line
            for line in merges_path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        self.ranks = {tuple(line.split(" ", 1)): index for index, line in enumerate(merge_lines)}
        self.byte_encoder = self._bytes_to_unicode()
        self.special_re = re.compile(
            "(" + "|".join(re.escape(token) for token in self.SPECIAL_TOKENS) + ")"
        )

    def count(self, text: str) -> int:
        total = 0
        for part in self.special_re.split(text):
            if not part:
                continue
            if part in self.SPECIAL_TOKENS:
                total += 1
            else:
                total += sum(len(self._bpe(piece)) for piece in self._pretokenize(part))
        return total

    @lru_cache(maxsize=100_000)
    def _bpe(self, piece: str) -> tuple[str, ...]:
        word = tuple(self.byte_encoder[byte] for byte in piece.encode("utf-8"))
        if len(word) < 2:
            return word
        while True:
            candidates = (
                (self.ranks[pair], index, pair)
                for index, pair in enumerate(zip(word, word[1:]))
                if pair in self.ranks
            )
            best = min(candidates, default=None)
            if best is None:
                return word
            _, _, pair = best
            merged: list[str] = []
            index = 0
            while index < len(word):
                if index + 1 < len(word) and (word[index], word[index + 1]) == pair:
                    merged.append(word[index] + word[index + 1])
                    index += 2
                else:
                    merged.append(word[index])
                    index += 1
            word = tuple(merged)

    @staticmethod
    def _bytes_to_unicode() -> dict[int, str]:
        values = list(range(ord("!"), ord("~") + 1))
        values += list(range(ord("¡"), ord("¬") + 1))
        values += list(range(ord("®"), ord("ÿ") + 1))
        chars = list(values)
        extra = 0
        for byte in range(256):
            if byte not in values:
                values.append(byte)
                chars.append(256 + extra)
                extra += 1
        return dict(zip(values, map(chr, chars)))

    @staticmethod
    def _pretokenize(text: str) -> list[str]:
        pieces: list[str] = []
        index = 0
        contractions = ("'s", "'t", "'re", "'ve", "'m", "'ll", "'d")
        while index < len(text):
            lower = text[index : index + 3].lower()
            contraction = next(
                (value for value in contractions if lower.startswith(value)), None
            )
            if contraction is not None:
                pieces.append(text[index : index + len(contraction)])
                index += len(contraction)
                continue

            start = index
            if (
                index + 1 < len(text)
                and text[index] not in "\r\n"
                and not _is_letter_or_number(text[index])
                and _is_letter_or_mark(text[index + 1])
            ):
                index += 1
            if index < len(text) and _is_letter_or_mark(text[index]):
                index += 1
                while index < len(text) and _is_letter_or_mark(text[index]):
                    index += 1
                pieces.append(text[start:index])
                continue
            index = start

            if _is_number(text[index]):
                pieces.append(text[index])
                index += 1
                continue

            if (
                text[index] == " "
                and index + 1 < len(text)
                and _is_symbol_run_char(text[index + 1])
            ):
                index += 1
            if _is_symbol_run_char(text[index]):
                index += 1
                while index < len(text) and _is_symbol_run_char(text[index]):
                    index += 1
                while index < len(text) and text[index] in "\r\n":
                    index += 1
                pieces.append(text[start:index])
                continue
            index = start

            if text[index].isspace():
                end = index
                while end < len(text) and text[end].isspace():
                    end += 1
                newline = next(
                    (pos for pos in range(index, end) if text[pos] in "\r\n"), None
                )
                if newline is not None:
                    after = newline
                    while after < len(text) and text[after] in "\r\n":
                        after += 1
                    pieces.append(text[index:after])
                    index = after
                    continue
                if end < len(text) and end - index > 1:
                    pieces.append(text[index : end - 1])
                    index = end - 1
                else:
                    pieces.append(text[index:end])
                    index = end
                continue

            pieces.append(text[index])
            index += 1
        return pieces


def _category(value: str) -> str:
    return unicodedata.category(value)


def _is_letter_or_number(value: str) -> bool:
    return _category(value)[0] in {"L", "N"}


def _is_letter_or_mark(value: str) -> bool:
    return _category(value)[0] in {"L", "M"}


def _is_number(value: str) -> bool:
    return _category(value)[0] == "N"


def _is_symbol_run_char(value: str) -> bool:
    return not value.isspace() and _category(value)[0] not in {"L", "M", "N"}
