"""Explicit, non-secret runtime configuration for the LLM boundary."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class LLMRuntimeConfig:
    api_key: str = ""
    api_base: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    source: str = "unconfigured"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def redacted(self) -> dict[str, str | bool]:
        """Return fields safe to include in an audit record."""
        return {
            "configured": self.configured,
            "source": self.source,
            "api_base": self.api_base,
            "model": self.model,
        }


def load_runtime_config(environ: dict[str, str] | None = None) -> LLMRuntimeConfig:
    """Read process environment variables; never load a dotenv file implicitly."""
    values = os.environ if environ is None else environ
    api_key = values.get("LLM_API_KEY", "").strip()
    return LLMRuntimeConfig(
        api_key=api_key,
        api_base=values.get("LLM_API_BASE", "https://api.deepseek.com").strip(),
        model=values.get("LLM_MODEL", "deepseek-v4-flash").strip(),
        source="environment" if api_key else "unconfigured",
    )
