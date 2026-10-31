"""노드 실행을 JSONL 파일에 기록한다.

프로세스가 강제 종료돼도 남도록 시작과 끝을 각각 그 순간에 쓴다.
start만 있고 end가 없으면 그 노드가 도는 중에 죽었다는 뜻이다.
"""

import functools
import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from langgraph.config import get_config


def _write(path: Path, node: str, event: str, error: str | None = None) -> None:
    record = {
        "node": node,
        # 노드 시그니처를 바꾸지 않으려고 config를 인자가 아니라 실행 컨텍스트에서 읽는다.
        "thread_id": get_config()["configurable"].get("thread_id"),
        "event": event,
        "at": datetime.now(UTC).isoformat(),
        "error": error,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def traced(path: Path) -> Callable:
    """노드 함수를 감싸 시작과 끝을 path에 기록한다. 동기·비동기 노드 모두 된다."""

    def decorate(fn: Callable) -> Callable:
        name = fn.__name__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                _write(path, name, "start")
                error = None
                try:
                    return await fn(*args, **kwargs)
                # 타임아웃의 CancelledError와 interrupt도 기록되도록 BaseException으로 잡고 그대로 올린다.
                except BaseException as e:
                    error = type(e).__name__
                    raise
                finally:
                    _write(path, name, "end", error)

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _write(path, name, "start")
            error = None
            try:
                return fn(*args, **kwargs)
            except BaseException as e:
                error = type(e).__name__
                raise
            finally:
                _write(path, name, "end", error)

        return wrapper

    return decorate


def read_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # 쓰는 도중 죽었으면 마지막 줄이 잘려 있을 수 있어 완전한 줄만 읽는다.
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.endswith("}")]
