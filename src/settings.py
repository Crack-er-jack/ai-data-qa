"""Environment / Streamlit secrets configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _secret_or_env(*names: str, default: str | None = None) -> str | None:
    try:
        import streamlit as st

        for name in names:
            if name in st.secrets:
                value = st.secrets[name]
                if value not in (None, ""):
                    return str(value)
    except Exception:
        pass
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None
    llm_provider: str
    llm_model: str
    llm_temperature: float

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key) and self.llm_provider.lower() == "groq"


def get_settings() -> Settings:
    temperature_raw = _secret_or_env("LLM_TEMPERATURE", default="0") or "0"
    try:
        temperature = float(temperature_raw)
    except ValueError:
        temperature = 0.0
    return Settings(
        groq_api_key=_secret_or_env("GROQ_API_KEY"),
        llm_provider=(_secret_or_env("LLM_PROVIDER", default="groq") or "groq").lower(),
        llm_model=_secret_or_env("LLM_MODEL", default="openai/gpt-oss-20b")
        or "openai/gpt-oss-20b",
        llm_temperature=temperature,
    )
