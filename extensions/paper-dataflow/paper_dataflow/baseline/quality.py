"""Vendored exact source segments; see vendor_manifest.json."""
from __future__ import annotations
import json, re
from datetime import UTC, datetime, timezone
from typing import Any
from .token_contract import canonical_json, render_qwen36_parts, sha256_text
from .mixed_count import word_compatible_mixed_count


GENERATOR_PROMPT_VERSION = "paper_sft_answer_only_zh_v3"


VERIFIER_PROMPT_VERSION = "paper_sft_claim_verifier_zh_v3_2_5"


EXPECTED_VERIFIER_MODEL = "deepseek-v4-pro"


MAX_ACCEPTED_PER_PAPER = 3


MAX_MIXED_COUNT = 400


MAX_TOKEN_COUNT = 4096


TAG_RE = re.compile(r"</?(?:think|answer)>|```", re.IGNORECASE)


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


ASCII_TERM_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*)(?![A-Za-z0-9])")


BILLION_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*billion\b", re.IGNORECASE)


YI_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*亿")


SEMANTIC_AUDIT_NAMES = (
    "scope_component_attribution",
    "number_unit_binding",
    "entity_binding",
    "sampling_protocol",
    "obligation_completeness",
    "unsupported_expansion",
    "truncated_evidence_support",
    "translation_fidelity",
    "direction_polarity",
)


SEMANTIC_AUDIT_STATUSES = {"PASS", "FAIL", "UNCERTAIN", "NOT_APPLICABLE"}


ALWAYS_APPLICABLE_SEMANTIC_AUDITS = {
    "obligation_completeness",
    "unsupported_expansion",
    "translation_fidelity",
}


GENERATOR_SYSTEM_PROMPT = """你只依据给定英文论文 Evidence 生成一条高质量中文 SFT 问答。

要求：
1. question 必须自包含、单义、具有专业信息价值，并能完全由 Evidence 回答。
2. answer 必须直接回答全部要求；每个原子事实、数字、单位、实体、方向和范围都必须受 Evidence 直接支持。
3. 不得加入常识补充、因果强化、组件误归因、价值评价或 Evidence 外推断。
4. Evidence 内部矛盾、指代不清、问题前提不可靠或无法完整回答时返回 SKIP。
5. question 和 answer 使用自然简体中文；模型名、标准缩写、代码标识符和必要技术名词可保留英文。
6. support_quotes 为 Evidence 中 1-3 条逐字短引文，共同覆盖 answer 的关键事实。
7. 训练输出严格 answer-only。不要生成 reasoning、think、分析过程或审核说明。
8. 完整 instruction + input + answer 不超过 400 个中英文混合计数单位和 4096 个 Qwen token。

严格返回 JSON 对象，不要 Markdown：
GENERATED:
{"status":"GENERATED","question":"...","answer":"...","qa_type":"...","support_quotes":["..."]}
SKIP:
{"status":"SKIP","reason":"..."}"""


