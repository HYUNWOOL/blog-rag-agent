"""진짜 그래프를 돌리다 프로세스를 강제 종료하고, 같은 thread_id로 재개해 무엇이 다시 도는지 본다.

실행: uv run python experiments/week2/kill_resume.py --node grade --after 0.3
로그를 쓴 직후에 죽이기: --node log_question --after 1 --pause 30 [--no-idempotent]

개발 DB와 실제 LLM을 쓴다. 먼저 alembic upgrade head와 make checkpoints가 돼 있어야 한다.
"""

import argparse
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from blog_rag_agent.config import load_settings
from blog_rag_agent.graph import agentic
from blog_rag_agent.graph.agentic import build_graph, open_graph, run_async, run_config
from blog_rag_agent.graph.research import make_model
from blog_rag_agent.graph.trace import read_trace

NODES = ("retrieve", "grade", "rewrite_query", "answer", "log_question")
# 자식 프로세스가 임베딩 모델을 올리는 시간까지 포함한다.
START_TIMEOUT_SECONDS = 120
QUESTION = "튀르키예를 어떤 순서로 이동했어?"


def patch_log_write(args) -> None:
    """제품 코드를 바꾸지 않고 이 프로세스의 로그 쓰기만 실험용으로 감싼다."""
    real = agentic.upsert_question_log

    def upsert(conn, **row):
        if args.no_idempotent:
            # 멱등키를 없앤 상태: 노드가 다시 돌 때마다 다른 키로 들어간다.
            row["thread_id"] = f"{args.thread}:{uuid.uuid4().hex[:8]}"
        real(conn, **row)
        # DB에는 썼지만 체크포인트는 아직 안 쓴 순간을 kill이 맞히도록 붙잡아 둔다.
        if args.child == "start":
            time.sleep(args.pause)

    agentic.upsert_question_log = upsert


async def run_child(args) -> None:
    """kill 대상이 되는 별도 프로세스. start는 처음부터, resume은 입력 None으로 이어 간다."""
    patch_log_write(args)
    async with open_graph(Path(args.trace)) as graph:
        await graph.ainvoke(
            {"question": QUESTION} if args.child == "start" else None,
            run_config(args.thread),
            durability=args.durability,
        )


def spawn(mode: str, args, thread_id: str, trace_path: Path) -> subprocess.Popen:
    command = [
        sys.executable,
        __file__,
        "--child",
        mode,
        "--thread",
        thread_id,
        "--trace",
        str(trace_path),
        "--durability",
        args.durability,
        "--pause",
        str(args.pause),
    ]
    if args.no_idempotent:
        command.append("--no-idempotent")
    return subprocess.Popen(
        command, stderr=subprocess.PIPE, text=True, encoding="utf-8"
    )


def wait_for_start(trace_path: Path, node: str, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if any(
            e["node"] == node and e["event"] == "start" for e in read_trace(trace_path)
        ):
            return
        if proc.poll() is not None:
            raise RuntimeError(f"{node} 시작 전에 끝났다: {proc.stderr.read()}")
        time.sleep(0.05)
    raise TimeoutError(f"{START_TIMEOUT_SECONDS}초 안에 {node}가 시작되지 않았다")


def summarize(events: list[dict]) -> list[str]:
    """노드마다 한 줄. end가 없으면 도는 중에 죽은 노드다."""
    finished = {e["node"] for e in events if e["event"] == "end"}
    return [
        f"{e['node']} {'완료' if e['node'] in finished else '시작만 (kill)'}"
        for e in events
        if e["event"] == "start"
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--node", choices=NODES, default="grade")
    parser.add_argument(
        "--after", type=float, default=0.3, help="노드 시작 뒤 kill까지 초"
    )
    parser.add_argument(
        "--durability", choices=("sync", "async", "exit"), default="async"
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0,
        help="로그를 쓴 뒤 멈출 초(log_question kill용)",
    )
    parser.add_argument(
        "--no-idempotent", action="store_true", help="멱등키 없이 로그를 쓴다"
    )
    parser.add_argument("--child", choices=("start", "resume"), help=argparse.SUPPRESS)
    parser.add_argument("--thread", help=argparse.SUPPRESS)
    parser.add_argument("--trace", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        run_async(run_child(args))
        return

    settings = load_settings()
    thread_id = str(uuid.uuid4())
    config = run_config(thread_id)
    trace_path = Path(tempfile.gettempdir()) / f"kill_resume_{thread_id}.jsonl"

    with PostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        # 부모는 상태만 읽으므로 노드가 쓸 conn과 embedder는 없어도 된다.
        graph = build_graph(
            None, None, make_model(settings.anthropic_api_key), checkpointer
        )

        proc = spawn("start", args, thread_id, trace_path)
        wait_for_start(trace_path, args.node, proc)
        time.sleep(args.after)
        # Popen.kill()은 Windows에서 TerminateProcess다. 정리 코드 없이 즉시 죽는다.
        proc.kill()
        proc.wait()
        before = read_trace(trace_path)
        next_nodes = graph.get_state(config).next

        resumed = spawn("resume", args, thread_id, trace_path)
        _, stderr = resumed.communicate()
        after = read_trace(trace_path)[len(before) :]
        snapshot = graph.get_state(config)

    with psycopg.connect(settings.database_url) as conn:
        logs = conn.execute(
            "SELECT status, attempts, llm_calls FROM question_logs"
            " WHERE thread_id LIKE %s",
            (f"{thread_id}%",),
        ).fetchall()

    print(f"thread_id: {thread_id}")
    print(f"kill: {args.node} 시작 {args.after}초 뒤, durability={args.durability}")
    print(f"멱등: {'끔' if args.no_idempotent else '켬'}")
    print(f"죽은 뒤 get_state().next: {next_nodes}\n")

    left, right = summarize(before), summarize(after)
    width = max([len("죽기 전"), *map(len, left)]) + 8
    print(f"{'죽기 전':<{width}}재개 뒤")
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else ""
        b = right[i] if i < len(right) else ""
        print(f"{a:<{width}}{b}")

    print(f"\n재개 종료 코드: {resumed.returncode}")
    if resumed.returncode:
        print(f"재개 오류: {stderr.strip().splitlines()[-1]}")
    print(f"최종 llm_calls: {snapshot.values.get('llm_calls')}")
    print(f"question_logs 행 수: {len(logs)} {logs}")


if __name__ == "__main__":
    main()
