# blog-rag-agent

- 누구의 어떤 문제:
- 성공 지표:
- 아키텍처: (그림)

  LangGraph 에이전트(`BE/src/blog_rag_agent/graph/research.py`), `python -m blog_rag_agent.graph.research --mermaid` 출력:

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
