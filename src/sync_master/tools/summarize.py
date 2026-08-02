import os
from pathlib import Path


def _default_llm():
    from langchain_openai import ChatOpenAI

    from sync_master.config import load_llm_config

    llm_config_path = Path.home() / ".config" / "sync-master" / "llm.yaml"
    llm_config = load_llm_config(llm_config_path)

    return ChatOpenAI(
        model=llm_config["model"],
        base_url=llm_config.get("base_url"),
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
