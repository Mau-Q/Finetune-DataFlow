"""Protocol adapters around reused generation, evaluation and filtering operators."""
import json
import math
import pandas as pd
from jsonschema import validators
from dataflow.core import OperatorABC
from dataflow.utils.registry import OPERATOR_REGISTRY
from dataflow.utils.storage import DataFlowStorage
from app.services.simple_training_operators import parse_candidate, row_issues, same_answer, image_data


def required_columns(frame, *columns):
    missing = [key for key in columns if key and key not in frame]
    if missing:
        raise ValueError(f'Missing {missing}; available columns: {list(frame.columns)}')


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


@OPERATOR_REGISTRY.register()
class TrainingQAExpander(OperatorABC):
    WEBUI_CATEGORY = ('core_text', 'refine')

    @staticmethod
    def get_desc(lang='zh'):
        return '展开多跳 QA 列表，保留来源和生成证据，将问题和回答绑定为独立字段。' if lang == 'zh' else 'Expand QA lists while preserving source evidence.'

    def run(self, storage: DataFlowStorage, input_key='qa_pairs', output_key='candidate', output_question_key='question', output_answer_key='answer'):
        frame = storage.read('dataframe')
        if not frame.empty:
            required_columns(frame, input_key)
        rows = []
        for _, row in frame.iterrows():
            pairs = row[input_key]
            if not isinstance(pairs, list) or not pairs:
                pairs = [None]
            for pair in pairs:
                if not isinstance(pair, dict) or not all(nonempty(pair.get(k)) for k in ('question', 'answer')):
                    rec = row.to_dict()
                    rec.update({output_key:{}, output_question_key:'', output_answer_key:'',
                                '_training_issues':row_issues(row) + ['多跳 QA 含无效问题或回答']})
                    rows.append(rec)
                    continue
                rec = row.to_dict()
                rec.update({output_key: {'question': pair['question'], 'answer': pair['answer']},
                            output_question_key: pair['question'], output_answer_key: pair['answer']})
                rows.append(rec)
        columns = list(dict.fromkeys([*frame.columns, output_key, output_question_key, output_answer_key, '_training_issues']))
        storage.write(pd.DataFrame(rows, columns=columns))
        return [output_key, output_question_key, output_answer_key]


@OPERATOR_REGISTRY.register()
class TrainingPreferenceBuilder(OperatorABC):
    WEBUI_CATEGORY = ('core_text', 'refine')

    def __init__(self, llm_serving=None, max_negative_retries: int = 2):
        super().__init__()
        if type(max_negative_retries) is not int or not 0 <= max_negative_retries <= 3:
            raise ValueError('负例重试次数必须在 0–3 之间')
        self.llm_serving, self.max_negative_retries = llm_serving, max_negative_retries

    @staticmethod
    def get_desc(lang='zh'):
        return '组合同题正负例；相同回答有界重生成负例，失败样本单独记录。' if lang == 'zh' else 'Build preference pairs with bounded negative regeneration and per-row isolation.'

    def _negative(self, row, a, previous):
        prompt = ('生成同题合成负例：故意改变一个明确的数值、事实或条件。不得复制正例或仅改变格式、单位。'
                  '仅输出 JSON，question 必须逐字保留，answer 为负例回答。\n问题：' + a['question'] +
                  '\n正例：' + a['answer'] + '\n上次无效负例：' + str(previous))
        if row.get('media_ref'):
            conversation = [{'role':'user','content':[{'type':'text','text':prompt},
                {'type':'image_url','image_url':{'url':image_data(row['source'])}}]}]
            return self.llm_serving.generate_from_conversations([conversation])[0]
        return self.llm_serving.generate_from_input([prompt + '\n原始材料：' + str(row.get('text', ''))])[0]

    def run(self, storage: DataFlowStorage, input_key='candidate_a', input_alternative_key='candidate_b', output_key='alternatives'):
        frame = storage.read('dataframe')
        required_columns(frame, input_key, input_alternative_key)
        values, reports, attempts = [], [], []
        for _, row in frame.iterrows():
            errors, responses = row_issues(row), []
            pair = dict(question='', answer_a='', answer_b='')
            reason = '正例 JSON 无效'
            try:
                a = parse_candidate(row[input_key])
                reason = '正例缺少问题或回答'
                if not all(nonempty(a.get(k)) for k in ('question','answer')):
                    raise ValueError('正例缺少问题或回答')
                raw = row[input_alternative_key]
                for attempt in range(self.max_negative_retries + 1):
                    try:
                        reason = '负例 JSON 无效'
                        b = parse_candidate(raw)
                        reason = '负例缺少问题或回答'
                        if not all(nonempty(b.get(k)) for k in ('question','answer')):
                            raise ValueError(reason)
                        reason = '候选 A/B 使用了不同问题'
                        if a['question'].strip() != b['question'].strip():
                            raise ValueError(reason)
                        reason = '正负回答相同或只有简单格式差异'
                        if same_answer(a['answer'], b['answer']):
                            raise ValueError('正负回答相同')
                        pair = dict(question=a['question'].strip(), answer_a=a['answer'].strip(), answer_b=b['answer'].strip())
                        break
                    except (ValueError, TypeError, KeyError):
                        if not self.llm_serving or attempt == self.max_negative_retries:
                            raise ValueError('负例无效或与正例相同，已达到重试上限') from None
                        try:
                            raw = self._negative(row, a, raw)
                            responses.append(raw)
                        except Exception as exc:
                            responses.append({'error_type': type(exc).__name__})
            except Exception as exc:
                # A malformed or exhausted row cannot discard the remaining batch.
                errors.append(f'{reason}（{type(exc).__name__}；负例重试 {len(responses)} 次）')
            values.append(pair); reports.append(errors); attempts.append(responses)
        frame[output_key] = values
        frame['_training_issues'] = reports
        frame['negative_retry_responses'] = attempts
        storage.write(frame)
        return [output_key]


