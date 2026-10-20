"""LangChain으로 툴 호출 한 번의 흐름을 본다.

요청 → AIMessage.tool_calls → 툴 실행 → ToolMessage → 최종 답
실행: uv run python experiments/week0/tool_call.py
"""

import json

from langchain.messages import HumanMessage
from langchain.tools import tool
from langchain_anthropic import ChatAnthropic

from blog_rag_agent.config import load_settings

MODEL = "claude-haiku-5-5"  # 가장 저렴한 급


@tool
def search_posts(query: str) -> str:
    """블로그 글을 검색해 제목과 URL을 돌려준다."""
    # 외부 호출 없이 고정된 글 2개. 툴 결과는 문자열로 모델에 전달된다.
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


def show(step: str, messages: list) -> None:
    # 단계마다 메시지 목록 전체를 찍어서, 무엇이 하나씩 늘어나는지 본다.
    print(f"\n===== {step}: messages {len(messages)}개 =====")
    for i, m in enumerate(messages):
        print(f"[{i}] {m!r}")


def main() -> None:
    # 키는 config.py로만 읽는다. 비어 있으면 여기서 API 호출 전에 멈춘다.
    settings = load_settings()
    model = ChatAnthropic(
        model=MODEL,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,  # 작게. 툴 호출과 짧은 답에는 충분하다.
        effort="low",  # 생각을 짧게 해서 토큰을 아낀다.
    )
    # bind_tools: 툴의 이름·설명·인자 스키마를 요청에 실어 보낸다. 실행은 우리가 한다.
    model_with_tools = model.bind_tools([search_posts])

    messages = [HumanMessage("LangGraph 관련 글 찾아줘")]
    show("1. 요청", messages)

    # 1차 호출: 모델은 답 대신 "이 툴을 이 인자로 불러 달라"는 AIMessage를 돌려준다.
    ai_msg = model_with_tools.invoke(messages)
    messages.append(ai_msg)
    print("\n----- ai_msg.tool_calls -----")
    print(ai_msg.tool_calls)
    show("2. 모델 응답(tool_calls) 추가", messages)

    # 툴 실행: tool_call 딕셔너리를 통째로 넘기면 tool_call_id가 채워진 ToolMessage가 나온다.
    tools_by_name = {"search_posts": search_posts}
    for tool_call in ai_msg.tool_calls:
        tool_msg = tools_by_name[tool_call["name"]].invoke(tool_call)
        messages.append(tool_msg)
    show("3. ToolMessage 추가", messages)

    # 2차 호출: 요청 + 툴 호출 + 툴 결과를 모두 보내야 모델이 결과를 근거로 답한다.
    final = model_with_tools.invoke(messages)
    messages.append(final)
    show("4. 최종 답 추가", messages)
    print("\n----- 최종 답 -----")
    print(final.text)


if __name__ == "__main__":
    main()
