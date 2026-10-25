# 흐름 노트

> 1주차 흐름을 AI가 실제 실행 로그 기준으로 정리한 초안(2026-10-25). 내 말로 다시 쓰면서 틀린 곳을 고친다.

## 1. 적재: 마크다운 파일 하나가 행이 되기까지
- 입력: `BE/data/posts/<slug>.md` 하나(앞부분 url·title·published_at·updated_at·tags + 본문 마크다운).
- 거치는 순서:
  1. `ingest/load.py: load_dir`가 파일을 이름순으로 하나씩 넘긴다.
  2. `parse_post_file`이 앞부분을 읽고 본문 sha256(`content_hash`)을 다시 계산한다.
  3. `load_post`가 `SELECT content_hash FROM posts WHERE url = ?`로 이전 해시와 비교한다.
  4. 같으면 posts 메타데이터만 upsert하고 끝(`unchanged`).
  5. 다르거나 새 글이면 `ingest/chunking.py: chunk_post`로 `##` 소제목 단위 청크를 만들고, `LocalEmbedder.embed`(bge-m3, 1024차원)로 벡터를 만든다. 임베딩은 트랜잭션 밖.
  6. 트랜잭션 하나 안에서 posts upsert(`RETURNING id`) → 그 글의 chunks DELETE → 새 chunks INSERT. 커밋(`embedded`).
- 바뀌는 것(State·DB): `posts` 1행(url 기준 upsert), `chunks` N행(글마다 통째로 교체). 실측: 33편 → posts 33행, chunks 261행(평균 497자). 1회차 `embedded 33`(3분 38초), 2회차 `unchanged 33`(22초, 임베딩 0번).
- 실패하면: 6번 안에서 예외가 나면 DELETE와 해시 변경까지 함께 롤백된다. 이전 chunks와 이전 해시가 남으므로 다음 실행이 다시 시도한다(`test_failed_replace_keeps_previous_chunks`). `load_dir`은 실패한 글을 목록에 남기고 다음 글로 넘어간다.
- 헷갈리기 쉬운 점:
  - 연결이 autocommit이 아니면 `conn.transaction()`은 BEGIN이 아니라 SAVEPOINT가 되어, 블록이 끝나도 커밋되지 않는다. 그래서 `load_post`가 autocommit을 assert한다.
  - 해시는 본문 기준이라, 청킹 규칙만 바꾸면 다시 청킹되지 않는다(db-reset 후 재적재 필요).
  - 블로그에서 지운 글의 행은 남는다(아직 처리 안 함).

## 2. 검색: 질문 하나가 결과가 되기까지
- 입력: 질문 문자열, k(기본 5).
- 거치는 순서:
  1. `retrieval/search.py: search`가 `embedder.embed([질문])`으로 1024차원 단위 벡터를 만든다.
  2. numpy float32로 바꾸면 `register_vector`가 `vector` 타입으로 보낸다.
  3. SQL: CTE에서 chunks를 `ORDER BY embedding <=> q LIMIT k`로 top-k를 먼저 뽑고, 그다음 posts와 JOIN해 제목·URL을 붙인다.
  4. dict 목록(chunk_id, post_id, title, url, heading, text, distance)을 돌려준다. distance는 코사인 거리(0에 가까울수록 비슷).
- 바뀌는 것(State·DB): 없음(읽기만).
- 실패하면: DB 연결 오류는 psycopg 예외로 올라간다. 결과가 없어도 빈 목록이다. 답이 블로그에 없으면 "가장 덜 먼" 청크가 그대로 나온다(파리 질문 1위 거리 0.492) — 걸러 내는 기준은 아직 없다.
- 헷갈리기 쉬운 점:
  - 261행에서는 플래너가 HNSW 대신 Seq Scan을 고른다(추정 비용 약 43 vs HNSW 시작 비용 약 1050). 인덱스가 있어도 안 쓰는 게 정상이다.
  - 처음 쓴 "JOIN 뒤 ORDER BY … LIMIT"는 seqscan을 꺼도 HNSW를 못 탔다. top-k를 chunks에서 먼저 뽑아야 한다(README EXPLAIN 절).
  - 인덱스 opclass(`vector_cosine_ops`)와 연산자(`<=>`)가 짝이 맞아야 한다.