@OPERATOR_REGISTRY.register()
class TrainingReviewParser(OperatorABC):
    WEBUI_CATEGORY = ('core_text', 'refine')

    def __init__(self, training_type='sft', json_schema=None, min_score: float = 4, min_gap: float = 1):
        super().__init__()
        if training_type not in {'sft', 'dpo'}:
            raise ValueError('训练类型无效')
        if not (isinstance(min_score, (int, float)) and not isinstance(min_score, bool) and math.isfinite(min_score) and 1 <= min_score <= 5):
            raise ValueError('min_score 必须在 1–5 之间')
        if not (isinstance(min_gap, (int, float)) and not isinstance(min_gap, bool) and math.isfinite(min_gap) and 0 < min_gap <= 4):
            raise ValueError('min_gap 必须大于 0 且不超过 4')
        if not isinstance(json_schema, dict):
            raise ValueError('请选择评价结果 Schema')
        cls = validators.validator_for(json_schema)
        cls.check_schema(json_schema)
        self.validator = cls(json_schema)
        self.training_type, self.min_score, self.min_gap = training_type, min_score, min_gap

    @staticmethod
    def get_desc(lang='zh'):
        return '解析独立评价；检查图片问题一致性，按分数和来源依据决定是否准入；平局、无效评价不生成 DPO。' if lang == 'zh' else 'Parse reviews and admit only grounded, decisive preferences.'

    def run(self, storage: DataFlowStorage, input_key='review', input_candidate_key='candidate', input_question_key=None,
            output_key='accepted', output_candidate_key='candidate', output_reason_key='admission_reason'):
        frame = storage.read('dataframe')
        required_columns(frame, input_key, input_candidate_key, input_question_key)
        decisions, candidates, reasons = [], [], []
        for _, row in frame.iterrows():
            accepted, candidate, reason = False, {}, 'invalid_review'
            try:
                review = parse_candidate(row[input_key])
                self.validator.validate(review)
                source = parse_candidate(row[input_candidate_key])
                if not nonempty(source.get('question')):
                    raise ValueError('问题为空')
                if input_question_key:
                    question = parse_candidate(row[input_question_key]).get('question')
                    if not nonempty(question) or question.strip() != source['question'].strip():
                        raise ValueError('生成回答时问题发生变化')
                if self.training_type == 'sft':
                    if not nonempty(source.get('answer')):
                        raise ValueError('回答为空')
                    score = review['score']
                    if type(score) not in (int, float) or not math.isfinite(score) or not 1 <= score <= 5 or type(review['grounded']) is not bool:
                        raise ValueError('评价字段类型无效')
                    candidate = source
                    accepted = score >= self.min_score and review['grounded']
                    reason = 'accepted' if accepted else 'low_score_or_ungrounded'
                else:
                    a, b = source['answer_a'], source['answer_b']
                    scores = [review['score_a'], review['score_b']]
                    grounded = [review['grounded_a'], review['grounded_b']]
                    if not all(nonempty(v) for v in (a,b)) or any(type(s) not in (int,float) or not math.isfinite(s) or not 1 <= s <= 5 for s in scores) or any(type(g) is not bool for g in grounded):
                        raise ValueError('候选或评价字段类型无效')
                    winner = 0 if scores[0] > scores[1] else 1
                    accepted = (a.strip() != b.strip() and abs(scores[0]-scores[1]) >= self.min_gap
                                and scores[winner] >= self.min_score and grounded[winner])
                    candidate = dict(question=source['question'], chosen=(a,b)[winner], rejected=(a,b)[1-winner]) if accepted else {}
                    reason = 'accepted' if accepted else 'tie_small_gap_identical_or_ungrounded'
            except Exception:
                # Invalid reviews are explicit rejections, never inferred scores.
                pass
            decisions.append(accepted); candidates.append(candidate); reasons.append(reason)
        frame[output_key], frame[output_candidate_key], frame[output_reason_key] = decisions, candidates, reasons
        storage.write(frame)
        return [output_key, output_candidate_key, output_reason_key]
