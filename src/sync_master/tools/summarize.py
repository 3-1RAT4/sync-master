import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SummaryResult:
    content: str
    llm_provider: str
    llm_model: str


def _load_llm_config() -> dict:
    from sync_master.config import load_llm_config

    llm_config_path = Path.home() / ".config" / "sync-master" / "llm.yaml"
    return load_llm_config(llm_config_path)


def _default_llm(llm_config: dict):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=llm_config["model"],
        base_url=llm_config.get("base_url"),
        api_key=os.environ.get("LLM_API_KEY"),
    )


def summarize(
    transcript_text: str,
    instructions: str,
    llm=None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> SummaryResult:
    if llm is None:
        llm_config = _load_llm_config()
        llm = _default_llm(llm_config)
        llm_provider = llm_config["provider"]
        llm_model = llm_config["model"]

    prompt = f"{instructions}\n\nTranscript:\n{transcript_text}"

    response = llm.invoke(prompt)
    text = response.content if hasattr(response, "content") else str(response)

    return SummaryResult(
        content=text,
        llm_provider=llm_provider or "unknown",
        llm_model=llm_model or "unknown",
    )
