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
