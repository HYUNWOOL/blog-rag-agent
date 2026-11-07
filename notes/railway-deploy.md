# Railway 배포 (2026-11-07 기준)

결정은 notes/decisions.md "3주차 Railway 배포 결정". Railway 문서는 2026-11-07에 읽었다.

## 지금 빌드가 실패한 이유

`Railpack failed to prepare the build`. 서비스가 저장소 루트를 빌드하는데, 루트에는 `BE/`, `FE/`, `notes/`만 있고 `pyproject.toml`이나 `Dockerfile`이 없다. 그래서 Railpack이 무엇을 빌드할지 정하지 못한다. 빌드 로그 원문은 보지 못했으니, 아래 1~2단계 후에도 실패하면 로그를 붙여 달라.

또 배포된 커밋(5c511b2)에는 웹 서버 코드가 아직 없다. 커밋·push 전까지는 무엇을 해도 서버가 뜨지 않는다.

## 내가 할 단계

1. 코드 커밋·push: Dockerfile, .dockerignore, src/blog_rag_agent/api/, static/, 마이그레이션, pyproject.toml·uv.lock.
2. DB를 pgvector로 바꾸기. 기본 Postgres 템플릿에는 pgvector 확장이 없다(문서: "we do not plan to add extensions to the PostgreSQL templates"). 첫 마이그레이션의 `CREATE EXTENSION vector`가 실패한다.
   - 프로젝트 캔버스에서 + → Template → **pgvector**(이미지 `pgvector/pgvector:pg18`, 로컬 docker-compose와 같은 이미지)를 추가한다.
   - 지금 추가한 기본 Postgres는 데이터가 없으면 삭제한다(되돌릴 수 없음, 확인 후).
   - 서비스 이름이 `pgvector`가 아니면 아래 참조 변수의 이름을 그 이름으로 바꾼다.
3. 웹 서비스(blog-rag-agent) Settings
   - **Root Directory**: `/BE`. 그러면 `BE/Dockerfile`을 자동으로 쓴다.
   - **Healthcheck Path**: `/healthz`. 기본 대기 300초. 첫 부팅은 마이그레이션과 모델 로딩이 있어 수십 초 걸린다.
   - **Networking → Generate Domain**: 지금은 "Unexposed service"라 주소가 없다. 쿠키가 Secure라 https 도메인에서만 로그인된다(Railway 도메인은 https).
   - **Wait for CI**: GitHub Actions 워크플로(on: push)가 저장소에 있어야 설정에 보인다. 지금 저장소에는 워크플로가 없어서 켤 수 없다. 테스트 워크플로를 만들지는 따로 정한다.
   - railway.json/railway.toml은 쓰지 않는다. Config as Code는 폐기 예정이라 새 서비스는 쓸 수 없고, 2026-12-01에 기존 것도 끊긴다.
4. 웹 서비스 Variables(아래 표). 다 넣고 Deploy(변경은 staged로 모였다가 배포해야 적용된다).
5. 운영 DB 적재: 아래 "운영 적재"를 내 PC에서 한 번 실행한다.
6. 접근 코드 발급: 아래 "운영 접근 코드".
7. 확인: `https://<도메인>/healthz`가 `{"status":"ok"}`, 브라우저로 코드 입력 → 질문 하나 → usage_log 행 확인.

## 환경 변수 (웹 서비스)

| 이름 | 예시 | 어디서 | 비밀 |
| --- | --- | --- | --- |
| `DATABASE_URL` | `${{pgvector.DATABASE_URL}}` | 참조 변수. pgvector 서비스의 비공개 네트워크 주소 | 예(비밀번호 포함) |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Claude Console에서 운영용 키를 새로 발급 | 예 |
| `ACCESS_CODE_PEPPER` | 32자 이상 무작위 | `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` | 예. 바꾸면 발급한 코드가 모두 무효 |
| `SESSION_SECRET` | 32자 이상 무작위(PEPPER와 다른 값) | 위와 같은 명령 | 예. 바꾸면 로그인 세션이 모두 끊김 |
| `EMBEDDING_PROVIDER` | `local` | 고정 | 아니오 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 고정. 이미지에 구운 모델과 같아야 함 | 아니오 |
| `DAILY_QUESTION_LIMIT` | `20` | 코드 발급 때 `--limit` 기본값 | 아니오 |
| `ANSWER_MAX_TOKENS` | `1024` | LLM 호출 한 번의 max_tokens | 아니오 |
| `CHAT_MODEL` | `claude-haiku-5-5` | 단가표에 있는 모델만 | 아니오 |
| `LANGSMITH_TRACING` | `false` | 고정 | 아니오 |
| `PORT` | `8080` | Networking의 도메인 Target Port와 같은 값. 서버는 이 포트로 듣는다 | 아니오 |

비밀 4개는 Railway의 Sealed 변수로 두어도 된다(봉인하면 UI·API·`railway run`에서 다시 볼 수 없고 풀 수 없다).

