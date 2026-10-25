"""questions.txt를 세 버전으로 돌려 평균 LLM 호출 수, 토큰, 지연, 코드 줄 수를 표로 찍는다.

실행: uv run python experiments/week1/compare.py [질문 파일]
"""

import inspect
import sys
import time
from pathlib import Path

import anthropic
import psycopg
from pgvector.psycopg import register_vector
from raw_loop import run_raw

from blog_rag_agent.config import load_settings
from blog_rag_agent.embedding import LocalEmbedder
from blog_rag_agent.graph.research import build_graph, make_model, run_graph
from blog_rag_agent.workflow import answer_v0

DEFAULT_QUESTIONS = Path(__file__).with_name("questions.txt")
ANSWERS = Path(__file__).with_name("compare_answers.md")


def code_lines(*objs) -> int:
    # 핵심 함수의 소스에서 빈 줄·주석·docstring 줄을 뺀 줄 수. 공통 툴/프롬프트(agent_tools)는 셋 다 쓰므로 뺀다.
    lines = [
        line.strip() for obj in objs for line in inspect.getsource(obj).splitlines()
    ]
    return sum(1 for s in lines if s and not s.startswith(("#", '"""')))


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_QUESTIONS
    lines = path.read_text(encoding="utf-8").splitlines()
    questions = [q.strip() for q in lines if q.strip() and not q.startswith("#")]

    settings = load_settings()
    embedder = LocalEmbedder(settings.embedding_model)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        register_vector(conn)
        graph = build_graph(conn, embedder, make_model(settings.anthropic_api_key))
        versions = {
            "v0 workflow": (
                lambda q: answer_v0(q, conn=conn, embedder=embedder, client=client),
                code_lines(answer_v0),
            ),
            "raw_loop": (
                lambda q: run_raw(
                    q, conn=conn, embedder=embedder, client=client, log=lambda _: None
                ),
                code_lines(run_raw),
            ),
            "langgraph": (
                lambda q: run_graph(q, graph),
                code_lines(build_graph, run_graph),
            ),
        }
        rows = []
        # 표의 숫자만으로는 답이 맞았는지 알 수 없어서, 답변 원문을 질문별로 파일에 남긴다.
        answers = [f"# compare 답변 원문 ({path.name})\n"]
        for name, (run, n_lines) in versions.items():
            results, failures = [], []
            answers.append(f"\n## {name}\n")
            for i, q in enumerate(questions, 1):
                start = time.perf_counter()
                try:
                    r = run(q)
                # 상한 초과·API 오류 등 어떤 실패든 비교 대상이라 세고 넘어간다
                except Exception as e:  # noqa: BLE001
                    failures.append(f"{q} → {type(e).__name__}: {e}")
                    answers.append(f"\n### {i}. {q}\n\n실패: {type(e).__name__}: {e}\n")
                    continue
                elapsed = time.perf_counter() - start
                results.append((r, elapsed))
                answers.append(
                    f"\n### {i}. {q}\n\n"
                    f"(호출 {r['llm_calls']}회, 토큰 {r['input_tokens']}+{r['output_tokens']}, "
                    f"{elapsed:.1f}초)\n\n{r['answer'].strip()}\n"
                )
            n = len(results) or 1
            rows.append(
                (
                    name,
                    sum(r["llm_calls"] for r, _ in results) / n,
                    sum(r["input_tokens"] + r["output_tokens"] for r, _ in results) / n,
                    sum(t for _, t in results) / n,
                    n_lines,
                    len(failures),
                )
            )
            for f in failures:
                print(f"FAILED [{name}] {f}", file=sys.stderr)

    ANSWERS.write_text("".join(answers), encoding="utf-8", newline="\n")
    print(f"질문 {len(questions)}개 ({path.name}), 답변 원문: {ANSWERS.name}\n")
    print(
        "| 버전 | 평균 LLM 호출 | 평균 토큰(입력+출력) | 평균 지연(초) | 코드 줄 수 | 실패 |"
    )
    print("| --- | --- | --- | --- | --- | --- |")
    for name, calls, tokens, latency, n_lines, failed in rows:
        print(
            f"| {name} | {calls:.1f} | {tokens:.0f} | {latency:.1f} | {n_lines} | {failed} |"
        )


if __name__ == "__main__":
    main()
