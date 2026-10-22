import json

import pandas as pd

from dataflow.operators.core_text import Text2QASampleEvaluator
from dataflow.operators.text_sft import AlpagasusSampleEvaluator


class FakeServing:
    def generate_from_input(self, user_inputs, system_prompt=None):
        return [None for _ in user_inputs]


def test_text2qa_empty_response_is_an_explicit_invalid_score():
    evaluator = Text2QASampleEvaluator(llm_serving=FakeServing())
    assert evaluator._parse_grade_and_feedback(None) == (
        None, "invalid_or_empty_model_response"
    )
    assert evaluator._parse_grade_and_feedback("**Feedback**: useful") == (
        None, "grading_parse_failed: useful"
    )


def test_text2qa_accepts_common_grading_formats_without_guessing_from_feedback():
    evaluator = Text2QASampleEvaluator(llm_serving=FakeServing())
    for heading in (
        "**Grading**: 4", "Grading: 4", "**Grading:** 4",
        "Grading：4", "Score: 4/5", "评分：4分", "**Grading**: [4]",
    ):
        assert evaluator._parse_grade_and_feedback(
            f"{heading}\n**Feedback**: useful for training"
        ) == (4.0, "useful for training")

    assert evaluator._parse_grade_and_feedback(
        "**Feedback**: I would give it 4 points."
    ) == (None, "grading_parse_failed: I would give it 4 points.")
    assert evaluator._parse_grade_and_feedback(
        "Grading: 6\n**Feedback**: useful"
    ) == (None, "grading_parse_failed: useful")


def test_text2qa_retries_only_unparseable_rows_once():
    class RetryServing:
        def __init__(self):
            self.calls = []

        def generate_from_input(self, user_inputs, system_prompt=None):
            self.calls.append(user_inputs)
            if len(self.calls) == 1:
                return ["**Feedback**: useful", "**Grading**: 5\n**Feedback**: strong"]
            return ["**Grading**: 4\n**Feedback**: useful"]

    serving = RetryServing()
    evaluator = Text2QASampleEvaluator(llm_serving=serving)
    grades, feedbacks, audit = evaluator._score_dimension(["first prompt", "second prompt"])
    assert grades == [4.0, 5.0]
    assert feedbacks == ["grading_parse_retry_recovered: useful", "strong"]
    assert len(serving.calls) == 2
    assert len(serving.calls[1]) == 1
    assert "same rubric" in serving.calls[1][0]
    assert [entry["parse_status"] for entry in audit] == ["retry_recovered", "parsed"]
    assert audit[0]["raw_response"] == "**Feedback**: useful"
    assert audit[0]["retry_response"] == "**Grading**: 4\n**Feedback**: useful"
    assert audit[1]["retry_response"] is None


def test_text2qa_marks_a_second_parse_failure():
    evaluator = Text2QASampleEvaluator(llm_serving=FakeServing())
    grades, feedbacks, audit = evaluator._score_dimension(["one prompt"])
    assert grades == [None]
    assert feedbacks[0].startswith("grading_parse_failed_after_retry:")
    assert audit[0]["parse_status"] == "parse_failed"
    assert audit[0]["raw_response"] is None
    assert audit[0]["retry_response"] is None


def test_text2qa_run_exports_parse_evidence_for_reuse_by_other_pipelines():
    class Storage:
        def __init__(self):
            self.frame = pd.DataFrame([{"question": "Why?", "answer": "Because."}])

        def read(self, output_type):
            assert output_type == "dataframe"
            return self.frame

        def write(self, frame):
            self.frame = frame
            return "test-output.jsonl"

    class Serving:
        def generate_from_input(self, user_inputs, system_prompt=None):
            return ["**Grading**: [4]\n**Feedback**: supported" for _ in user_inputs]

    storage = Storage()
    keys = Text2QASampleEvaluator(llm_serving=Serving()).run(
        storage, input_question_key="question", input_answer_key="answer"
    )
    for dimension in ("question_quality", "answer_alignment", "answer_verifiability", "downstream_value"):
        grade_key = f"{dimension}_grades"
        assert storage.frame.at[0, grade_key] == 4
        assert storage.frame.at[0, f"{grade_key}_parse_status"] == "parsed"
        assert storage.frame.at[0, f"{grade_key}_raw_response"].startswith("**Grading**: [4]")
        assert storage.frame.at[0, f"{grade_key}_retry_response"] is None
        assert f"{grade_key}_parse_status" in keys