VERIFIER_SYSTEM_PROMPT = """你是独立的论文 SFT claim-level Verifier。只能依据给定 Evidence，不得使用常识补全。

执行局部分析，不做宽泛的“整体看起来合理”判断：
1. 先只看 Question + Evidence，独立列出回答问题所必需的全部原子 required_evidence_points；“如何具体应用/哪些主要问题/有何不同/分别是什么”等问法必须把 Evidence 中每个并列必要点分开列出。必须显式解析 first/second/furthermore/both、also/unlike/different，以及 these/it 等指代：并列的问题、步骤、差异、采样对象/评估对象和代词的精确先行项分别成为 required point。若问题询问某种运算“如何具体应用”，既要列出运算定义中的核心步骤，也要列出其分组/适用范围，不能只列范围。完成该清单后再检查 Answer。每个 COVERED point 必须引用一个或多个 answer claim id，且这些 claims 必须全部 ENTAILED；未覆盖 point 必须为 MISSING，不能通过写成一个宽泛 obligation 隐藏遗漏。
2. 把 question 拆成全部原子 obligations；每个 ANSWERED obligation 必须引用一个或多个 answer claim id，且这些 claims 必须全部 ENTAILED。
3. 把 answer 拆成全部原子 claims。answer_quote 必须是 Answer 中的逐字片段，不得改写或合并隐藏限定词。
4. 对每个 claim 分别核对 subject、predicate、object、quantity_unit、direction、condition_scope、comparison_baseline、causal_relation。只要 Answer 声明了某个决定性维度，而 Evidence 没有覆盖，该维度就是 MISSING，claim 必须为 UNSUPPORTED；Evidence 明确相反则为 CONTRADICTED。
5. 词语重合、常识上合理、机制上可能、同一段出现相关概念，都不等于支持。必须逐字区分相近实体和组件名（如 Fusion4 与 Fusion4CA）、类内与类间关系、数值的单位与换算、主体和数量的绑定、比较/优化方向、训练样本的重复抽取与 test split 上的评估、组件效果与整体效果。Evidence 的“overlap between class features”不能判成 Answer 的“类内特征重叠”；“conduct N samples and average across the test split”不能改写为“对测试集采样 N 次”；正负权重的优化方向必须结合更新式的加减号判断，不能只复述权重符号。
6. 每个支持判断必须给 Evidence 中最短、连续、原样复制的逐字短引文。返回时不要修补断词、连字符或实体拼写，不要合并跨句片段，不要压缩空白，也不要用省略号；需要多个片段时放入多个 evidence_quotes 元素。确定性校验只会有限容忍换行、连续空白、Unicode 引号或破折号的表示差异，以及唯一匹配的 ASCII 技术词内部连字符差异；无法给出原文时不得判 COVERED/ANSWERED/ENTAILED。
7. 不完整 required point/obligation 是 MISSING；问题询问“哪些/如何/差异/主要问题”时，必须从 Evidence 枚举完整必要项，不能只回答其中一个受支持子项。
8. Evidence 若在句中、列表项或关系表达中截断，只支持截断前完整表达的事实；不得依据半句补出对象。缩写全称、术语翻译、隐私/效果评价和因果解释也必须由当前 Evidence 明示。
9. 对 semantic_audits 的九个固定维度逐项独立尝试证伪 Answer，不能从 answer_claims 的既有 status 直接复制结论。checked_claim_ids 只列该维度实际核对的 claims；每个 PASS 至少列一个，九维合计必须覆盖全部 answer claim ids。为避免重复整段引文：PASS 时 answer_quotes/evidence_quotes 都为空；FAIL/UNCERTAIN 时 checked_claim_ids 只列受影响 claims，且必须给 Answer 与 Evidence 的最短逐字片段并在 reason 中写出不一致；NOT_APPLICABLE 时 ids 和 quotes 都为空。唯一例外是 obligation_completeness=FAIL 且同一结果已有 required point 或 obligation=MISSING：因为遗漏本身没有受影响的现存 Answer claim 或 Answer 片段，可将 checked_claim_ids 与双侧 quotes 都留空，但该结构化 MISSING 必须使结果直接 REJECT；其他 FAIL、所有 UNCERTAIN 及没有结构化 MISSING 的 completeness FAIL 均不得使用此例外。obligation_completeness、unsupported_expansion、translation_fidelity 永远适用。FAIL 表示明确错误，UNCERTAIN 只用于能够指出具体 Answer 片段但当前 Evidence 真正不足以判定的情形，并必须在 uncertainty_reasons 写明缺口；不能用来回避 FAIL。PASS/NOT_APPLICABLE 的 reason 使用空字符串；FAIL/UNCERTAIN 的 reason 只写一句短句，不得复述整段 Answer/Evidence。
10. 为避免长答案触发截断，只输出紧凑单行 JSON；required point、obligation 和 claim 的 text 只写最短区分标签，不复述引文。

严格返回以下 JSON，不要 Markdown，也不要输出最终 PASS/REJECT：
{
  "required_evidence_point_extraction":"COMPLETE|INCOMPLETE|UNCERTAIN",
  "required_evidence_points":[{"id":"r1","text":"...","status":"COVERED|MISSING|AMBIGUOUS","covered_by_claim_ids":["c1"],"evidence_quotes":["..."]}],
  "question_obligation_extraction":"COMPLETE|INCOMPLETE|UNCERTAIN",
  "question_obligations":[{"id":"o1","text":"...","status":"ANSWERED|MISSING|AMBIGUOUS","satisfied_by_claim_ids":["c1"],"evidence_quotes":["..."]}],
  "answer_claim_extraction":"COMPLETE|INCOMPLETE|UNCERTAIN",
  "answer_claims":[{
    "id":"c1",
    "text":"...",
    "answer_quote":"Answer 中的逐字片段",
    "status":"ENTAILED|UNSUPPORTED|CONTRADICTED|AMBIGUOUS",
    "support_dimensions":{
      "subject":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN",
      "predicate":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN",
      "object":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN",
      "quantity_unit":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN",
      "direction":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN",
      "condition_scope":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN",
      "comparison_baseline":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN",
      "causal_relation":"MATCH|MISSING|CONTRADICTED|NOT_APPLICABLE|UNCERTAIN"
    },
    "evidence_quotes":["..."]
  }],
  "global_checks":{
    "question_answerable":"PASS|FAIL|UNCERTAIN",
    "number_unit":"PASS|FAIL|UNCERTAIN",
    "entity_binding":"PASS|FAIL|UNCERTAIN",
    "direction_scope":"PASS|FAIL|UNCERTAIN",
    "answer_complete":"PASS|FAIL|UNCERTAIN"
  },
  "semantic_audits":{
    "scope_component_attribution":{"status":"PASS|FAIL|UNCERTAIN|NOT_APPLICABLE","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "number_unit_binding":{"status":"PASS|FAIL|UNCERTAIN|NOT_APPLICABLE","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "entity_binding":{"status":"PASS|FAIL|UNCERTAIN|NOT_APPLICABLE","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "sampling_protocol":{"status":"PASS|FAIL|UNCERTAIN|NOT_APPLICABLE","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "obligation_completeness":{"status":"PASS|FAIL|UNCERTAIN","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "unsupported_expansion":{"status":"PASS|FAIL|UNCERTAIN","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "truncated_evidence_support":{"status":"PASS|FAIL|UNCERTAIN|NOT_APPLICABLE","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "translation_fidelity":{"status":"PASS|FAIL|UNCERTAIN","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""},
    "direction_polarity":{"status":"PASS|FAIL|UNCERTAIN|NOT_APPLICABLE","checked_claim_ids":["c1"],"answer_quotes":[],"evidence_quotes":[],"reason":""}
  },
  "uncertainty_reasons":["..."]
}"""


class GeneratorProtocolError(ValueError):
    pass