## 3. 세 버전: 다음에 할 일을 누가 정하나
- 입력: 같은 질문 하나. 세 버전 모두 같은 시스템 프롬프트·툴 설명·모델(`agent_tools.py`, claude-haiku-5-5, effort low).
- 거치는 순서:
  - v0 (`workflow.py: answer_v0`): 코드가 `search(질문, 5)` → 결과를 프롬프트에 붙여 LLM 1번 → 답. 검색어도 질문 그대로.
  - raw_loop (`experiments/week1/raw_loop.py: run_raw`): LLM 호출 → `stop_reason == "tool_use"`면 코드가 툴 실행 → tool_result를 user 메시지로 붙여 다시 호출 → `end_turn`이면 끝. 검색어·툴 선택·종료를 LLM이 정한다(예: 질문을 '스위스 배 탑승 이유'로 바꿔 검색).
  - langgraph (`graph/research.py`): agent 노드(LLM) → `should_continue`가 마지막 메시지의 tool_calls를 보고 tools 노드 또는 END로 보냄 → tools 노드가 ToolMessage를 돌려주고 다시 agent. 판단은 raw_loop와 같고, 루프 제어를 코드 대신 그래프 엣지가 한다.
- 바뀌는 것(State·DB): DB는 읽기만. 대화 기록은 아래 4번.
- 실패하면: v0는 검색 1번이 놓친 정보를 되찾을 길이 없다(9번 튀르키예 순서에 일부만 답함). raw_loop는 6번째 호출 뒤에도 끝나지 않으면 RuntimeError, langgraph는 10 super-step을 넘으면 GraphRecursionError로 멈춘다(답 없음).
- 실측(questions.txt 10개): v0 호출 1.0회·3745토큰·2.7초, raw_loop 2.1회·6551토큰·4.4초, langgraph 2.1회·6962토큰·5.0초. 에이전트가 검색을 더 한 건 9번 하나뿐(호출 3회).

## 4. raw_loop의 messages와 LangGraph State가 늘어나는 방식
- 입력: "스위스에서 배를 탄 이유가 뭐야?"
- 거치는 순서와 길이(실제 로그):

  | 시점 | raw_loop `messages` | LangGraph State `messages` |
  | --- | --- | --- |
  | 시작 | `[user]` = 1 | `[Human]` = 1, llm_calls 0 |
  | 1차 호출 뒤 | + assistant(tool_use) = 2 (in 676, out 59) | + AIMessage(tool_calls) = 2, llm_calls 1 |
  | 툴 실행 뒤 | + user(tool_result) = 3 | + ToolMessage = 3 |
  | 2차 호출 뒤 | + assistant(text) = 4 (in 4754, out 588) | + AIMessage = 4, llm_calls 2 |

- 바뀌는 것(State·DB): raw_loop는 리스트에 직접 append, LangGraph는 노드가 새 메시지만 돌려주고 `add_messages` 리듀서가 기존 목록 뒤에 붙인다. 시스템 프롬프트는 둘 다 목록에 넣지 않고 호출마다 따로 붙인다.
- 실패하면(리듀서를 뺐을 때, `RESEARCH_NO_REDUCER=1`): 노드가 돌려준 목록이 State를 통째로 덮어써 `[Human]` → `[AIMessage]` → `[ToolMessage]`가 된다. 2차 호출에 `[System, ToolMessage]`만 가서 API가 400(`tool_result`에 짝이 되는 `tool_use`가 없음)으로 거절한다.
- 헷갈리기 쉬운 점:
  - SDK에는 tool 역할이 없다. 툴 결과는 user 메시지 안의 tool_result 블록이고, LangChain의 ToolMessage가 보낼 때 그 모양으로 바뀐다.
  - tool_use와 tool_result는 `id`/`tool_use_id`(LangChain은 `tool_call_id`)로 짝을 맞춘다.
  - 2차 호출 입력 토큰이 크게 느는 건 전체 기록과 검색 결과 5개를 다시 보내기 때문이다.
