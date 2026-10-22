import json

from dataflow.operators.core_text import Text2MultiHopQAGenerator


class FakeServing:
    def __init__(self):
        self.request_count = 0

    def generate_from_input(self, user_inputs, system_prompt):
        self.request_count += len(user_inputs)
        return [
            None,
            json.dumps({"question": "What does the paper report?", "answer": "A finding."}),
        ]


def test_timeout_response_is_skipped_and_num_q_caps_requests():
    serving = FakeServing()
    generator = Text2MultiHopQAGenerator(llm_serving=serving, lang="en", num_q=2)
    text = (
        "This paper compares several approaches to supervised fine tuning. "
        "The authors report detailed experimental results across datasets. "
        "Their analysis connects data composition with model behavior. "
        "The discussion describes important limitations for future work. "
        "The conclusion summarizes the observations from these experiments. "
    )

    examples = generator.process_batch([text])

    assert serving.request_count == 2
    assert examples[0]["qa_pairs"] == [
        {"question": "What does the paper report?", "answer": "A finding."}
    ]