class GeneratorQualityReject(ValueError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat()


def strip_json_fence(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return value


def normalized(value: str) -> str:
    return " ".join(value.split())


CANONICAL_QUOTE_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


def _canonical_quote_view(
    value: str, *, drop_internal_ascii_hyphens: bool = False
) -> tuple[str, list[tuple[int, int]]]:
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    in_whitespace = False
    for index, source_character in enumerate(value):
        translated = source_character.translate(CANONICAL_QUOTE_TRANSLATION)
        for character in translated:
            if (
                drop_internal_ascii_hyphens
                and character == "-"
                and 0 < index < len(value) - 1
                and value[index - 1].isascii()
                and value[index - 1].isalnum()
                and value[index + 1].isascii()
                and value[index + 1].isalnum()
            ):
                continue
            if character.isspace():
                if not in_whitespace:
                    characters.append(" ")
                    spans.append((index, index + 1))
                else:
                    spans[-1] = (spans[-1][0], index + 1)
                in_whitespace = True
            else:
                characters.append(character)
                spans.append((index, index + 1))
                in_whitespace = False
    return "".join(characters), spans


def canonical_evidence_quote(quote: str, evidence: str) -> tuple[str | None, str]:
    direct_start = evidence.find(quote)
    if direct_start >= 0:
        return evidence[direct_start : direct_start + len(quote)], "EXACT"
    canonical_quote, _ = _canonical_quote_view(quote.strip())
    canonical_evidence, spans = _canonical_quote_view(evidence)
    if not canonical_quote:
        return None, "EMPTY"
    canonical_start = canonical_evidence.find(canonical_quote)
    if canonical_start < 0:
        hyphen_quote, _ = _canonical_quote_view(
            quote.strip(), drop_internal_ascii_hyphens=True
        )
        hyphen_evidence, hyphen_spans = _canonical_quote_view(
            evidence, drop_internal_ascii_hyphens=True
        )
        if (
            hyphen_quote
            and hyphen_quote != canonical_quote
            and hyphen_evidence.count(hyphen_quote) == 1
        ):
            hyphen_start = hyphen_evidence.find(hyphen_quote)
            hyphen_end = hyphen_start + len(hyphen_quote) - 1
            source_start = hyphen_spans[hyphen_start][0]
            source_end = hyphen_spans[hyphen_end][1]
            return evidence[source_start:source_end], "TECHNICAL_HYPHEN_CANONICAL"
        return None, "NOT_FOUND"
    canonical_end = canonical_start + len(canonical_quote) - 1
    source_start = spans[canonical_start][0]
    source_end = spans[canonical_end][1]
    return evidence[source_start:source_end], "CANONICAL"


def exact_quote_in_evidence(quote: str, evidence: str) -> bool:
    return normalized(quote) in normalized(evidence)


def generator_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": canonical_json(
                {
                    "prompt_version": GENERATOR_PROMPT_VERSION,
                    "candidate_id": row["candidate_id"],
                    "paper_id": row["paper_id"],
                    "domain": row["domain"],
                    "paper_evidence": row["evidence"],
                    "training_schema": ["instruction", "input", "output"],
                    "assistant_output_mode": "ANSWER_ONLY",
                    "full_record_mixed_count_max": MAX_MIXED_COUNT,
                    "qwen_token_count_max": MAX_TOKEN_COUNT,
                }
            ),
        },
    ]


def verifier_messages(
    *, evidence: str, question: str, answer: str
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": canonical_json(
                {
                    "prompt_version": VERIFIER_PROMPT_VERSION,
                    "paper_evidence": evidence,
                    "question": question,
                    "answer": answer,
                }
            ),
        },
    ]


