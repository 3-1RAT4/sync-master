import os
from pathlib import Path


def _default_llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        base_url=os.environ.get("LLM_BASE_URL"),
        api_key=os.environ.get("LLM_API_KEY"),
    )


def summarize(transcript_text: str, instructions: str, output_dir: Path, llm=None) -> str:
    llm = llm or _default_llm()
    prompt = f"{instructions}\n\nTranscript:\n{transcript_text}"

    response = llm.invoke(prompt)
    text = response.content if hasattr(response, "content") else str(response)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.md").write_text(text)

    return text
