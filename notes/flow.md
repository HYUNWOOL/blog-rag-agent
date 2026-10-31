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

## 5. 재개: 무엇이 다시 실행되고, 왜 멱등이 필요한가

> 5~7절은 사용자 요청으로 AI가 2026-10-31 실제 실행 결과를 기준으로 썼다. 직접 쓴 설명이 아니다.

- 입력: 같은 `thread_id`로 `ainvoke(None, config)`. 입력이 None이면 새 질문이 아니라 이어 가기다.
- 거치는 순서:
  1. 체크포인터가 그 thread의 마지막 체크포인트를 읽는다. 체크포인트는 노드 묶음(super-step)이 끝날 때 저장된다.
  2. 체크포인트의 `next`에 적힌 노드부터 함수 처음부터 다시 돈다. 노드 안의 어디까지 갔는지는 저장되지 않는다.
  3. 그 뒤로는 보통 실행처럼 끝까지 간다.
- 무엇이 다시 도나(실측, durability=async):

  | 죽은 곳 | 죽은 뒤 `next` | 재개 때 처음 도는 노드 | 다시 돌지 않은 것 |
  | --- | --- | --- | --- |
  | `grade` 시작 0.3초 뒤 | `grade` | `grade` | `begin_turn`, `retrieve` |
  | `log_question`이 DB에 쓴 뒤 | `log_question` | `log_question` | 그 앞 노드 전부(LLM 재호출 없음) |
  | `retrieve` 시작 0.05초 뒤 | `__start__` | `begin_turn` | 없음 |

- 마지막 줄의 이유: async는 저장을 기다리지 않고 다음 노드로 넘어간다. `begin_turn`은 끝났지만 그 체크포인트가 저장되기 전에 죽어서 다시 돌았다. 그래서 정확한 규칙은 "끝난 노드"가 아니라 "저장이 끝난 노드는 다시 돌지 않는다"이다.
- 왜 멱등이 필요한가:
  1. State 변경은 체크포인트와 함께 저장되거나 함께 사라진다. 그래서 다시 돌아도 값이 어긋나지 않는다. `begin_turn`이 다시 돌아도 `turn`이 2번 늘지 않는 것도 이전 값이 저장되지 않았기 때문이다.
  2. `question_logs` 쓰기는 체크포인트 밖에서 일어난다. "DB에 쓴 뒤, 체크포인트 저장 전"에 죽으면 DB에는 행이 있는데 체크포인트는 그 노드가 안 끝났다고 기억한다.
  3. 재개하면 그 노드가 다시 돌아 같은 쓰기를 한 번 더 한다. 노드 재시도(RetryPolicy)도 같은 일을 일으킬 수 있다.
  4. 그래서 몇 번 돌아도 결과가 같게 만든다. `(thread_id, turn)`을 키로 upsert하고, `turn`은 State에서 읽으므로 재개 때도 같은 값이다.
- 바뀌는 것(State·DB) 실측:

  | 죽은 곳 | 멱등 켬 행 수 | 멱등 끔 행 수 |
  | --- | --- | --- |
  | `retrieve` | 1 | 1 |
  | `grade` | 1 | 1 |
  | `log_question` | 1 | 2 |

  `retrieve`와 `grade`에서는 아직 로그를 쓰기 전에 죽었으므로 켜고 끔의 차이가 없다.
- 실패하면: `durability="exit"`는 실행 중 체크포인트를 저장하지 않아 `next=()`이고 재개가 `EmptyInputError`로 실패했다(1차 대역 그래프 실험).
- 헷갈리기 쉬운 점:
  - 멱등은 "다시 안 돈다"가 아니라 "다시 돌아도 결과가 같다"이다. 노드는 실제로 다시 돈다.
  - LLM 호출은 멱등이 아니다. 죽은 `grade` 호출은 끝나지 않아 `llm_calls`에 없지만 비용은 청구될 수 있다. 다시 부르면 판정이 달라질 수도 있다(같은 질문이 `retrieve` kill에서 한 번은 insufficient, 한 번은 answer로 끝났다).
  - `log_question` 멈춤은 실험 스크립트가 일부러 만든 30초다. 실제로는 아주 짧은 구간이라 kill로 맞히기 어렵다.