def validate_generated(
    raw: str, row: dict[str, Any], tokenizer: Any
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    try:
        value = json.loads(strip_json_fence(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise GeneratorProtocolError("GENERATOR_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise GeneratorProtocolError("GENERATOR_NOT_OBJECT")
    if value.get("status") == "SKIP":
        if (
            set(value) != {"status", "reason"}
            or not isinstance(value["reason"], str)
            or not value["reason"].strip()
        ):
            raise GeneratorProtocolError("GENERATOR_SKIP_INVALID")
        return None, {"skip_reason": value["reason"].strip()}
    expected = {"status", "question", "answer", "qa_type", "support_quotes"}
    if set(value) != expected or value.get("status") != "GENERATED":
        raise GeneratorProtocolError("GENERATOR_FIELDS_INVALID")
    for field in ("question", "answer", "qa_type"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise GeneratorProtocolError(f"{field.upper()}_INVALID")
        value[field] = value[field].strip()
        if TAG_RE.search(value[field]):
            raise GeneratorQualityReject(f"{field.upper()}_CONTAINS_FORBIDDEN_TAG")
    if len(CJK_RE.findall(value["question"])) < 8:
        raise GeneratorQualityReject("QUESTION_NOT_NATURAL_CHINESE")
    if len(CJK_RE.findall(value["answer"])) < 6:
        raise GeneratorQualityReject("ANSWER_NOT_NATURAL_CHINESE")
    quotes = value["support_quotes"]
    if (
        not isinstance(quotes, list)
        or not 1 <= len(quotes) <= 3
        or any(not isinstance(quote, str) or not quote.strip() for quote in quotes)
    ):
        raise GeneratorProtocolError("SUPPORT_QUOTES_SCHEMA_INVALID")
    if any(not exact_quote_in_evidence(quote, row["evidence"]) for quote in quotes):
        raise GeneratorQualityReject("SUPPORT_QUOTES_NOT_IN_EVIDENCE")
    value["support_quotes"] = [quote.strip() for quote in quotes]
    mixed_count = word_compatible_mixed_count(
        value["question"], row["evidence"], value["answer"]
    )
    if mixed_count > MAX_MIXED_COUNT:
        raise GeneratorQualityReject("FULL_RECORD_MIXED_COUNT_EXCEEDED")
    prompt, response = render_qwen36_parts(
        value["question"], row["evidence"], value["answer"]
    )
    token_count = tokenizer.count(prompt) + tokenizer.count(response)
    if token_count > MAX_TOKEN_COUNT:
        raise GeneratorQualityReject("QWEN_TOKEN_LIMIT_EXCEEDED")
    value["output"] = value["answer"]
    return value, {
        "full_record_mixed_count": mixed_count,
        "qwen36_token_count": token_count,
        "answer_chars": len(value["answer"]),
    }


def _validate_evidence_quotes(
    quotes: Any, evidence: str, location: str
) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(quotes, list) or any(
        not isinstance(quote, str) or not quote.strip() for quote in quotes
    ):
        raise ValueError(f"{location}_EVIDENCE_QUOTES_INVALID")
    canonical: list[str] = []
    issues: list[dict[str, Any]] = []
    for quote_index, quote in enumerate(quotes, 1):
        source_quote, match_mode = canonical_evidence_quote(quote.strip(), evidence)
        if source_quote is None:
            issues.append(
                {
                    "location": location,
                    "quote_index": quote_index,
                    "reason": "EVIDENCE_QUOTE_NOT_FOUND",
                    "model_quote": quote.strip(),
                }
            )
        else:
            canonical.append(source_quote)
            if match_mode != "EXACT":
                issues.append(
                    {
                        "location": location,
                        "quote_index": quote_index,
                        "reason": (
                            "CANONICAL_TECHNICAL_HYPHEN_MATCH_USED"
                            if match_mode == "TECHNICAL_HYPHEN_CANONICAL"
                            else "CANONICAL_MATCH_USED"
                        ),
                        "model_quote": quote.strip(),
                        "canonical_quote": source_quote,
                    }
                )
    return canonical, issues


SUPPORT_DIMENSIONS = {
    "subject",
    "predicate",
    "object",
    "quantity_unit",
    "direction",
    "condition_scope",
    "comparison_baseline",
    "causal_relation",
}


SUPPORT_DIMENSION_STATUSES = {
    "MATCH",
    "MISSING",
    "CONTRADICTED",
    "NOT_APPLICABLE",
    "UNCERTAIN",
}


def _high_precision_ascii_terms(value: str) -> set[str]:
    terms: set[str] = set()
    for match in ASCII_TERM_RE.finditer(value):
        term = match.group(1)
        uppercase_count = sum(character.isupper() for character in term)
        if len(term) >= 3 and (
            any(character.isdigit() for character in term)
            or uppercase_count >= 2
            or "-" in term
            or "_" in term
        ):
            terms.add(term)
    return terms


def deterministic_semantic_checks(
    evidence: str, answer: str | None, question: str | None = None
) -> list[str]:
    if answer is None:
        return []
    evidence_terms = {term.casefold() for term in ASCII_TERM_RE.findall(evidence)}
    unbound_terms = sorted(
        term
        for term in _high_precision_ascii_terms(answer)
        if term.casefold() not in evidence_terms
    )
    reasons = [f"UNBOUND_ASCII_TERM:{term}" for term in unbound_terms]
    billion_values = [float(value) for value in BILLION_RE.findall(evidence)]
    yi_values = [float(value) for value in YI_RE.findall(answer)]
    if billion_values and yi_values:
        expected_yi = {round(value * 10, 12) for value in billion_values}
        for value in yi_values:
            if round(value, 12) not in expected_yi:
                reasons.append(f"BILLION_TO_YI_MISMATCH:{value:g}")
    evidence_folded = normalized(evidence).casefold()
    answer_normalized = normalized(answer)
    if "deductive-abductive" in evidence_folded and re.search(
        r"混合?演绎\s*[-—－]?\s*归纳(?:学习)?循环", answer_normalized
    ):
        reasons.append("ABDUCTIVE_AS_INDUCTIVE_MISTRANSLATION")
    if (
        "maximum turn limit" in evidence_folded
        and "trajectory" in evidence_folded
        and "最大转弯" in answer_normalized
    ):
        reasons.append("TRAJECTORY_TURN_AS_PHYSICAL_TURN_MISTRANSLATION")
    agent_dataset_match = re.search(
        r"\b(\d+)-agent\s+[a-z-]*hackathon\s+dataset\b", evidence_folded
    )
    if agent_dataset_match and re.search(
        rf"{re.escape(agent_dataset_match.group(1))}个[^。；，]{{0,24}}数据集(?:的|中)[^。；，]{{0,16}}智能体",
        answer_normalized,
    ):
        reasons.append("NUMBER_ENTITY_BINDING_AGENT_DATASET_MISMATCH")
    question_normalized = normalized(question or "")
    if (
        "xadv←xadv−" in evidence.replace(" ", "")
        and "negative" in evidence_folded
        and "positive" in evidence_folded
        and any(
            (
                "负" in clause
                and "收敛" in clause
                and not re.search(r"负[^。；]{0,24}发散", clause)
            )
            or (
                "正" in clause
                and "发散" in clause
                and not re.search(r"正[^。；]{0,24}收敛", clause)
            )
            for clause in re.split(r"[。；;]", answer_normalized)
        )
    ):
        reasons.append("SIGNED_GRADIENT_DIRECTION_REVERSAL")
    if (
        "we don't include it in the efficiency comparison" in evidence_folded
        and "comparison results" in evidence_folded
        and "ci-tsmixer" in evidence_folded
        and re.search(r"CI-TSMixer[^。；]{0,20}未被纳入", answer_normalized)
    ):
        reasons.append("EXCLUDED_ENTITY_PRESENT_IN_COMPARISON")
    if re.search(r"uniquely\s+feature\s*\d+(?:see|https?://)", evidence_folded) and re.search(
        r"优先保留[^。；]{0,24}独特角色", answer_normalized
    ):
        reasons.append("TRUNCATED_EVIDENCE_COMPLETION")
    if (
        "this dual approach" in evidence_folded
        and "openclaw" in evidence_folded
        and "hermes agent" in evidence_folded
        and re.search(
            r"通过[^。；，,]{0,30}[（(]OpenClaw[）)][^。；，,]{0,24}(?:提升|改善)[^。；，,]{0,16}确定性"
            r"[^。；]{0,30}并通过[^。；，,]{0,30}[（(]Hermes Agent[）)][^。；]{0,32}(?:赋予|提供)[^。；]{0,24}自由",
            answer_normalized,
        )
    ):
        reasons.append("JOINT_EFFECT_SPLIT_COMPONENT_ATTRIBUTION")
    if (
        "red and orange mark the lowest and second-lowest" in evidence_folded
        and "where these are omitted" in evidence_folded
        and re.search(
            r"(?:(?:这些|所有|全部)颜色(?:标记)?[^。；]{0,12}(?:省略|未标)|"
            r"(?:省略|未标)[^。；]{0,12}(?:这些|所有|全部)颜色(?:标记)?)",
            answer_normalized,
        )
    ):
        reasons.append("OMITTED_COLOR_SCOPE_EXPANSION")
    if (
        "training split" in evidence_folded
        and "test split" in evidence_folded
        and re.search(r"\bconduct\s+\d+\s+samples\b", evidence_folded)
        and re.search(r"(?:对|在)测试集(?:上)?(?:进行)?\s*\d+次(?:随机)?采样", answer_normalized)
    ):
        reasons.append("TRAIN_SAMPLE_AS_TEST_SAMPLE_BINDING")
    if (
        "归一化" in question_normalized
        and "centering rewards with the within-group empirical mean" in evidence_folded
        and "scaling by the within-group empirical standard deviation" in evidence_folded
        and not (
            (
                re.search(r"(?:均值|平均值)[^。；]{0,24}(?:中心化|减去|居中)", answer_normalized)
                or re.search(r"(?:中心化|减去|居中)[^。；]{0,24}(?:均值|平均值)", answer_normalized)
            )
            and "标准差" in answer_normalized
        )
    ):
        reasons.append("NORMALIZATION_CORE_OPERATION_OMITTED")
    if (
        "主要数值问题" in question_normalized
        and "as a second problem" in evidence_folded
        and "tackle both problems" in evidence_folded
        and not (
            "近似误差" in answer_normalized
            and ("步长" in answer_normalized or "无穷小" in answer_normalized)
        )
    ):
        reasons.append("ENUMERATED_NUMERICAL_PROBLEM_OMITTED")
    if (
        "多任务学习" in question_normalized
        and "有何不同" in question_normalized
        and "decisions must be made in a sequential manner" in evidence_folded
        and "different training samples" in evidence_folded
        and not re.search(r"(?:顺序|逐步|先[^。；]{0,20}(?:再|然后)|依次)", answer_normalized)
    ):
        reasons.append("SEQUENTIAL_MULTITASK_CONSTRAINT_OMITTED")
    if (
        "back-channels" in evidence_folded
        and "short utterances" in evidence_folded
        and ("speaker" in evidence_folded or "dialogue" in evidence_folded)
        and "反馈信道" in answer_normalized
    ):
        reasons.append("BACK_CHANNEL_AS_FEEDBACK_CHANNEL_MISTRANSLATION")
    if (
        re.search(
            r"(?:\boverlap\s+between\s+(?:class(?:es)?\s+features|classes)\b|"
            r"\binter[- ]class(?: feature)? overlap\b)",
            evidence_folded,
        )
        and not re.search(
            r"\b(?:intra|within)[- ]class(?: feature)? overlap\b",
            evidence_folded,
        )
        and re.search(r"类内[^。；，,]{0,12}特征[^。；，,]{0,12}重叠|类内特征重叠", answer_normalized)
    ):
        reasons.append("INTRA_CLASS_AS_INTER_CLASS_RELATION")
    return reasons


def validate_verifier(
    raw: str,
    evidence: str,
    answer: str | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    value = json.loads(strip_json_fence(raw))
    expected = {
        "required_evidence_point_extraction",
        "required_evidence_points",
        "question_obligation_extraction",
        "question_obligations",
        "answer_claim_extraction",
        "answer_claims",
        "global_checks",
        "semantic_audits",
        "uncertainty_reasons",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("VERIFIER_FIELDS_INVALID")
    for field in (
        "required_evidence_point_extraction",
        "question_obligation_extraction",
        "answer_claim_extraction",
    ):
        if value[field] not in {"COMPLETE", "INCOMPLETE", "UNCERTAIN"}:
            raise ValueError(f"{field.upper()}_INVALID")
    required_points = value["required_evidence_points"]
    obligations = value["question_obligations"]
    claims = value["answer_claims"]
    if not isinstance(required_points, list) or not required_points:
        raise ValueError("VERIFIER_REQUIRED_EVIDENCE_POINTS_EMPTY")
    if not isinstance(obligations, list) or not obligations:
        raise ValueError("VERIFIER_OBLIGATIONS_EMPTY")
    if not isinstance(claims, list) or not claims:
        raise ValueError("VERIFIER_CLAIMS_EMPTY")
    obligation_ids: set[str] = set()
    quote_alignment_issues: list[dict[str, Any]] = []
    required_point_ids: set[str] = set()
    for index, item in enumerate(required_points, 1):
        if not isinstance(item, dict) or set(item) != {
            "id",
            "text",
            "status",
            "covered_by_claim_ids",
            "evidence_quotes",
        }:
            raise ValueError("VERIFIER_REQUIRED_EVIDENCE_POINT_FIELDS_INVALID")
        if (
            not isinstance(item["id"], str)
            or not item["id"].strip()
            or item["id"] in required_point_ids
            or not isinstance(item["text"], str)
            or not item["text"].strip()
            or item["status"] not in {"COVERED", "MISSING", "AMBIGUOUS"}
            or not isinstance(item["covered_by_claim_ids"], list)
            or any(
                not isinstance(claim_id, str) or not claim_id.strip()
                for claim_id in item["covered_by_claim_ids"]
            )
        ):
            raise ValueError("VERIFIER_REQUIRED_EVIDENCE_POINT_INVALID")
        required_point_ids.add(item["id"])
        canonical_quotes, quote_issues = _validate_evidence_quotes(
            item["evidence_quotes"], evidence, f"REQUIRED_EVIDENCE_POINT_{index}"
        )
        item["evidence_quotes"] = canonical_quotes
        quote_alignment_issues.extend(quote_issues)
        if item["status"] == "COVERED" and (
            not canonical_quotes
            or any(
                issue["reason"] == "EVIDENCE_QUOTE_NOT_FOUND"
                for issue in quote_issues
            )
        ):
            item["status"] = "AMBIGUOUS"
    for index, item in enumerate(obligations, 1):
        if not isinstance(item, dict) or set(item) != {
            "id",
            "text",
            "status",
            "satisfied_by_claim_ids",
            "evidence_quotes",
        }:
            raise ValueError("VERIFIER_OBLIGATION_FIELDS_INVALID")
        if (
            not isinstance(item["id"], str)
            or not item["id"].strip()
            or item["id"] in obligation_ids
            or not isinstance(item["text"], str)
            or not item["text"].strip()
            or item["status"] not in {"ANSWERED", "MISSING", "AMBIGUOUS"}
            or not isinstance(item["satisfied_by_claim_ids"], list)
            or any(
                not isinstance(claim_id, str) or not claim_id.strip()
                for claim_id in item["satisfied_by_claim_ids"]
            )
        ):
            raise ValueError("VERIFIER_OBLIGATION_INVALID")
        obligation_ids.add(item["id"])
        canonical_quotes, quote_issues = _validate_evidence_quotes(
            item["evidence_quotes"], evidence, f"OBLIGATION_{index}"
        )
        item["evidence_quotes"] = canonical_quotes
        quote_alignment_issues.extend(quote_issues)
        if item["status"] == "ANSWERED" and (
            not canonical_quotes
            or any(issue["reason"] == "EVIDENCE_QUOTE_NOT_FOUND" for issue in quote_issues)
        ):
            item["status"] = "AMBIGUOUS"
    claim_ids: set[str] = set()
    for index, item in enumerate(claims, 1):
        if not isinstance(item, dict) or set(item) != {
            "id",
            "text",
            "answer_quote",
            "status",
            "support_dimensions",
            "evidence_quotes",
        }:
            raise ValueError("VERIFIER_CLAIM_FIELDS_INVALID")
        if (
            not isinstance(item["id"], str)
            or not item["id"].strip()
            or item["id"] in claim_ids
            or not isinstance(item["text"], str)
            or not item["text"].strip()
            or not isinstance(item["answer_quote"], str)
            or not item["answer_quote"].strip()
            or item["status"]
            not in {"ENTAILED", "UNSUPPORTED", "CONTRADICTED", "AMBIGUOUS"}
        ):
            raise ValueError("VERIFIER_CLAIM_INVALID")
        dimensions = item["support_dimensions"]
        if (
            not isinstance(dimensions, dict)
            or set(dimensions) != SUPPORT_DIMENSIONS
            or any(
                status not in SUPPORT_DIMENSION_STATUSES
                for status in dimensions.values()
            )
        ):
            raise ValueError("VERIFIER_CLAIM_SUPPORT_DIMENSIONS_INVALID")
        claim_ids.add(item["id"])
        if answer is not None:
            model_answer_quote = item["answer_quote"].strip()
            canonical_answer_quote, answer_match_mode = canonical_evidence_quote(
                model_answer_quote, answer
            )
            if canonical_answer_quote is None:
                quote_alignment_issues.append(
                    {
                        "location": f"CLAIM_{index}_ANSWER",
                        "quote_index": 1,
                        "reason": "ANSWER_QUOTE_NOT_FOUND",
                        "model_quote": item["answer_quote"].strip(),
                    }
                )
                item["status"] = "AMBIGUOUS"
            else:
                item["answer_quote"] = canonical_answer_quote
                if answer_match_mode == "CANONICAL":
                    quote_alignment_issues.append(
                        {
                            "location": f"CLAIM_{index}_ANSWER",
                            "quote_index": 1,
                            "reason": "CANONICAL_MATCH_USED",
                            "model_quote": model_answer_quote,
                            "canonical_quote": canonical_answer_quote,
                        }
                    )
        canonical_quotes, quote_issues = _validate_evidence_quotes(
            item["evidence_quotes"], evidence, f"CLAIM_{index}"
        )
        item["evidence_quotes"] = canonical_quotes
        quote_alignment_issues.extend(quote_issues)
        if item["status"] == "ENTAILED" and (
            not canonical_quotes
            or any(issue["reason"] == "EVIDENCE_QUOTE_NOT_FOUND" for issue in quote_issues)
        ):
            item["status"] = "AMBIGUOUS"
        dimension_values = set(dimensions.values())
        if "CONTRADICTED" in dimension_values:
            item["status"] = "CONTRADICTED"
        elif "MISSING" in dimension_values:
            item["status"] = "UNSUPPORTED"
        elif "UNCERTAIN" in dimension_values and item["status"] == "ENTAILED":
            item["status"] = "AMBIGUOUS"
    claims_by_id = {item["id"]: item for item in claims}
    for item in required_points:
        covered_ids = item["covered_by_claim_ids"]
        if any(claim_id not in claims_by_id for claim_id in covered_ids):
            item["status"] = "MISSING"
            item["covered_by_claim_ids"] = []
            covered_ids = []
        if item["status"] == "COVERED":
            if not covered_ids or any(
                claims_by_id[claim_id]["status"]
                in {"UNSUPPORTED", "CONTRADICTED"}
                for claim_id in covered_ids
            ):
                item["status"] = "MISSING"
            elif any(
                claims_by_id[claim_id]["status"] == "AMBIGUOUS"
                for claim_id in covered_ids
            ):
                item["status"] = "AMBIGUOUS"
    for item in obligations:
        satisfied_ids = item["satisfied_by_claim_ids"]
        if any(claim_id not in claims_by_id for claim_id in satisfied_ids):
            item["status"] = "MISSING"
            item["satisfied_by_claim_ids"] = []
            satisfied_ids = []
        if item["status"] == "ANSWERED":
            if not satisfied_ids:
                item["status"] = "MISSING"
            elif any(
                claims_by_id[claim_id]["status"]
                in {"UNSUPPORTED", "CONTRADICTED"}
                for claim_id in satisfied_ids
            ):
                item["status"] = "MISSING"
            elif any(
                claims_by_id[claim_id]["status"] == "AMBIGUOUS"
                for claim_id in satisfied_ids
            ):
                item["status"] = "AMBIGUOUS"
    checks = value["global_checks"]
    expected_checks = {
        "question_answerable",
        "number_unit",
        "entity_binding",
        "direction_scope",
        "answer_complete",
    }
    if not isinstance(checks, dict) or set(checks) != expected_checks:
        raise ValueError("VERIFIER_GLOBAL_CHECKS_INVALID")
    if any(check not in {"PASS", "FAIL", "UNCERTAIN"} for check in checks.values()):
        raise ValueError("VERIFIER_GLOBAL_CHECK_VALUE_INVALID")
    audits = value["semantic_audits"]
    if not isinstance(audits, dict) or set(audits) != set(SEMANTIC_AUDIT_NAMES):
        raise ValueError("VERIFIER_SEMANTIC_AUDITS_INVALID")
    uncertainty = value["uncertainty_reasons"]
    if not isinstance(uncertainty, list) or any(
        not isinstance(reason, str) or not reason.strip() for reason in uncertainty
    ):
        raise ValueError("VERIFIER_UNCERTAINTY_REASONS_INVALID")
    value["uncertainty_reasons"] = [reason.strip() for reason in uncertainty]
    model_declared_uncertainty = (
        value["required_evidence_point_extraction"] == "UNCERTAIN"
        or value["question_obligation_extraction"] == "UNCERTAIN"
        or value["answer_claim_extraction"] == "UNCERTAIN"
        or any(check == "UNCERTAIN" for check in checks.values())
        or any(
            isinstance(audit, dict) and audit.get("status") == "UNCERTAIN"
            for audit in audits.values()
        )
    )
    if model_declared_uncertainty and not value["uncertainty_reasons"]:
        raise ValueError("VERIFIER_DECLARED_UNCERTAINTY_REASON_REQUIRED")
    structural_omission_reject = any(
        item["status"] == "MISSING" for item in required_points
    ) or any(item["status"] == "MISSING" for item in obligations)
    audited_claim_ids: set[str] = set()
    for audit_name, audit in audits.items():
        if not isinstance(audit, dict) or set(audit) != {
            "status",
            "checked_claim_ids",
            "answer_quotes",
            "evidence_quotes",
            "reason",
        }:
            raise ValueError(f"VERIFIER_SEMANTIC_AUDIT_FIELDS_INVALID:{audit_name}")
        status = audit["status"]
        declared_status = status
        if status not in SEMANTIC_AUDIT_STATUSES or (
            audit_name in ALWAYS_APPLICABLE_SEMANTIC_AUDITS
            and status == "NOT_APPLICABLE"
        ):
            raise ValueError(f"VERIFIER_SEMANTIC_AUDIT_STATUS_INVALID:{audit_name}")
        if not isinstance(audit["reason"], str) or (
            status in {"FAIL", "UNCERTAIN"} and not audit["reason"].strip()
        ):
            raise ValueError(f"VERIFIER_SEMANTIC_AUDIT_REASON_INVALID:{audit_name}")
        audit["reason"] = audit["reason"].strip()
        if status in {"PASS", "NOT_APPLICABLE"} and audit["reason"]:
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_NON_FINDING_REASON_INVALID:{audit_name}"
            )
        checked_claim_ids = audit["checked_claim_ids"]
        if (
            not isinstance(checked_claim_ids, list)
            or any(
                not isinstance(claim_id, str) or claim_id not in claims_by_id
                for claim_id in checked_claim_ids
            )
            or len(set(checked_claim_ids)) != len(checked_claim_ids)
        ):
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_CLAIM_REFERENCES_INVALID:{audit_name}"
            )
        if status == "PASS" and not checked_claim_ids:
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_PASS_CLAIM_REQUIRED:{audit_name}"
            )
        structural_omission_audit = (
            audit_name == "obligation_completeness"
            and status == "FAIL"
            and structural_omission_reject
        )
        if (
            status in {"FAIL", "UNCERTAIN"}
            and not checked_claim_ids
            and not structural_omission_audit
        ):
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_FINDING_CLAIM_REQUIRED:{audit_name}"
            )
        if status == "NOT_APPLICABLE" and checked_claim_ids:
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_NA_CLAIMS_INVALID:{audit_name}"
            )
        audited_claim_ids.update(checked_claim_ids)
        answer_quotes = audit["answer_quotes"]
        evidence_quotes = audit["evidence_quotes"]
        if not isinstance(answer_quotes, list) or any(
            not isinstance(quote, str) or not quote.strip() for quote in answer_quotes
        ):
            raise ValueError(f"VERIFIER_SEMANTIC_AUDIT_ANSWER_QUOTES_INVALID:{audit_name}")
        if not isinstance(evidence_quotes, list) or any(
            not isinstance(quote, str) or not quote.strip() for quote in evidence_quotes
        ):
            raise ValueError(f"VERIFIER_SEMANTIC_AUDIT_EVIDENCE_QUOTES_INVALID:{audit_name}")
        if declared_status in {"PASS", "NOT_APPLICABLE"} and (
            answer_quotes or evidence_quotes
        ):
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_NON_FINDING_QUOTES_INVALID:{audit_name}"
            )
        quote_less_structural_omission = (
            structural_omission_audit
            and not answer_quotes
            and not evidence_quotes
        )
        if declared_status in {"FAIL", "UNCERTAIN"} and (
            not answer_quotes or not evidence_quotes
        ) and not quote_less_structural_omission:
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_FINDING_QUOTES_REQUIRED:{audit_name}"
            )
        canonical_answer_quotes: list[str] = []
        if answer is not None:
            for quote_index, quote in enumerate(answer_quotes, 1):
                canonical_quote, match_mode = canonical_evidence_quote(quote.strip(), answer)
                if canonical_quote is None:
                    quote_alignment_issues.append(
                        {
                            "location": f"SEMANTIC_AUDIT_{audit_name}_ANSWER",
                            "quote_index": quote_index,
                            "reason": "ANSWER_QUOTE_NOT_FOUND",
                            "model_quote": quote.strip(),
                        }
                    )
                else:
                    canonical_answer_quotes.append(canonical_quote)
                    if match_mode == "CANONICAL":
                        quote_alignment_issues.append(
                            {
                                "location": f"SEMANTIC_AUDIT_{audit_name}_ANSWER",
                                "quote_index": quote_index,
                                "reason": "CANONICAL_MATCH_USED",
                                "model_quote": quote.strip(),
                                "canonical_quote": canonical_quote,
                            }
                        )
        else:
            canonical_answer_quotes = [quote.strip() for quote in answer_quotes]
        if len(canonical_answer_quotes) != len(answer_quotes):
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_ANSWER_QUOTE_ALIGNMENT_INVALID:{audit_name}"
            )
        canonical_evidence_quotes, audit_quote_issues = _validate_evidence_quotes(
            evidence_quotes, evidence, f"SEMANTIC_AUDIT_{audit_name}"
        )
        quote_alignment_issues.extend(audit_quote_issues)
        if len(canonical_evidence_quotes) != len(evidence_quotes):
            raise ValueError(
                f"VERIFIER_SEMANTIC_AUDIT_EVIDENCE_QUOTE_ALIGNMENT_INVALID:{audit_name}"
            )
        audit["answer_quotes"] = canonical_answer_quotes
        audit["evidence_quotes"] = canonical_evidence_quotes
    if audited_claim_ids != set(claim_ids):
        raise ValueError("VERIFIER_SEMANTIC_AUDIT_GLOBAL_CLAIM_COVERAGE_INVALID")
    value["deterministic_semantic_checks"] = deterministic_semantic_checks(
        evidence, answer, question
    )
    value["quote_alignment_issues"] = quote_alignment_issues
    return value


