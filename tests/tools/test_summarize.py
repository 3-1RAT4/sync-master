from sync_master.tools.summarize import SummaryResult, summarize


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, response_text):
        self.response_text = response_text
        self.received_prompt = None

    def invoke(self, prompt):
        self.received_prompt = prompt
        return FakeResponse(self.response_text)


def test_summarize_returns_summary_result_with_content():
    llm = FakeLLM("This is the summary.")

    result = summarize("transcript text", "Summarize in 3 paragraphs.", llm=llm)

    assert result == SummaryResult(content="This is the summary.", llm_provider="unknown", llm_model="unknown")


def test_summarize_includes_instructions_and_transcript_in_prompt():
    llm = FakeLLM("summary")

    summarize("the transcript body", "custom instructions", llm=llm)

    assert "custom instructions" in llm.received_prompt
    assert "the transcript body" in llm.received_prompt


def test_summarize_passes_through_given_llm_provider_and_model():
    llm = FakeLLM("summary")

    result = summarize(
        "transcript", "instructions", llm=llm, llm_provider="deepseek", llm_model="deepseek-chat"
    )

    assert result.llm_provider == "deepseek"
    assert result.llm_model == "deepseek-chat"