## PowerShell에서 uv가 안 잡힐 때

uv는 `%APPDATA%\Python\Python311\Scripts`에 깔려 있고 PATH에 없다. 창마다 먼저:

```powershell
$env:Path = "$env:APPDATA\Python\Python311\Scripts;$env:Path"
uv --version
```

## 운영 적재 (내 PC, 한 번)

pgvector 서비스 Settings → Networking에서 Public Access(TCP Proxy)가 켜져 있어야 `DATABASE_PUBLIC_URL`이 생긴다. 이 값을 그 명령에만 준다. `.env`에는 넣지 않는다. config.py와 alembic은 셸 환경 변수를 .env보다 먼저 쓴다.

PowerShell(BE/에서):

```powershell
$env:DATABASE_URL = "<pgvector 서비스 Variables의 DATABASE_PUBLIC_URL>"
uv run alembic upgrade head
uv run python -m blog_rag_agent.db.setup_checkpointer
uv run python -m blog_rag_agent.ingest.load
Remove-Item Env:DATABASE_URL
```

- `data/posts`가 비어 있으면 load 전에 `uv run python -m blog_rag_agent.ingest.collect`.
- load는 몇 번 다시 돌려도 결과가 같다(글 해시로 바뀐 글만 다시 임베딩).
- 끝나면 Public Access를 꺼도 된다(외부 접속 트래픽은 egress로 과금). 다시 적재할 때 켠다.

## 운영 접근 코드

코드 해시는 `ACCESS_CODE_PEPPER`로 만들므로 Railway의 값과 같은 값으로 발급해야 한다.

```powershell
$env:DATABASE_URL = "<DATABASE_PUBLIC_URL>"
$env:ACCESS_CODE_PEPPER = "<Railway에 넣은 ACCESS_CODE_PEPPER>"
$env:SESSION_SECRET = "<Railway에 넣은 SESSION_SECRET>"
uv run python -m blog_rag_agent.api.issue_code "회사 이름" --days 30 --limit 20
Remove-Item Env:DATABASE_URL, Env:ACCESS_CODE_PEPPER, Env:SESSION_SECRET
```

(SESSION_SECRET은 설정 검사 때문에 필요할 뿐 발급에는 쓰지 않는다. PowerShell 기록에 값이 남으니 창을 닫거나 기록을 지운다.)

## 로컬 이미지 확인

```bash
docker build -t blog-rag-agent:local BE
```

```bash
docker run --rm -p 8000:8000 --env-file BE/.env -e PORT=8000 -e DATABASE_URL=postgresql://rag:rag@host.docker.internal:5432/rag -e ACCESS_CODE_PEPPER=<32자 이상> -e SESSION_SECRET=<32자 이상> blog-rag-agent:local
```

```bash
curl -i http://127.0.0.1:8000/healthz
```

2026-11-07 결과: 빌드 성공, 컨테이너 기동 약 12초(마이그레이션 → 체크포인트 테이블 → uvicorn), `/healthz` 200 `{"status":"ok"}`, `/` 200, 실행 사용자 `uid=10001(app)`, 실제 질문 1건 스트리밍·근거 링크 정상, 한도 1에서 두 번째 요청 429.

## 비용 주의

Railway는 쓴 만큼 과금한다: RAM $10/GB/월, CPU $20/vCPU/월. Hobby는 월 $5 구독에 $5 사용량 포함(docs.railway.com/reference/pricing/plans).

로컬 실측(2026-11-07, docker stats): 기동 직후 884MiB, 질문 하나 처리 중 최대 913MiB(1초 간격 표본 2개라 순간 최대치는 놓쳤을 수 있다). 약 0.9GB를 한 달 내내 쓰면 RAM만 약 $9로 포함 사용량 $5를 넘는다. 배포 후 Metrics 탭에서 실제 값을 확인한다.

이미지: 7.41GB(Docker Desktop 표시). 큰 층은 Python 패키지 2.79GB, bge-m3 가중치 2.29GB.

## 출처

- Config as Code 폐기: https://docs.railway.com/guides/config-as-code
- Dockerfile 자동 사용, RAILWAY_DOCKERFILE_PATH: https://docs.railway.com/guides/dockerfiles
- Root Directory: https://docs.railway.com/guides/monorepo
- 헬스체크(경로, 300초, healthcheck.railway.app, PORT): https://docs.railway.com/reference/healthchecks
- Wait for CI: https://docs.railway.com/guides/github-autodeploys
- 참조 변수, Sealed 변수: https://docs.railway.com/guides/variables
- 비공개 네트워크는 실행 중에만(빌드 중 불가): https://docs.railway.com/guides/private-networking
- Postgres 확장 없음, DATABASE_PUBLIC_URL과 Public Access: https://docs.railway.com/guides/postgresql
- pgvector 템플릿: https://railway.com/deploy/pgvector
- 요금: https://docs.railway.com/reference/pricing/plans
