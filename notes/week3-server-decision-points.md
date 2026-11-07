# 3주차 웹 서버 결정 포인트 (미결정)

정하면 `notes/decisions.md`에 남긴다. 요청: access_codes·usage_log 테이블, `/api/session`, `/api/chat`(SSE), `/healthz`, static/index.html, tests/test_api.py. 그래프 코드(`graph/agentic.py`)는 바꾸지 않는다.

이미 설치된 것: fastapi 0.146(`fastapi.sse` 있음), starlette 1.9, uvicorn 0.54, psycopg_pool 3.3, httpx. 새 의존성 없이 갈 수 있는 쪽을 추천한다.

## 1. access_codes 스키마와 코드 해시

공통 컬럼: `id bigint identity PK`, `code_hash bytea UNIQUE NOT NULL`, `company text NOT NULL`, `expires_at timestamptz NOT NULL`, `daily_question_limit int NOT NULL CHECK (> 0)`, `created_at timestamptz DEFAULT now()`.

해시 방법:

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. SHA-256 | 표준 라이브러리, 해시로 바로 조회(UNIQUE 인덱스) | DB가 새면 짧은 코드는 사전 대입으로 풀린다 |
| B. HMAC-SHA256 + 서버 비밀값(`ACCESS_CODE_PEPPER`, .env) | A처럼 바로 조회. DB만 새면 비밀값 없이는 대입 불가 | .env에 비밀값이 하나 는다. 비밀값을 잃으면 코드를 다시 발급 |
| C. argon2/bcrypt | 비밀번호 저장 표준 | 새 의존성. 솔트 때문에 해시로 조회가 안 돼 모든 행과 비교해야 함 |

상수 시간 비교: 입력을 해시해 `code_hash`로 행을 찾고, 찾은 해시와 다시 `hmac.compare_digest`로 비교한다. 행이 없을 때도 같은 비교를 한 번 해서 응답 시간 차이를 줄인다. 코드는 발급 스크립트가 `secrets.token_urlsafe`로 만들고 한 번만 출력한다.

한도 값: 코드마다 `daily_question_limit`을 두고, 발급 때 값을 안 주면 환경 변수 `DAILY_QUESTION_LIMIT`을 기본값으로 쓴다.

추천: **B**.

## 2. usage_log 스키마와 하루 한도 세기

| 선택지 | 컬럼 | 한도 세는 법 | 장점 | 단점 |
| --- | --- | --- | --- | --- |
| A. 끝나고 한 줄 | id, code_id FK, created_at, input_tokens, output_tokens, cost_usd numeric(12,6) | 시작 전에 오늘 행 수를 세고, 끝나면 INSERT | 가장 단순 | 동시에 두 요청이 오면 둘 다 통과해 한도를 넘는다. 도중에 죽으면 기록이 없다(비용은 이미 씀) |
| B. 시작할 때 예약 | A + thread_id, turn, status(started/done/failed), finished_at | 한 트랜잭션에서 `access_codes` 행을 `FOR UPDATE`로 잠그고, 오늘 행 수를 센 뒤 started 행을 넣는다. 끝나면 같은 행에 토큰·비용·status를 UPDATE | 동시 요청에도 한도가 정확함. 실패한 요청도 한 번으로 셈. thread_id·turn으로 question_logs와 이어 볼 수 있음 | 컬럼과 상태가 늘어남 |
| C. 카운터 테이블 | (code_id, day) PK + count | upsert로 +1 | 세기가 가장 빠름 | 테이블이 하나 더 생기고 usage_log와 숫자가 어긋날 수 있다 |

하루 경계: `Asia/Seoul` 자정 기준(UTC 자정은 한국 오전 9시라 사용자가 헷갈린다). 인덱스: `(code_id, created_at)`.

추천: **B**.

## 3. 세션 저장

쿠키는 공통으로 HttpOnly, Secure, SameSite=Lax, Max-Age 2시간. 세션마다 thread_id(uuid4) 하나를 묶는다.

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 서명 쿠키(표준 라이브러리 hmac, `SESSION_SECRET`) | 테이블·의존성 없음. 쿠키에 code_id, thread_id, 만료 시각을 넣고 서명 | 2시간 전에 강제로 끊을 수 없다. 대신 요청마다 코드 만료를 DB에서 다시 본다 |
| B. sessions 테이블 | 서버에서 끊을 수 있음. 쿠키에는 무작위 토큰만 | 테이블과 만료 행 정리가 필요 |
| C. Starlette SessionMiddleware | 코드가 짧음 | itsdangerous를 새로 설치해야 함. 내부적으로 A와 같은 방식 |

추천: **A**. 코드 만료·삭제는 요청마다 DB에서 확인하니, 끊어야 할 때는 코드를 만료시키면 된다.

## 4. 답변 토큰 스트리밍 (그래프를 안 바꾸는 조건)

문제: `answer` 노드는 구조화 출력(`{"answer": ..., "source_post_ids": [...]}`)이라 `stream_mode="messages"`로 받으면 JSON 조각이 온다. `grade`(JSON)와 `rewrite_query`(검색어)의 토큰도 같은 스트림에 섞인다.

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. API에서 거르고 풀기 | 메타데이터 `langgraph_node == "answer"`만 받고, 쌓이는 JSON에서 `answer` 문자열 값만 조금씩 꺼내 보낸다. 진짜 토큰 단위 | JSON 문자열 이스케이프(`\n`, `\"`, `\uXXXX`)를 푸는 작은 파서가 필요하고 테스트로 고정해야 함 |
| B. 진행 상황만 흘리고 답은 끝에 한 번 | 파서가 필요 없음 | 토큰 스트리밍 요구를 못 지킴 |
| C. answer 노드를 일반 텍스트로 바꿈 | 스트림이 깔끔 | 그래프 코드를 바꾸지 말라는 조건에 어긋남 |

`insufficient` 노드는 LLM을 부르지 않으므로 끝난 뒤 state의 answer를 한 번에 보낸다. 마지막 `sources` 이벤트는 state의 `source_post_ids`로 posts에서 제목과 URL을 읽어 보낸다.

추천: **A**.

## 함께 정해 둔 것(결정 아님, 바꾸려면 말해 주세요)

- 환경 변수: `DAILY_QUESTION_LIMIT`(기본 20), `ANSWER_MAX_TOKENS`(기본 1024), `CHAT_MODEL`(기본 claude-haiku-5-5), `ACCESS_CODE_PEPPER`, `SESSION_SECRET`.
- 비용: 모델별 백만 토큰당 단가를 코드 상수(Decimal)로 두고, 표에 없는 모델이면 서버가 뜨지 않게 한다. 단가는 구현 전에 claude-api 문서로 확인한다.
- 그래프의 `conn`(검색·질문 로그용 동기 연결)은 서버에서 하나를 열어 넘긴다. 체크포인터는 lifespan에서 `AsyncConnectionPool` + `AsyncPostgresSaver`로 연다.
