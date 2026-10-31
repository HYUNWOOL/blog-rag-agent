# blog-rag-agent

- 누구의 어떤 문제:
- 성공 지표:
- 아키텍처: (그림)

  Agentic RAG 그래프(`BE/src/blog_rag_agent/graph/agentic.py`), `draw_mermaid()` 출력:

  ```mermaid
  ---
  config:
    flowchart:
      curve: linear
  ---
  graph TD;
  	__start__(<p>__start__</p>)
  	begin_turn(begin_turn)
  	__error_handler__retrieve(__error_handler__retrieve)
  	retrieve(retrieve)
  	grade(grade)
  	rewrite_query(rewrite_query)
  	answer(answer)
  	insufficient(insufficient)
  	log_question(log_question)
  	__end__(<p>__end__</p>)
  	__start__ --> begin_turn;
  	answer --> log_question;
  	begin_turn -.-> retrieve;
  	begin_turn -.-> rewrite_query;
  	grade -.-> answer;
  	grade -.-> insufficient;
  	grade -.-> rewrite_query;
  	insufficient --> log_question;
  	retrieve --> grade;
  	rewrite_query --> retrieve;
  	log_question --> __end__;
  	classDef default fill:#f2f0ff,line-height:1.2
  	classDef first fill-opacity:0
  	classDef last fill:#bfb6fc
  ```

  1주차 LangGraph 에이전트(`BE/src/blog_rag_agent/graph/research.py`), `python -m blog_rag_agent.graph.research --mermaid` 출력:

  ```mermaid
  ---
  config:
    flowchart:
      curve: linear
  ---
  graph TD;
  	__start__([<p>__start__</p>]):::first
  	agent(agent)
  	tools(tools)
  	__end__([<p>__end__</p>]):::last
  	__start__ --> agent;
  	agent -.-> __end__;
  	agent -.-> tools;
  	tools --> agent;
  	classDef default fill:#f2f0ff,line-height:1.2
  	classDef first fill-opacity:0
  	classDef last fill:#bfb6fc
  ```

- 요청당 비용·지연:
- 주요 결정과 이유:
- 한계와 다음 단계:

## 세 버전 비교 (compare.py)

`BE/experiments/week1/questions.txt`(쉬움 3, 중간 4, 어려움 3)를 2026-10-25에 세 버전으로 돌린 결과. 모델 `claude-haiku-5-5`, effort low, search k=5. 재현: `uv run python experiments/week1/compare.py`. 답변 원문은 `BE/experiments/week1/compare_answers.md`.

| 버전 | 평균 LLM 호출 | 평균 토큰(입력+출력) | 평균 지연(초) | 코드 줄 수 | 실패 |
| --- | --- | --- | --- | --- | --- |
| v0 workflow | 1.0 | 3745 | 2.7 | 25 | 0 |
| raw_loop | 2.1 | 6551 | 4.4 | 48 | 0 |
| langgraph | 2.1 | 6962 | 5.0 | 45 | 0 |

- 코드 줄 수는 각 버전의 핵심 함수만 센 값이다(공통 프롬프트·툴 `agent_tools.py`는 제외).
- 에이전트 두 버전은 대부분 질문에서 검색 1번 + 답 1번(호출 2회)이었고, 여러 글을 이어야 하는 9번(튀르키예 이동 순서)에서만 검색을 더 해 호출 3회가 됐다. v0는 그 질문에 일부 구간만 답했다.

## 재개

`BE/experiments/week2/kill_resume.py`로 2026-10-31에 실행한 결과. 진짜 그래프, 개발 DB, `claude-haiku-5-5`, durability=async, 같은 질문("튀르키예를 어떤 순서로 이동했어?"), 조건마다 1번. `log_question`은 DB에 쓴 뒤 30초 멈추게 하고 1초 뒤 죽였다. 멱등 끔은 재실행마다 다른 키로 쓰게 했다.

재현:

```
uv run python experiments/week2/kill_resume.py --node retrieve --after 0.05
uv run python experiments/week2/kill_resume.py --node grade --after 0.3
uv run python experiments/week2/kill_resume.py --node log_question --after 1 --pause 30
uv run python experiments/week2/kill_resume.py --node log_question --after 1 --pause 30 --no-idempotent
```

| 죽인 노드 | 멱등 | 죽은 뒤 `next` | 재개 때 처음 실행된 노드 | 끝난 노드 | 최종 llm_calls | question_logs 행 수 |
| --- | --- | --- | --- | --- | --- | --- |
| retrieve | 켬 | `__start__` | begin_turn | insufficient | 5 | 1 |
| retrieve | 끔 | `__start__` | begin_turn | answer | 4 | 1 |
| grade | 켬 | `grade` | grade | answer | 4 | 1 |
| grade | 끔 | `grade` | grade | answer | 4 | 1 |
| log_question | 켬 | `log_question` | log_question | answer | 4 | 1 |
| log_question | 끔 | `log_question` | log_question | insufficient | 5 | 2 |

retrieve, 멱등 켬:

```
kill: retrieve 시작 0.05초 뒤, durability=async
죽은 뒤 get_state().next: ('__start__',)

죽기 전                       재개 뒤
begin_turn 완료              begin_turn 완료
retrieve 시작만 (kill)        retrieve 완료
                           grade 완료
                           rewrite_query 완료
                           retrieve 완료
                           grade 완료
                           rewrite_query 완료
                           retrieve 완료
                           grade 완료
                           insufficient 완료
                           log_question 완료

재개 종료 코드: 0
최종 llm_calls: 5
question_logs 행 수: 1 [('insufficient', 2, 5)]
```

