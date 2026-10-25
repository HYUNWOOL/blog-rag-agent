"""BE/.env와 셸 환경변수에서 설정을 읽고, API를 부르기 전에 키가 채워졌는지 검사한다.

키 값은 로그, 예외 메시지, repr 어디에도 남기지 않는다.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# src/blog_rag_agent/config.py 기준 parents[2] = BE/
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
PLACEHOLDER = "REPLACE_ME"
EMBEDDING_PROVIDERS = ("api", "local")


class ConfigError(RuntimeError):
    """설정이 비었거나 잘못됐을 때. 메시지에는 변수 이름만 넣고 값은 넣지 않는다."""


@dataclass(frozen=True)
class Settings:
    # repr=False: print(settings)나 예외 트레이스에 찍혀도 키가 보이지 않게 한다.
    anthropic_api_key: str = field(repr=False)
    # DATABASE_URL에도 비밀번호가 들어 있으므로 같이 숨긴다.
    database_url: str = field(repr=False)
    embedding_provider: str
    embedding_model: str
    embedding_api_key: str | None = field(repr=False)
    langsmith_api_key: str | None = field(repr=False)
    langsmith_tracing: bool


def _is_unset(value: str | None) -> bool:
    # 빈 값과 .env.example의 자리표시자를 같은 "아직 안 넣음"으로 본다.
    return value is None or value.strip() in ("", PLACEHOLDER)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if _is_unset(value):
        # 값이 아니라 변수 이름만 메시지에 넣는다.
        raise ConfigError(f"{name}가 아직 설정되지 않았습니다. .env를 확인하세요")
    return value.strip()


def _optional(name: str) -> str | None:
    value = os.environ.get(name)
    return None if _is_unset(value) else value.strip()


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
    """설정을 읽어 검사한다. LLM·임베딩 클라이언트를 만들기 전에 가장 먼저 부른다."""
    if env_file is not None:
        # override=False: 셸에 이미 있는 같은 이름의 변수가 .env보다 우선한다.
        load_dotenv(env_file, override=False)

    # 다른 어떤 검사보다 먼저 해서, 키 없이 API를 부르는 경로가 생기지 않게 한다.
    anthropic_api_key = _require("ANTHROPIC_API_KEY")

    embedding_provider = os.environ.get("EMBEDDING_PROVIDER", "local").strip().lower()
    if embedding_provider not in EMBEDDING_PROVIDERS:
        # provider 이름은 시크릿이 아니라서 메시지에 넣어도 된다.
        raise ConfigError(
            f"EMBEDDING_PROVIDER는 {'/'.join(EMBEDDING_PROVIDERS)} 중 하나여야 합니다: "
            f"{embedding_provider!r}"
        )
    # 로컬 임베딩 모델을 쓰면 임베딩 API 키가 필요 없으니 검사하지 않는다.
    if embedding_provider == "api":
        embedding_api_key = _require("EMBEDDING_API_KEY")
    else:
        embedding_api_key = _optional("EMBEDDING_API_KEY")

    return Settings(
        anthropic_api_key=anthropic_api_key,
        database_url=_require("DATABASE_URL"),
        embedding_provider=embedding_provider,
        # 1주차 결정: 로컬 bge-m3(1024차원). 바꾸면 chunks.embedding 차원도 마이그레이션해야 한다.
        embedding_model=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3").strip(),
        embedding_api_key=embedding_api_key,
        langsmith_api_key=_optional("LANGSMITH_API_KEY"),
        langsmith_tracing=os.environ.get("LANGSMITH_TRACING", "false").strip().lower()
        == "true",
    )
