# 1주차 요약 (2026-10-25)

블로그 글 33편을 청크 261개로 나눠 bge-m3로 임베딩하고 Postgres(pgvector)에 적재했다. 그 위에 검색과 답변 세 버전(워크플로우 v0, SDK 직접 루프, LangGraph)을 만들어 질문 10개로 비교했고, "기본은 v0, 멀티홉 질문만 에이전트"로 결정했다.

## 한 일과 남긴 곳

| 단계 | 한 일 | 남긴 곳 |
| --- | --- | --- |
| API 공부 | pgvector, Anthropic tool use, LangGraph 문서 확인 | `notes/week1-api.md` |
| 결정 | 스키마·임베딩·청킹·인덱스·State·상한·툴 설명·프롬프트 | `notes/week1-decision-points.md`(선택지), `notes/decisions.md`(결정 + 판단 기록 2개) |
| 테스트 기반 | 테스트 전용 DB `rag_test`, 가짜 임베더, Makefile | `BE/tests/conftest.py`, `fakes.py`, `BE/Makefile` |
| 적재 | 마크다운 → 청크 → 임베딩 → posts·chunks | `BE/src/blog_rag_agent/ingest/chunking.py`, `load.py`, `embedding.py` |
| 검색 | `search(query, k)`, `get_post(post_id)`, HNSW 인덱스 | `BE/src/blog_rag_agent/retrieval/search.py`, README EXPLAIN 절 |
| 에이전트 3종 | v0 / raw_loop / LangGraph, 리듀서 깨뜨리기 스위치 | `workflow.py`, `experiments/week1/raw_loop.py`, `graph/research.py` |
| 비교 | 질문 10개(쉬움 3·중간 4·어려움 3)로 세 버전 비교 | `experiments/week1/questions.txt`, `compare.py`, `compare_answers.md`, README 표 |
| 흐름 | 적재·검색·세 버전·메시지 증가 방식 | `notes/flow.md` |
| 회고 | AI 실수 3건과 막을 방법 | `notes/harness-log.md` |
| 블로그 | 초심자용 1주차 글 초안 | `notes/blog-week1.md` |

## 정한 것

- 스키마: posts(url UNIQUE) + chunks(post_id FK, UNIQUE(post_id, chunk_index)). 본문 해시가 같으면 재임베딩 안 함.
- 임베딩: 로컬 BAAI/bge-m3, 1024차원(sentence-transformers). 비용 0, 대신 모델 약 2GB.
- 청킹: `##` 소제목 단위, 앞에 "글 제목 > 소제목", 이미지는 alt만, 200자 미만 합치고 1500자 초과 문단 경계에서 자름, 코드 블록은 자르지 않음.
- 인덱스: HNSW(vector_cosine_ops, 연산자 `<=>`).
- State: messages(add_messages) + llm_calls. 상한: raw_loop max_steps=6, LangGraph recursion_limit=10, 넘으면 실패로 멈춤.
- 에이전트 필요성: C(기본 v0, 멀티홉만 에이전트). 라우팅 방식은 미정.

## 숫자

| 항목 | 값 |
| --- | --- |
| 글 / 청크 | 33편 / 261개(평균 497자, 최소 233, 최대 1230) |
| 적재 시간 | 처음 3분 38초(모델 있음 기준), 다시 적재 22초(재임베딩 0번) |
| 검색 정확도 | 블로그에 답이 있는 단일 글 질문 8개: 정답 글 1위 8/8, 정답 소제목 1위 7/8 |
| 실행 계획 | 261행이라 기본은 Seq Scan(약 1.6ms), seqscan off에서 HNSW Index Scan(약 1.6ms) |
| 테스트 | 18개 통과 |

| 버전 | 평균 LLM 호출 | 평균 토큰 | 질문당 비용 | 평균 지연 | 원문과 맞은 답 |
| --- | --- | --- | --- | --- | --- |
| v0 | 1.0 | 3745 | $0.00056 | 2.7초 | 9/10 |
| raw_loop | 2.1 | 6551 | $0.00092 | 4.4초 | 10/10 |
| langgraph | 2.1 | 6962 | $0.00097 | 5.0초 | 10/10 |

비용은 claude-haiku-5-5 단가(입력 $0.10, 출력 $0.50 / 1M 토큰)로 Decimal 계산.

## 1주차 완료 기준

| # | 기준 | 결과 |
| --- | --- | --- |
| 1 | 빈 DB에서 db-reset·migrate·적재만으로 search 재현 | 부분 통과: 명령은 재현됨, 이 PC에 `make`가 없어 make로는 미실행 |
| 2 | 두 번 적재해도 행 수 그대로 | 통과 |
| 3 | search의 EXPLAIN ANALYZE가 README에 있다 | 통과 |
| 4 | 세 버전이 같은 질문에 답하고, README에 그림과 compare 표 | 통과 |
| 5 | decisions.md에 이번 주 결정 | 통과 |

## 알려진 한계와 다음 주

- 블로그에서 지운 글의 행은 DB에 남는다. 청킹 규칙만 바꾸면 해시가 같아 재청킹되지 않는다(db-reset 필요).
- 답이 블로그에 없을 때 "가장 덜 먼" 청크가 그대로 나온다. 거리로 걸러 내는 기준이 없다.
- 하네스 로그의 게이트 3개는 아직 제안 상태.
- 2주차: 평가(질문 확대, "맞았다" 기준, 자동 채점, 출처 오타·원문 밖 내용 잡기), 라우팅(규칙 vs LLM 분류) 결정.