def test_text2qa_verifiability_prompt_includes_source_and_untrusted_facts_only():
    evaluator = Text2QASampleEvaluator(llm_serving=FakeServing())
    evaluator.input_question_key = "question"
    evaluator.input_answer_key = "answer"
    evaluator.input_context_key = "raw_chunk"
    evaluator.input_supporting_facts_key = "QA_pairs"
    frame = pd.DataFrame([{
        "question": "What is the configured weight decay?",
        "answer": "0",
        "raw_chunk": "The configured weight decay is 0.1.",
        "QA_pairs": {"supporting_facts": ["weight decay of 0"]},
    }])

    question, alignment, verifiability, downstream = evaluator._build_prompts(frame)

    assert "The configured weight decay is 0.1." in verifiability[0]
    assert "- weight decay of 0" in verifiability[0]
    assert "untrusted model output" in verifiability[0]
    for prompt in (question[0], alignment[0], downstream[0]):
        assert "The configured weight decay is 0.1." not in prompt
        assert "weight decay of 0" not in prompt


def test_text2qa_requires_configured_source_fields():
    evaluator = Text2QASampleEvaluator(llm_serving=FakeServing())
    evaluator.input_question_key = "question"
    evaluator.input_answer_key = "answer"
    evaluator.input_context_key = "raw_chunk"
    evaluator.input_supporting_facts_key = "QA_pairs"
    evaluator.output_question_quality_key = "question_quality_grades"
    evaluator.output_question_quality_feedback_key = "question_quality_feedbacks"
    evaluator.output_answer_alignment_key = "answer_alignment_grades"
    evaluator.output_answer_alignment_feedback_key = "answer_alignment_feedbacks"
    evaluator.output_answer_verifiability_key = "answer_verifiability_grades"
    evaluator.output_answer_verifiability_feedback_key = "answer_verifiability_feedbacks"
    evaluator.output_downstream_value_key = "downstream_value_grades"
    evaluator.output_downstream_value_feedback_key = "downstream_value_feedbacks"

    try:
        evaluator._validate_dataframe(pd.DataFrame([{
            "question": "Q", "answer": "A", "raw_chunk": "C"
        }]))
    except ValueError as exc:
        assert "QA_pairs" in str(exc)
    else:
        raise AssertionError("missing supporting-facts field must be rejected")


def test_alpagasus_empty_response_does_not_crash():
    evaluator = AlpagasusSampleEvaluator(llm_serving=FakeServing())
    scores = evaluator.get_score(
        [{"question": "Q", "raw_chunk": "Context", "answer": "A"}],
        "question", "raw_chunk", "answer",
    )
    assert scores == [None]


def test_alpagasus_preserves_real_zero_and_marks_missing_response():
    class Serving:
        def generate_from_input(self, user_inputs, system_prompt=None):
            return ["0\nLow quality", "unreadable"]  # Third response is missing.

    evaluator = AlpagasusSampleEvaluator(llm_serving=Serving())
    samples = [{"question": "Q", "raw_chunk": "Context", "answer": "A"}] * 3
    scores, statuses, raw = evaluator.get_score(
        samples, "question", "raw_chunk", "answer", include_audit=True
    )
    assert scores == [0.0, None, None]
    assert statuses == ["parsed", "parse_failed", "parse_failed"]
    assert raw == ["0\nLow quality", "unreadable", None]
    encoded = pd.DataFrame({"score": scores, "status": statuses}).to_json(
        orient="records", lines=True
    )
    rows = [json.loads(line) for line in encoded.splitlines()]
    assert [row["score"] for row in rows] == [0, None, None]
    assert (pd.Series(scores) >= 4).tolist() == [False, False, False]


def test_alpagasus_run_writes_score_and_parse_evidence():
    class Storage:
        def __init__(self):
            self.frame = pd.DataFrame([
                {"question": "Q1", "raw_chunk": "Context", "answer": "A1"},
                {"question": "Q2", "raw_chunk": "Context", "answer": "A2"},
            ])

        def read(self, output_type):
            assert output_type == "dataframe"
            return self.frame

        def write(self, frame):
            self.frame = frame
            return "test-output.jsonl"

    class Serving:
        def generate_from_input(self, user_inputs, system_prompt=None):
            return ["0\nLow quality", "unreadable"]

    storage = Storage()
    keys = AlpagasusSampleEvaluator(llm_serving=Serving()).run(
        storage, "question", "raw_chunk", "answer"
    )
    assert keys == [
        "AlpagasusScore", "AlpagasusScore_parse_status",
        "AlpagasusScore_raw_response",
    ]
    rows = [json.loads(line) for line in storage.frame.to_json(
        orient="records", lines=True
    ).splitlines()]
    assert [row["AlpagasusScore"] for row in rows] == [0, None]
    assert [row["AlpagasusScore_parse_status"] for row in rows] == [
        "parsed", "parse_failed"
    ]
    assert [row["AlpagasusScore_raw_response"] for row in rows] == [
        "0\nLow quality", "unreadable"
    ]