## 6. Agentic RAG: 질문 하나가 노드를 지나는 순서
- 입력: `{"question": 질문}`과 `thread_id`. 같은 `thread_id`면 대화가 이어진다.
- 거치는 순서(`graph/agentic.py`):
  1. `begin_turn`: `turn`을 1 올리고 지난 턴의 값을 비운다. `chunks`는 reducer가 합치므로 `Overwrite([])`로 비운다.
  2. 대화 기록이 있으면 `rewrite_query`가 "거기 요금은?"을 독립 검색어로 바꾼다. 첫 턴은 질문 그대로 `retrieve`로 간다.
  3. `retrieve`: `search`로 청크 5개를 찾아 `chunks`에 합친다.
  4. `grade`: 구조화 출력으로 `{sufficient, missing}`을 판정한다.
  5. 충분하면 `answer`, 부족하고 재검색이 2번 미만이면 `rewrite_query` 후 다시 `retrieve`, 2번을 다 썼으면 `insufficient`.
  6. `answer`는 `{answer, source_post_ids}`를 구조화 출력으로 받고, 코드가 이번 턴에 검색된 글 id만 남긴다.
  7. `log_question`: `question_logs`에 upsert하고 `history`에 질문과 답을 붙인다.
- 바뀌는 것(State·DB) 실측:

  | 턴 | 경로 | 검색어 | LLM | 근거 글 id |
  | --- | --- | --- | --- | --- |
  | 1 "트롬쇠 오로라 투어 첫날에 오로라를 못 본 이유가 뭐야?" | begin_turn → retrieve → grade → answer → log_question | 질문 그대로 | 2 | [29] |
  | 2 "그럼 둘째 날은 어땠어?" | begin_turn → rewrite_query → retrieve → grade → answer → log_question | `트롬쇠 오로라 둘째 날 검색어` | 3 | [29] |

  같은 thread에 체크포인트 15개, `question_logs`는 턴마다 1행(2행)이었다.
- 재검색 예(튀르키예 질문): retrieve → grade → rewrite_query → retrieve → grade → answer, LLM 4번, 근거 글 [14, 32].
- 헷갈리기 쉬운 점:
  - `attempts`는 재검색 횟수다. 후속 턴의 첫 `rewrite_query`는 세지 않는다.
  - `llm_calls`는 턴마다 0부터 다시 센다. `history`만 턴을 넘어 남고, 프롬프트에는 최근 3턴만 넣는다.
  - 튀르키예 질문은 재검색이 돌아도 5개 도시를 다 찾지 못한다. 3주차 평가로 넘겼다.

## 7. 실패 경로: 재시도, error_handler, durability
- 일시적 장애(`is_transient`)는 노드 안에서 최대 3번 시도한다. 타임아웃은 `retrieve` 30초, LLM 노드 60초다. `NodeTimeoutError`는 내장 `TimeoutError`의 하위 클래스가 아니라서 따로 넣었다.
- `retrieve`가 재시도를 다 쓰면 `on_retrieve_failure`가 불린다.
  - 일시적 장애: `verdict.missing`에 검색 오류를 적고 `Command(goto="insufficient")` → `log_question`. `status`는 insufficient다.
  - 코드 버그(`ValueError` 등): 숨기지 않고 그대로 올린다. 로그는 남지 않는다.
- LLM 노드에는 `error_handler`가 없다. 재시도 뒤 실패로 끝나고, 체크포인트가 남아 재개할 수 있다.
- durability:

  | 모드 | 저장 시점 | 실측 |
  | --- | --- | --- |
  | `sync` | 다음 단계 전에 저장 완료 | `retrieve`에서 kill: `next=('retrieve',)` (대역 그래프) |
  | `async`(기본) | 백그라운드 저장, 다음 단계와 동시 진행 | 같은 kill에서 같은 결과. 시작 0.05초 뒤 kill은 `next=('__start__',)` |
  | `exit` | 실행이 끝날 때만 저장 | `next=()`, 재개 시 `EmptyInputError` (대역 그래프) |

- 확인 범위: 검색 장애와 타임아웃은 가짜 검색·가짜 모델 테스트로만 확인했다. 실제 DB 장애를 일으켜 보지는 않았다.
