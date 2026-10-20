import pytest

from blog_rag_agent.config import ConfigError, load_settings

# 실제 키처럼 생긴 가짜 값. 이 문자열이 메시지나 repr에 나오면 유출이다.
FAKE_KEY = "sk-ant-test-DO-NOT-LEAK-123"
ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "DATABASE_URL",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_API_KEY",
    "LANGSMITH_API_KEY",
    "LANGSMITH_TRACING",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # 개발자 셸이나 BE/.env 값이 테스트에 섞이지 않게 비우고 시작한다.
    # setenv를 먼저 해 두면 monkeypatch가 원래 상태를 기록해서, load_dotenv가 넣은 값도 테스트 뒤에 지워진다.
    for name in ENV_NAMES:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


def write_env(tmp_path, **values):
    path = tmp_path / ".env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path


BASE = {"DATABASE_URL": "postgresql://rag:rag@localhost:5432/rag"}


@pytest.mark.parametrize("value", ["REPLACE_ME", "", "  "])
def test_stops_when_anthropic_key_is_placeholder_or_empty(tmp_path, value):
    env = write_env(tmp_path, ANTHROPIC_API_KEY=value, **BASE)
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert (
        str(exc.value)
        == "ANTHROPIC_API_KEY가 아직 설정되지 않았습니다. .env를 확인하세요"
    )


def test_error_message_does_not_contain_key_values(tmp_path):
    # Anthropic 키는 채워져 있고 임베딩 키에서 실패하는 경우, 메시지에 Anthropic 키가 새면 안 된다.
    env = write_env(
        tmp_path,
        ANTHROPIC_API_KEY=FAKE_KEY,
        EMBEDDING_PROVIDER="api",
        EMBEDDING_API_KEY="REPLACE_ME",
        **BASE,
    )
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    message = str(exc.value) + repr(exc.value)
    assert "EMBEDDING_API_KEY" in message
    assert FAKE_KEY not in message
    assert "REPLACE_ME" not in message


def test_local_embedding_skips_embedding_key_check(tmp_path):
    env = write_env(
        tmp_path,
        ANTHROPIC_API_KEY=FAKE_KEY,
        EMBEDDING_PROVIDER="local",
        EMBEDDING_API_KEY="REPLACE_ME",
        **BASE,
    )
    settings = load_settings(env)
    assert settings.embedding_api_key is None


def test_repr_hides_secrets(tmp_path):
    env = write_env(
        tmp_path, ANTHROPIC_API_KEY=FAKE_KEY, LANGSMITH_API_KEY=FAKE_KEY, **BASE
    )
    text = repr(load_settings(env))
    assert FAKE_KEY not in text
    assert "rag:rag" not in text


def test_shell_variable_wins_over_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    env = write_env(tmp_path, ANTHROPIC_API_KEY="REPLACE_ME", **BASE)
    assert load_settings(env).anthropic_api_key == FAKE_KEY
