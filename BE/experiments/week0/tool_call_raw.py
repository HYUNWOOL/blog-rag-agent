"""Anthropic SDK로 tool_call.py와 같은 흐름을 직접 짠다.

요청 → tool_use 블록 → 툴 실행 → tool_result 블록 → 최종 답
실행: uv run python experiments/week0/tool_call_raw.py
"""

import json

import anthropic

from blog_rag_agent.config import load_settings

MODEL = "claude-haiku-5-5"  # 가장 저렴한 급

# LangChain의 @tool이 만들어 주던 스키마를 여기서는 직접 쓴다.
TOOLS = [
    {
        "name": "search_posts",
        "description": "블로그 글을 검색해 제목과 URL을 돌려준다.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
]


def search_posts(query: str) -> str:
    posts = [
        {
            "title": "LangGraph로 첫 에이전트 만들기",
            "url": "https://example.com/langgraph-1",
        },
        {
            "title": "LangGraph State와 리듀서 정리",
            "url": "https://example.com/langgraph-2",
        },
    ]
    return json.dumps(posts, ensure_ascii=False)


def as_plain(content):
    # SDK 블록 객체(pydantic)를 dict로 바꿔야 JSON으로 그대로 찍을 수 있다.
    if isinstance(content, str):
        return content
    return [
        b if isinstance(b, dict) else b.model_dump(exclude_none=True) for b in content
    ]


def show(step: str, messages: list) -> None:
    print(f"\n===== {step}: messages {len(messages)}개 =====")
    for i, m in enumerate(messages):
        print(f"[{i}] role={m['role']}")
        print(json.dumps(as_plain(m["content"]), ensure_ascii=False, indent=2))


def show_response(label: str, response) -> None:
    # 응답 원문에서 흐름을 결정하는 두 가지: stop_reason과 content 블록 목록.
    print(f"\n----- {label}: stop_reason={response.stop_reason} -----")
    print(json.dumps(as_plain(response.content), ensure_ascii=False, indent=2))


def main() -> None:
    settings = load_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    common = {
        "model": MODEL,
        "max_tokens": 1024,
        "output_config": {"effort": "low"},
        "tools": TOOLS,
    }

    messages = [{"role": "user", "content": "LangGraph 관련 글 찾아줘"}]
    show("1. 요청", messages)

    response = client.messages.create(messages=messages, **common)
    show_response("1차 응답", response)
    # 응답 content를 텍스트만 뽑지 말고 통째로 넣는다. tool_use 블록(과 thinking 블록)이 그대로 남아야 한다.
    messages.append({"role": "assistant", "content": response.content})
    show("2. assistant(tool_use) 추가", messages)

    if response.stop_reason == "tool_use":
        results = []
        for block in response.content:
            if block.type == "tool_use":
                results.append(
                    {
                        "type": "tool_result",
                        # 이 id로 어느 tool_use에 대한 결과인지 짝을 맞춘다.
                        "tool_use_id": block.id,
                        "content": search_posts(**block.input),
                    }
                )
        # SDK에는 tool 역할이 없다. 툴 결과는 user 메시지 안의 tool_result 블록으로 보낸다.
        messages.append({"role": "user", "content": results})
        show("3. user(tool_result) 추가", messages)

        response = client.messages.create(messages=messages, **common)
        show_response("2차 응답", response)
        messages.append({"role": "assistant", "content": response.content})
        show("4. 최종 답 추가", messages)

    print("\n----- 최종 답 -----")
    print("".join(b.text for b in response.content if b.type == "text"))


if __name__ == "__main__":
    main()
