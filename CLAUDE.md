# blog-rag-agent

11월 학습 프로젝트. 블로그 글 수집부터 Postgres(pgvector) 검색, Agentic RAG, 웹 서버, 평가까지 처음부터 만든다.

## 문서 기준
- LangGraph·LangChain API는 docs-langchain, reference-langchain MCP 서버로 현재 문서를 확인한 뒤에 쓴다. 기억에 기대 import 경로나 인자 이름을 쓰지 않는다.
- 쓰지 않는 구버전 API: create_react_agent, langchain-mcp-adapters, MultiServerMCPClient

## 역할 분담
- 코드는 네가 짠다. 스키마, 그래프, 툴, 테스트, 스크립트 전부.
- 결정 포인트(DB 스키마와 인덱스, State 필드, 그래프 구조, 평가 기준, LLM 프롬프트, 라이브러리 선택)에서는 코드를 짜기 전에 멈추고, 선택지 2~3개와 트레이드오프, 추천안을 보여준 뒤 내 선택을 기다린다. 내 선택은 notes/decisions.md에 한 줄로 남긴다.
- 구현이 끝나면 흐름을 설명한다: 요청 하나가 어떤 함수와 노드를 어떤 순서로 지나는지, 그사이 State와 DB가 어떻게 바뀌는지. mermaid 그림 하나와 실제 실행 로그 한 번으로 보여준다.
- 내가 notes/flow.md에 흐름을 내 말로 적으면, 고쳐 쓰지 말고 틀리거나 빠진 곳을 질문으로 짚는다.
- 내가 흐름을 설명하지 못하면 다음 단계로 넘어가지 않는다.

## DB 규칙
- DB 접근은 psycopg로 SQL을 직접 쓴다. LangChain 벡터스토어 래퍼는 쓰지 않는다.
- 스키마 변경은 Alembic 마이그레이션으로만 한다. DDL을 손으로 실행하지 않는다.
- 예외: LangGraph 체크포인터 테이블은 라이브러리의 `setup()`이 관리한다(`make checkpoints`).
- 적재는 몇 번을 다시 돌려도 결과가 같아야 한다.

## 코드 규칙
- pyproject의 버전 상한을 지킨다. 올려야 하면 먼저 묻는다.
- 시크릿은 .env에만 두고 커밋하지 않는다. 로그에도 남기지 않는다.
- .env 내용을 읽거나 출력하지 않는다. 키가 필요하면 config.py 검사 결과만 본다
- 비용 계산은 Decimal로 한다.
- LLM을 부르는 실험에는 recursion_limit이나 step 상한을 반드시 건다. 기본 recursion_limit은 1000이다.
- 내가 네 실수를 지적하면, 무엇이 틀렸고 어떤 규칙이나 테스트로 막을지 notes/harness-log.md에 넣을 한 줄을 제안한다.
