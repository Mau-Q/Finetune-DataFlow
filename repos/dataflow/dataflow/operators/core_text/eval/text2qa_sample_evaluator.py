import pandas as pd
from dataflow.utils.registry import OPERATOR_REGISTRY
from dataflow import get_logger
import re
from dataflow.utils.storage import DataFlowStorage
from dataflow.core import OperatorABC
from dataflow.core import LLMServingABC
from dataflow.core.prompt import prompt_restrict, DIYPromptABC

from dataflow.prompts.text2qa import (
    Text2QAQuestionQualityPrompt,
    Text2QAAnswerAlignmentPrompt,
    Text2QAAnswerVerifiabilityPrompt,
    Text2QADownstreamValuePrompt
)

@prompt_restrict(
    Text2QAQuestionQualityPrompt,
    Text2QAAnswerAlignmentPrompt,
    Text2QAAnswerVerifiabilityPrompt,
    Text2QADownstreamValuePrompt
)
@OPERATOR_REGISTRY.register()
class Text2QASampleEvaluator(OperatorABC):
    '''
    Answer Generator is a class that generates answers for given questions.
    '''
    def __init__(self, 
                 llm_serving: LLMServingABC,
                 question_quality_prompt_template: DIYPromptABC = None,
                 answer_alignment_prompt_template: DIYPromptABC = None,
                 answer_verifiability_prompt_template: DIYPromptABC = None,
                 downstream_value_prompt_template: DIYPromptABC = None,
                 ):
        self.logger = get_logger()   
        self.llm_serving = llm_serving
        self.rubric_templates = {
            'question_quality': question_quality_prompt_template,
            'answer_alignment': answer_alignment_prompt_template,
            'answer_verifiability': answer_verifiability_prompt_template,
            'downstream_value': downstream_value_prompt_template,
        }
        for key, prompt in self.rubric_templates.items():
            if prompt is not None and not isinstance(prompt, DIYPromptABC):
                raise TypeError(f'{key} rubric must be a DIYPromptABC')
    
    @staticmethod
    def get_desc(lang: str = "zh"):
        if lang == "zh":
            return (
                "该算子用于为给的的文档片段生成种子QA对打分\n\n"
                "输入参数：\n"
                "- input_question_key: Field name containing the generated question\n"
                "- input_answer_key: Field name containing the generated answer\n"
                "- input_context_key: Optional field containing source context for grounded verifiability\n"
                "- input_supporting_facts_key: Optional field containing untrusted supporting facts\n"
                "- output_question_quality_key: Field name containing the question quality grade\n"
                "- output_question_quality_feedback_key: Field name containing the question quality feedback\n"
                "- output_answer_alignment_key: Field name containing the answer alignment grade\n"
                "- output_answer_alignment_feedback_key: Field name containing the answer alignment feedback\n"
                "- output_answer_verifiability_key: Field name containing the answer verifiability grade\n"
                "- output_downstream_value_key: Field name containing the downstream value grade\n"
                "- output_downstream_value_feedback_key: Field name containing the downstream value feedback\n"
            )
        elif lang == "en":
            return (
                "This operator generates prompts for given document fragments to generate seed QA pairs.\n\n"
                "Input Parameters:\n"
                "- input_question_key: Field name containing the generated question\n"
                "- input_answer_key: Field name containing the generated answer\n"
                "- input_context_key: Optional field containing source context for grounded verifiability\n"
                "- input_supporting_facts_key: Optional field containing untrusted supporting facts\n"
                "- output_question_quality_key: Field name containing the question quality grade\n"
                "- output_question_quality_feedback_key: Field name containing the question quality feedback\n"
                "- output_answer_alignment_key: Field name containing the answer alignment grade\n"
                "- output_answer_alignment_feedback_key: Field name containing the answer alignment feedback\n"
                "- output_answer_verifiability_key: Field name containing the answer verifiability grade\n"
                "- output_downstream_value_key: Field name containing the downstream value grade\n"
                "- output_downstream_value_feedback_key: Field name containing the downstream value feedback\n"
            )
        else:
            return "QAScorer scores QA pairs for given document fragments."

    def _validate_dataframe(self, dataframe: pd.DataFrame):
        required_keys = [self.input_question_key, self.input_answer_key]
        required_keys += [
            key for key in (
                self.input_context_key,
                self.input_supporting_facts_key,
            )
            if key
        ]
        grade_keys = [self.output_question_quality_key, self.output_answer_alignment_key,
                      self.output_answer_verifiability_key, self.output_downstream_value_key]
        forbidden_keys = [self.output_question_quality_key, self.output_question_quality_feedback_key, self.output_answer_alignment_key, self.output_answer_alignment_feedback_key, self.output_answer_verifiability_key, self.output_answer_verifiability_feedback_key, self.output_downstream_value_key, self.output_downstream_value_feedback_key]
        forbidden_keys += [f"{key}_{suffix}" for key in grade_keys
                           for suffix in ("parse_status", "raw_response", "retry_response")]

        missing = [k for k in required_keys if k not in dataframe.columns]
        conflict = [k for k in forbidden_keys if k in dataframe.columns]

        if missing:
            raise ValueError(f"Missing required column(s): {missing}")
        if conflict:
            raise ValueError(f"The following column(s) already exist and would be overwritten: {conflict}")

    def _build_prompts(self, dataframe):
        """
        Reformat the prompts in the dataframe to generate questions.
        """
        question_quality_inputs = []
        self.prompts = Text2QAQuestionQualityPrompt()
        question_quality_prompt = self.prompts.build_prompt()
        if self.rubric_templates['question_quality'] is not None:
            question_quality_prompt = self.rubric_templates['question_quality'].build_prompt() + (
                '\nRequired output: **Grading**: N, where N is an integer from 1 to 5; '
                '**Feedback**: explanation. Do not change the scale or field names.\n'
            )
        answer_alignment_inputs = []
        self.prompts = Text2QAAnswerAlignmentPrompt()
        answer_alignment_prompt = self.prompts.build_prompt()
        if self.rubric_templates['answer_alignment'] is not None:
            answer_alignment_prompt = self.rubric_templates['answer_alignment'].build_prompt() + (
                '\nRequired output: **Grading**: N, where N is an integer from 1 to 5; '
                '**Feedback**: explanation. Do not change the scale or field names.\n'
            )
        answer_verifiability_inputs = []
        self.prompts = Text2QAAnswerVerifiabilityPrompt()
        answer_verifiability_prompt = self.prompts.build_prompt()
        if self.rubric_templates['answer_verifiability'] is not None:
            answer_verifiability_prompt = self.rubric_templates['answer_verifiability'].build_prompt() + (
                '\nRequired output: **Grading**: N, where N is an integer from 1 to 5; '
                '**Feedback**: explanation. Do not change the scale or field names.\n'
            )
        downstream_value_inputs = []
        self.prompts = Text2QADownstreamValuePrompt()
        downstream_value_prompt = self.prompts.build_prompt()
        if self.rubric_templates['downstream_value'] is not None:
            downstream_value_prompt = self.rubric_templates['downstream_value'].build_prompt() + (
                '\nRequired output: **Grading**: N, where N is an integer from 1 to 5; '
                '**Feedback**: explanation. Do not change the scale or field names.\n'
            )

        for index, row in dataframe.iterrows():
            question_quality_content = question_quality_prompt + "Question: " + row[self.input_question_key] + "\n" + "Answer: " + row[self.input_answer_key]
            question_quality_inputs.append(question_quality_content)
            answer_alignment_content = answer_alignment_prompt + "Question: " + row[self.input_question_key] + "\n" + "Answer: " + row[self.input_answer_key]
            answer_alignment_inputs.append(answer_alignment_content)
            context = (
                row[self.input_context_key]
                if self.input_context_key else "[No source context supplied]"
            )
            if not isinstance(context, str):
                context = str(context)
            supporting_facts = []
            if self.input_supporting_facts_key:
                supporting_value = row[self.input_supporting_facts_key]
                if isinstance(supporting_value, dict):
                    supporting_facts = supporting_value.get("supporting_facts", [])
                elif isinstance(supporting_value, list):
                    supporting_facts = supporting_value
            if not isinstance(supporting_facts, list):
                supporting_facts = [supporting_facts]
            formatted_facts = "\n".join(
                f"- {fact}" for fact in supporting_facts if isinstance(fact, str)
            ) or "[No candidate supporting facts supplied]"
            answer_verifiability_content = (
                answer_verifiability_prompt
                + "Source context:\n" + context + "\n\n"
                + "Candidate supporting facts:\n" + formatted_facts + "\n\n"
                + "Question: " + row[self.input_question_key] + "\n"
                + "Answer: " + row[self.input_answer_key]
            )
            answer_verifiability_inputs.append(answer_verifiability_content)
            downstream_value_content = downstream_value_prompt + "Question: " + row[self.input_question_key] + "\n" + "Answer: " + row[self.input_answer_key]
            downstream_value_inputs.append(downstream_value_content)

        return question_quality_inputs, answer_alignment_inputs, answer_verifiability_inputs, downstream_value_inputs

    def _parse_grade_and_feedback(self, response: str) -> tuple:
        if not isinstance(response, str) or not response.strip():
            self.logger.warning("Skipping empty or non-text Text2QA evaluation response")
            return None, "invalid_or_empty_model_response"
        # Models often move the Markdown bold markers around the label/colon.
        # Read only an explicit grading line; never infer a grade from feedback.
        grading = None
        for line in response.splitlines():
            heading = line.strip().replace("**", "").replace("`", "")
            match = re.fullmatch(
                r"(?:[-*]\s*)?(?:Grading|Grade|Score|评分)\s*[:：]\s*"
                r"(?:\[\s*([1-5])\s*\]|([1-5]))"
                r"(?:\s*(?:/\s*5|分))?\s*",
                heading,
                re.IGNORECASE,
            )
            if match:
                grading = float(match.group(1) or match.group(2))
                break
        feedback_match = re.search(
            r"^\s*(?:\*\*)?(?:Feedback|反馈)(?:\*\*)?\s*[:：]\s*(.+)",
            response, re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        feedback = feedback_match.group(1).strip() if feedback_match else ''
        if grading is None:
            self.logger.warning("Text2QA evaluation response has no parseable grading")
            feedback = f"grading_parse_failed: {feedback}".rstrip()

        return grading, feedback

    def _score_dimension(self, inputs: list[str]) -> tuple:
        responses = self.llm_serving.generate_from_input(user_inputs=inputs, system_prompt="")
        if not isinstance(responses, list):
            responses = []
        grades = []
        feedbacks = []
        audit = []
        for index, prompt in enumerate(inputs):
            response = responses[index] if index < len(responses) else None
            grade, feedback = self._parse_grade_and_feedback(response)
            retry_response = None
            parse_status = "parsed"
            if grade is None:
                self.logger.warning(
                    f"Retrying unparseable Text2QA grade for row {index}; "
                    f"raw response: {str(response)[:200]!r}"
                )
                retry_prompt = (
                    prompt + "\nYour previous reply did not provide a parseable grade. "
                    "Re-evaluate using the same rubric. Reply with exactly two fields: "
                    "**Grading**: N (where N is an integer from 1 to 5), followed by "
                    "**Feedback**: your explanation.\n"
                )
                try:
                    retry_responses = self.llm_serving.generate_from_input(
                        user_inputs=[retry_prompt], system_prompt=""
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"Text2QA grade retry failed for row {index}: {type(exc).__name__}"
                    )
                    retry_responses = []
                retry_response = (
                    retry_responses[0]
                    if isinstance(retry_responses, list) and retry_responses else None
                )
                retry_grade, retry_feedback = self._parse_grade_and_feedback(retry_response)
                if retry_grade is not None:
                    grade, feedback = retry_grade, f"grading_parse_retry_recovered: {retry_feedback}"
                    parse_status = "retry_recovered"
                else:
                    feedback = f"grading_parse_failed_after_retry: {feedback}"
                    parse_status = "parse_failed"
            grades.append(grade)
            feedbacks.append(feedback)
            audit.append({"parse_status": parse_status, "raw_response": response,
                          "retry_response": retry_response})
        return grades, feedbacks, audit

    def run(
        self,
        storage: DataFlowStorage,
        input_question_key: str = "generated_question",
        input_answer_key: str = "generated_answer",
        input_context_key: str | None = None,
        input_supporting_facts_key: str | None = None,
        output_question_quality_key: str = "question_quality_grades",
        output_question_quality_feedback_key: str = "question_quality_feedbacks",
        output_answer_alignment_key: str = "answer_alignment_grades",
        output_answer_alignment_feedback_key: str = "answer_alignment_feedbacks",
        output_answer_verifiability_key: str = "answer_verifiability_grades",
        output_answer_verifiability_feedback_key: str = "answer_verifiability_feedbacks",
        output_downstream_value_key: str = "downstream_value_grades",
        output_downstream_value_feedback_key: str = "downstream_value_feedbacks"
    ):
        self.input_question_key = input_question_key
        self.input_answer_key = input_answer_key
        self.input_context_key = input_context_key
        self.input_supporting_facts_key = input_supporting_facts_key
        self.output_question_quality_key = output_question_quality_key
        self.output_question_quality_feedback_key = output_question_quality_feedback_key
        self.output_answer_alignment_key = output_answer_alignment_key
        self.output_answer_alignment_feedback_key = output_answer_alignment_feedback_key
        self.output_answer_verifiability_key = output_answer_verifiability_key
        self.output_answer_verifiability_feedback_key = output_answer_verifiability_feedback_key
        self.output_downstream_value_key = output_downstream_value_key
        self.output_downstream_value_feedback_key = output_downstream_value_feedback_key

        dataframe = storage.read("dataframe")
        self._validate_dataframe(dataframe)

        # 构建prompt
        q_inputs, a_inputs, v_inputs, d_inputs = self._build_prompts(dataframe)

        # 生成四类分数和反馈
        self.logger.info("Scoring question quality...")
        q_grades, q_feedbacks, q_audit = self._score_dimension(q_inputs)

        self.logger.info("Scoring answer alignment...")
        a_grades, a_feedbacks, a_audit = self._score_dimension(a_inputs)

        self.logger.info("Scoring answer verifiability...")
        v_grades, v_feedbacks, v_audit = self._score_dimension(v_inputs)

        self.logger.info("Scoring downstream value...")
        d_grades, d_feedbacks, d_audit = self._score_dimension(d_inputs)

        # 写回结果
        dataframe[self.output_question_quality_key] = q_grades
        dataframe[self.output_question_quality_feedback_key] = q_feedbacks
        dataframe[self.output_answer_alignment_key] = a_grades
        dataframe[self.output_answer_alignment_feedback_key] = a_feedbacks
        dataframe[self.output_answer_verifiability_key] = v_grades
        dataframe[self.output_answer_verifiability_feedback_key] = v_feedbacks
        dataframe[self.output_downstream_value_key] = d_grades
        dataframe[self.output_downstream_value_feedback_key] = d_feedbacks
        audit_keys = (self.output_question_quality_key, self.output_answer_alignment_key,
                      self.output_answer_verifiability_key, self.output_downstream_value_key)
        for key, entries in zip(audit_keys, (q_audit, a_audit, v_audit, d_audit)):
            for field in ("parse_status", "raw_response", "retry_response"):
                dataframe[f"{key}_{field}"] = [entry[field] for entry in entries]

        output_file = storage.write(dataframe)
        self.logger.info(f"Results saved to {output_file}")

        return [
            output_question_quality_key, output_question_quality_feedback_key,
            output_answer_alignment_key, output_answer_alignment_feedback_key,
            output_answer_verifiability_key, output_answer_verifiability_feedback_key,
            output_downstream_value_key, output_downstream_value_feedback_key
        ] + [f"{key}_{field}" for key in audit_keys
             for field in ("parse_status", "raw_response", "retry_response")]
