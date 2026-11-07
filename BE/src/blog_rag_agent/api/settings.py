"""웹 서버 설정. 기존 Settings(키·DB)에 서버 전용 비밀값과 한도 값을 더한다.

비밀값은 repr에 남기지 않고, 오류 메시지에는 변수 이름만 넣는다.
"""

import os
from dataclasses import dataclass, field
from decimal import Decimal

from blog_rag_agent.config import ConfigError, _require, load_settings

# 백만 토큰당 달러(입력, 출력). 2026-10 claude-api 문서 기준, 입력 10만 토큰 이하 구간.
# shortcut: 10만 토큰 초과 구간 단가($0.50/$2.50)는 무시한다. 질문당 입력이 1만 토큰 안팎이라 닿지 않는다.
PRICES_PER_MTOK = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
}
MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class ApiSettings:
    database_url: str = field(repr=False)
    anthropic_api_key: str = field(repr=False)
    embedding_model: str
    access_code_pepper: bytes = field(repr=False)
    session_secret: bytes = field(repr=False)
    daily_question_limit: int
    answer_max_tokens: int
    chat_model: str


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ConfigError(f"{name}는 양의 정수여야 합니다: {raw!r}")
    return int(raw)


def _secret(name: str) -> bytes:
    value = _require(name)
    if len(value) < MIN_SECRET_LENGTH:
        raise ConfigError(f"{name}는 {MIN_SECRET_LENGTH}자 이상이어야 합니다")
    return value.encode()


def load_api_settings() -> ApiSettings:
    base = load_settings()
    chat_model = os.environ.get("CHAT_MODEL", "claude-haiku-5-5").strip()
    if chat_model not in PRICES_PER_MTOK:
        # 단가를 모르는 모델은 비용을 기록할 수 없으니 서버를 띄우지 않는다.
        raise ConfigError(f"CHAT_MODEL의 단가가 없습니다: {chat_model!r}")
    return ApiSettings(
        database_url=base.database_url,
        anthropic_api_key=base.anthropic_api_key,
        embedding_model=base.embedding_model,
        access_code_pepper=_secret("ACCESS_CODE_PEPPER"),
        session_secret=_secret("SESSION_SECRET"),
        daily_question_limit=_positive_int("DAILY_QUESTION_LIMIT", 20),
        answer_max_tokens=_positive_int("ANSWER_MAX_TOKENS", 1024),
        chat_model=chat_model,
    )


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    price_in, price_out = PRICES_PER_MTOK[model]
    total = (input_tokens * price_in + output_tokens * price_out) / Decimal(1_000_000)
    # usage_log.cost_usd가 numeric(12, 6)이라 소수 6자리로 맞춘다.
    return total.quantize(Decimal("0.000001"))