def aggregate_verifier(verifier: dict[str, Any]) -> tuple[str, list[str]]:
    reject: list[str] = []
    review: list[str] = []
    for field in (
        "required_evidence_point_extraction",
        "question_obligation_extraction",
        "answer_claim_extraction",
    ):
        if verifier[field] == "INCOMPLETE":
            reject.append(f"{field.upper()}_INCOMPLETE")
        elif verifier[field] == "UNCERTAIN":
            review.append(f"{field.upper()}_UNCERTAIN")
    for item in verifier["required_evidence_points"]:
        if item["status"] == "MISSING":
            reject.append(f"REQUIRED_EVIDENCE_POINT_MISSING:{item['id']}")
        elif item["status"] == "AMBIGUOUS":
            review.append(f"REQUIRED_EVIDENCE_POINT_AMBIGUOUS:{item['id']}")
    for item in verifier["question_obligations"]:
        if item["status"] == "MISSING":
            reject.append(f"OBLIGATION_MISSING:{item['id']}")
        elif item["status"] == "AMBIGUOUS":
            review.append(f"OBLIGATION_AMBIGUOUS:{item['id']}")
    for item in verifier["answer_claims"]:
        if item["status"] in {"UNSUPPORTED", "CONTRADICTED"}:
            reject.append(f"CLAIM_{item['status']}:{item['id']}")
        elif item["status"] == "AMBIGUOUS":
            review.append(f"CLAIM_AMBIGUOUS:{item['id']}")
    for name, status in verifier["global_checks"].items():
        if status == "FAIL":
            reject.append(f"GLOBAL_{name.upper()}_FAIL")
        elif status == "UNCERTAIN":
            review.append(f"GLOBAL_{name.upper()}_UNCERTAIN")
    for name, audit in verifier["semantic_audits"].items():
        if audit["status"] == "FAIL":
            reject.append(f"SEMANTIC_AUDIT_FAIL:{name}")
        elif audit["status"] == "UNCERTAIN":
            review.append(f"SEMANTIC_AUDIT_UNCERTAIN:{name}")
    reject.extend(verifier.get("deterministic_semantic_checks", []))
    review.extend(f"VERIFIER_UNCERTAINTY:{reason}" for reason in verifier["uncertainty_reasons"])
    if reject:
        return "REJECT", reject + review
    if review:
        return "REVIEW_REQUIRED", review
    return "PASS", []


