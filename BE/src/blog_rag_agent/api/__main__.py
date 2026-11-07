"""uv run python -m blog_rag_agent.api [--port 8000]"""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(
        "blog_rag_agent.api.app:app_from_env",
        factory=True,
        host=args.host,
        port=args.port,
        # 사용자 지정 문자열은 루프 팩토리 자체로 쓰인다. psycopg 비동기는 Windows ProactorEventLoop에서 못 돈다.
        loop="asyncio:SelectorEventLoop",
    )


if __name__ == "__main__":
    main()
