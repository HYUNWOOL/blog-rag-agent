"""세 버전(workflow v0, raw_loop, LangGraph)이 같이 쓰는 모델·프롬프트·툴.

문구는 1주차 결정(notes/decisions.md)대로다. 바꾸면 세 버전 비교가 같은 조건에서 다시 돌아야 한다.
"""

import json

import psycopg

from blog_rag_agent.retrieval.search import get_post, search

MODEL = "claude-haiku-5-5"  # week0과 같은 가장 저렴한 급
MAX_TOKENS = 1024
SEARCH_K = 5

SYSTEM_PROMPT = (
    "너는 thejoy-walking 여행 블로그의 글만 근거로 한국어로 답한다. "
    "근거가 없으면 블로그에 없다고 말한다. "
    "답 끝에 참고한 글의 제목과 URL을 적는다."
)

SEARCH_POSTS_DESC = (
    "블로그 글을 소제목 단위로 의미 검색해 가까운 청크 5개"
    "(post_id, 글 제목, url, 소제목, 본문, 거리)를 돌려준다. 질문에 답하려면 먼저 이걸로 찾는다."
)
GET_POST_DESC = (
    "search_posts에서 얻은 post_id로 글 전체 본문을 가져온다. "
    "청크만으로 답이 부족할 때만 쓴다."
)


def run_search_posts(conn: psycopg.Connection, embedder, query: str) -> str:
    hits = search(conn, embedder, query, SEARCH_K)
    # 모델에 보내는 툴 결과는 문자열이다. 거리는 소수 3자리면 순위를 읽기에 충분하다.
    return json.dumps(
        [
            {k: h[k] for k in ("post_id", "title", "url", "heading", "text")}
            | {"distance": round(float(h["distance"]), 3)}
            for h in hits
        ],
        ensure_ascii=False,
    )


def run_get_post(conn: psycopg.Connection, post_id: int) -> str:
    post = get_post(conn, post_id)
    if post is None:
        # 예외 대신 오류를 결과로 돌려줘야 모델이 다른 id로 다시 시도할 수 있다.
        return json.dumps({"error": f"post_id {post_id} 없음"}, ensure_ascii=False)
    # published_at 같은 datetime은 문자열로 바꿔 보낸다.
    return json.dumps(post, ensure_ascii=False, default=str)
