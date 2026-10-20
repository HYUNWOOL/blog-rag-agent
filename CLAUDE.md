# blog-rag-agent

11월 학습 프로젝트. 블로그 글 수집부터 Postgres(pgvector) 검색, Agentic RAG, 웹 서버, 평가까지 처음부터 만든다.

## 문서 기준
- LangGraph·LangChain API는 docs-langchain, reference-langchain MCP 서버로 현재 문서를 확인한 뒤에 쓴다. 기억에 기대 import 경로나 인자 이름을 쓰지 않는다.
- 쓰지 않는 구버전 API: create_react_agent, langchain-mcp-adapters, MultiServerMCPClient

## 역할 분담
- DB 스키마와 인덱스, State 설계, 그래프 구조, 평가 기준, 프롬프트는 내가 직접 쓴다. 이 부분은 선택지와 트레이드오프만 제안하고 바로 코드로 만들지 않는다.
- 보일러플레이트, 테스트 데이터, 리팩터링, 문서 정리는 맡겨도 된다.
- 내가 설명하지 못하는 코드는 커밋하지 않는다. 새로 쓴 코드는 핵심 줄마다 왜 그렇게 했는지 짧게 설명한다.

## DB 규칙
- DB 접근은 psycopg로 SQL을 직접 쓴다. LangChain 벡터스토어 래퍼는 쓰지 않는다.
- 스키마 변경은 Alembic 마이그레이션으로만 한다. DDL을 손으로 실행하지 않는다.
- 적재는 몇 번을 다시 돌려도 결과가 같아야 한다.

## 코드 규칙
- pyproject의 버전 상한을 지킨다. 올려야 하면 먼저 묻는다.
- 시크릿은 .env에만 두고 커밋하지 않는다. 로그에도 남기지 않는다.
- .env 내용을 읽거나 출력하지 않는다. 키가 필요하면 config.py 검사 결과만 본다
- 비용 계산은 Decimal로 한다.
- LLM을 부르는 실험에는 recursion_limit이나 step 상한을 반드시 건다. 기본 recursion_limit은 1000이다.
- 내가 네 실수를 지적하면, 무엇이 틀렸고 어떤 규칙이나 테스트로 막을지 notes/harness-log.md에 넣을 한 줄을 제안한다.