def finalize_verifier_observation(
    observed: dict[str, Any], *, evidence: str, question: str, answer: str
) -> dict[str, Any]:
    observation = observed.get("verifier_observation")
    if not isinstance(observation, dict):
        raise ValueError("VERIFIER_OBSERVATION_MISSING")
    raw = observation.get("raw_response")
    if not isinstance(raw, str):
        raise ValueError("VERIFIER_RAW_RESPONSE_MISSING")
    actual_model = observation.get("actual_model")
    try:
        semantic = validate_verifier(raw, evidence, answer, question)
        decision, reasons = aggregate_verifier(semantic)
    except (ValueError, json.JSONDecodeError, TypeError) as exc:
        protocol_error = {
            "type": type(exc).__name__,
            "reason": str(exc) or type(exc).__name__,
        }
        if actual_model != EXPECTED_VERIFIER_MODEL:
            return {
                **observed,
                "processing_status": "ERROR",
                "quality_decision": None,
                "stage": "VERIFIER_IDENTITY",
                "reason_codes": ["VERIFIER_ACTUAL_MODEL_MISMATCH"],
                "protocol_error": protocol_error,
                "validated_at": now(),
            }
        deterministic_reasons = deterministic_semantic_checks(
            evidence, answer, question
        )
        if deterministic_reasons:
            return {
                **observed,
                "processing_status": "COMPLETED",
                "quality_decision": "REJECT",
                "stage": "DETERMINISTIC_SEMANTIC_FALLBACK",
                "reason_codes": deterministic_reasons,
                "deterministic_semantic_checks": deterministic_reasons,
                "protocol_error": protocol_error,
                "validated_at": now(),
            }
        return {
            **observed,
            "processing_status": "ERROR",
            "quality_decision": None,
            "stage": "VERIFIER_PROTOCOL",
            "reason_codes": [str(exc) or type(exc).__name__],
            "protocol_error": protocol_error,
            "validated_at": now(),
        }
    if actual_model != EXPECTED_VERIFIER_MODEL:
        return {
            **observed,
            "processing_status": "ERROR",
            "quality_decision": None,
            "stage": "VERIFIER_IDENTITY",
            "reason_codes": ["VERIFIER_ACTUAL_MODEL_MISMATCH"],
            "semantic_verifier": semantic,
            "protocol_error": None,
            "validated_at": now(),
        }
    return {
        **observed,
        "processing_status": "COMPLETED",
        "quality_decision": decision,
        "stage": "COMPLETE",
        "reason_codes": reasons,
        "semantic_verifier": semantic,
        "protocol_error": None,
        "validated_at": now(),
    }
