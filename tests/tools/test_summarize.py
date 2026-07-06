from sync_master.tools.summarize import summarize


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


def test_summarize_returns_llm_response_content(tmp_path):
    llm = FakeLLM("This is the summary.")

    result = summarize("transcript text", "Summarize in 3 paragraphs.", tmp_path, llm=llm)

    assert result == "This is the summary."


def test_summarize_includes_instructions_and_transcript_in_prompt(tmp_path):
    llm = FakeLLM("summary")

    summarize("the transcript body", "custom instructions", tmp_path, llm=llm)

    assert "custom instructions" in llm.received_prompt
    assert "the transcript body" in llm.received_prompt


def test_summarize_writes_summary_markdown_file(tmp_path):
    llm = FakeLLM("written summary")

    summarize("transcript", "instructions", tmp_path, llm=llm)

    assert (tmp_path / "summary.md").read_text() == "written summary"