grade, 멱등 켬:

```
kill: grade 시작 0.3초 뒤, durability=async
죽은 뒤 get_state().next: ('grade',)

죽기 전                    재개 뒤
begin_turn 완료           grade 완료
retrieve 완료             rewrite_query 완료
grade 시작만 (kill)        retrieve 완료
                        grade 완료
                        answer 완료
                        log_question 완료

재개 종료 코드: 0
최종 llm_calls: 4
question_logs 행 수: 1 [('answered', 1, 4)]
```

log_question, 멱등 켬:

```
kill: log_question 시작 1.0초 뒤, durability=async
죽은 뒤 get_state().next: ('log_question',)

죽기 전                           재개 뒤
begin_turn 완료                  log_question 완료
retrieve 완료
grade 완료
rewrite_query 완료
retrieve 완료
grade 완료
answer 완료
log_question 시작만 (kill)

재개 종료 코드: 0
최종 llm_calls: 4
question_logs 행 수: 1 [('answered', 1, 4)]
```

log_question, 멱등 끔:

```
kill: log_question 시작 1.0초 뒤, durability=async
죽은 뒤 get_state().next: ('log_question',)

죽기 전                           재개 뒤
begin_turn 완료                  log_question 완료
retrieve 완료
grade 완료
rewrite_query 완료
retrieve 완료
grade 완료
rewrite_query 완료
retrieve 완료
grade 완료
insufficient 완료
log_question 시작만 (kill)

재개 종료 코드: 0
최종 llm_calls: 5
question_logs 행 수: 2 [('insufficient', 2, 5), ('insufficient', 2, 5)]
```

## 검색 실행 계획 (EXPLAIN ANALYZE)

`search()`(`BE/src/blog_rag_agent/retrieval/search.py`)의 SQL을 2026-10-25에 실행한 결과. 재현: `uv run python experiments/week1/explain_search.py`. 질문 "스위스에서 기차 탄 이야기", chunks 261행, 1024차원 벡터는 `<q>`로 줄였다.

**기본 설정: HNSW를 타지 않는다(Seq Scan + top-N heapsort).**

```
Sort  (cost=50.11..50.12 rows=5 width=1335) (actual time=1.630..1.632 rows=5.00 loops=1)
  Sort Key: ((chunks.embedding <=> <q>))
  ->  Hash Join  (cost=47.38..50.05 rows=5 width=1335) (actual time=1.601..1.606 rows=5.00 loops=1)
        Hash Cond: (p.id = chunks.post_id)
        ->  Seq Scan on posts p  (cost=0.00..2.33 rows=33 width=170) (actual time=0.004..0.006 rows=33.00 loops=1)
        ->  Hash  (cost=47.32..47.32 rows=5 width=1173) (actual time=1.579..1.579 rows=5.00 loops=1)
              ->  Limit  (cost=47.31..47.32 rows=5 width=1173) (actual time=1.570..1.571 rows=5.00 loops=1)
                    ->  Sort  (cost=47.31..47.93 rows=251 width=1173) (actual time=1.570..1.570 rows=5.00 loops=1)
                          Sort Key: ((chunks.embedding <=> <q>))
                          Sort Method: top-N heapsort  Memory: 39kB
                          ->  Seq Scan on chunks  (cost=0.00..43.14 rows=251 width=1173) (actual time=0.058..1.464 rows=261.00 loops=1)
Execution Time: 1.681 ms
```

**`SET LOCAL enable_seqscan = off`: HNSW 인덱스를 탄다.**

```
Nested Loop  (cost=1050.03..1059.30 rows=5 width=1335) (actual time=1.554..1.585 rows=5.00 loops=1)
  ->  Limit  (cost=1049.88..1053.13 rows=5 width=1173) (actual time=1.545..1.566 rows=5.00 loops=1)
        ->  Index Scan using chunks_embedding_hnsw on chunks  (cost=1049.88..1213.02 rows=251 width=1173) (actual time=1.544..1.565 rows=5.00 loops=1)
              Order By: (embedding <=> <q>)
  ->  Memoize  (cost=0.15..3.37 rows=1 width=170) (actual time=0.003..0.003 rows=1.00 loops=5)
        ->  Index Scan using posts_pkey on posts p  (cost=0.14..3.36 rows=1 width=170) (actual time=0.001..0.001 rows=1.00 loops=4)
              Index Cond: (id = chunks.post_id)
Execution Time: 1.602 ms
```

- 기본 설정에서 안 타는 이유: 261행 전체 스캔의 추정 비용(약 43)이 HNSW 스캔의 시작 비용 추정(약 1050)보다 훨씬 작아서 플래너가 Seq Scan을 고른다. 실제 시간도 둘 다 약 1.6ms로 차이가 없다. 행이 훨씬 많아지면 자동으로 HNSW를 고를 것이다(그 경계 행 수는 측정하지 않았다).
- 인덱스를 탈 수 있는 SQL 모양: chunks에서 `ORDER BY embedding <=> q LIMIT k`로 top-k를 먼저 뽑고 posts와 JOIN한다. 처음 쓴 "JOIN 뒤 ORDER BY … LIMIT" 형태는 seqscan을 꺼도 HNSW를 쓰지 못했다(notes/harness-log.md 2026-10-25).
