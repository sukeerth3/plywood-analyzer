"""Environment-driven configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


@dataclass(frozen=True)
class Config:
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    SQLITE_DB: str
    ANTHROPIC_API_KEY: str | None
    LOG_LEVEL: str
    HOST: str
    PORT: int
    CORS_ORIGINS: str
    STATS_CACHE_TTL_SECONDS: float
    SOURCE_CACHE_TTL_SECONDS: float
    NL_QUESTION_MAX_LEN: int

    @classmethod
    def from_env(cls) -> "Config":
        # best-effort .env load; python-dotenv is already a project dep
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except Exception:
            pass

        return cls(
            NEO4J_URI=_env("NEO4J_URI", "bolt://localhost:7687"),
            NEO4J_USER=_env("NEO4J_USER", "neo4j"),
            NEO4J_PASSWORD=_env("NEO4J_PASSWORD", "plywood2026"),
            SQLITE_DB=_env("SQLITE_DB", "data/coverage.db"),
            ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY") or None,
            LOG_LEVEL=_env("LOG_LEVEL", "INFO"),
            HOST=_env("WEB_HOST", "0.0.0.0"),
            PORT=int(_env("WEB_PORT", "5000")),
            CORS_ORIGINS=_env("CORS_ORIGINS", "*"),
            STATS_CACHE_TTL_SECONDS=float(_env("STATS_CACHE_TTL", "10")),
            SOURCE_CACHE_TTL_SECONDS=float(_env("SOURCE_CACHE_TTL", "60")),
            NL_QUESTION_MAX_LEN=int(_env("NL_QUESTION_MAX_LEN", "500")),
        )
