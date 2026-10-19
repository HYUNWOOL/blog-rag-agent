"""WordPress REST API로 공개 글을 모아 data/posts/<slug>.md 로 저장한다.

실행: uv run python -m blog_rag_agent.ingest.collect
DB에는 넣지 않는다. 같은 url은 같은 파일로 덮어써서 몇 번 돌려도 결과가 같다.
"""

import argparse
import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from markdownify import markdownify

BASE_URL = "https://thejoy-walking.com"
# src/blog_rag_agent/ingest/collect.py 기준 parents[3] = BE/
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
POSTS_DIR = DATA_DIR / "posts"
FAILED_PATH = DATA_DIR / "failed.txt"
MIN_INTERVAL_SEC = 1.0
POST_FIELDS = "id,link,status,title,date_gmt,modified_gmt,tags,categories,content"


class PoliteClient:
    """모든 요청 사이에 최소 간격을 강제하는 얇은 httpx 래퍼."""

    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": "blog-rag-agent-collector/0.1"},
            timeout=30.0,
            follow_redirects=True,
        )
        self._last = 0.0

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        # 실패한 요청도 간격에 포함되도록, 응답 결과와 상관없이 직전 요청 시각부터 잰다.
        wait = MIN_INTERVAL_SEC - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = self._client.get(path, params=params)
        finally:
            self._last = time.monotonic()
        resp.raise_for_status()
        return resp

    def close(self) -> None:
        self._client.close()


def fetch_all(client: PoliteClient, path: str, params: dict) -> list[dict]:
    """per_page=100으로 X-WP-TotalPages 끝까지 넘기며 목록을 모은다."""
    items: list[dict] = []
    page = 1
    while True:
        resp = client.get(path, params={**params, "per_page": 100, "page": page})
        items.extend(resp.json())
        if page >= int(resp.headers.get("X-WP-TotalPages", "1")):
            return items
        page += 1


def term_names(client: PoliteClient, taxonomy: str) -> dict[int, str]:
    terms = fetch_all(client, f"/wp-json/wp/v2/{taxonomy}", {"_fields": "id,name"})
    # 용어 이름에 &amp; 같은 HTML 엔티티가 섞여 오므로 풀어 둔다.
    return {t["id"]: html.unescape(t["name"]) for t in terms}


def code_language(el) -> str:
    """<pre><code class="language-python"> 형태에서 펜스 언어를 꺼낸다. 없으면 빈 문자열."""
    for node in [el, el.find("code")]:
        for cls in (node.get("class") or []) if node is not None else []:
            if cls.startswith("language-"):
                return cls.removeprefix("language-")
    return ""


def to_markdown(content_html: str) -> str:
    md = markdownify(
        content_html,
        heading_style="ATX",  # '## 제목' 형태. 밑줄형(Setext)은 h3 이하를 표현 못 한다.
        bullets="-",
        code_language_callback=code_language,  # <pre>는 ``` 펜스로, 언어 클래스가 있으면 붙인다.
    )
    # 이미지는 ![alt](src)로 남는다. 변환 뒤 남는 3줄 이상 빈 줄만 정리한다.
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def slug_from_url(url: str) -> str:
    # 파일 이름을 url에서만 만들어야 같은 글이 항상 같은 파일로 덮어써진다.
    slug = unquote(urlparse(url).path.strip("/").split("/")[-1])
    return re.sub(r'[<>:"/\\|?*\s]+', "-", slug) or "index"


def render_file(post: dict, tags: list[str], body: str) -> str:
    # 값은 json.dumps로 쓴다. JSON 문자열/배열은 그대로 유효한 YAML이라 따옴표·콜론 이스케이프를 따로 안 짜도 된다.
    meta = {
        "url": post["link"],
        "title": html.unescape(re.sub(r"<[^>]+>", "", post["title"]["rendered"])),
        # date_gmt는 시간대 없는 UTC 문자열이라 Z를 붙여 의미를 명시한다.
        "published_at": post["date_gmt"] + "Z",
        "updated_at": post["modified_gmt"] + "Z",
        "tags": tags,
        # 본문이 바뀌었는지 적재 단계에서 비교할 수 있게 마크다운 본문의 해시를 남긴다.
        "content_hash": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    head = "\n".join(
        f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()
    )
    return f"---\n{head}\n---\n\n{body}"


def collect(base_url: str) -> tuple[int, list[str]]:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(base_url)
    failed: list[str] = []
    saved = 0
    try:
        # 비로그인 요청은 status=publish 글만 돌려준다(draft·private은 401). 아래에서 한 번 더 거른다.
        listing = fetch_all(client, "/wp-json/wp/v2/posts", {"_fields": "id,link"})
        names = {**term_names(client, "categories"), **term_names(client, "tags")}

        for item in listing:
            try:
                post = client.get(
                    f"/wp-json/wp/v2/posts/{item['id']}", {"_fields": POST_FIELDS}
                ).json()
                # 공개 글이 아니거나 비밀번호 보호 글이면 건너뛴다.
                if post["status"] != "publish" or post["content"].get("protected"):
                    continue
                # 카테고리와 태그를 합치고 정렬해서, 실행할 때마다 순서가 같게 한다.
                ids = post["categories"] + post["tags"]
                tags = sorted({names[i] for i in ids if i in names})
                body = to_markdown(post["content"]["rendered"])
                path = POSTS_DIR / f"{slug_from_url(post['link'])}.md"
                # newline="\n": Windows에서도 CRLF로 바뀌지 않아 해시와 파일 내용이 OS와 무관하게 같다.
                path.write_text(
                    render_file(post, tags, body), encoding="utf-8", newline="\n"
                )
                saved += 1
            # 한 글이 실패해도 나머지는 계속 모은다. 네트워크/HTTP, 깨진 JSON, 필드 누락, 파일 쓰기만 잡는다.
            except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError) as e:
                failed.append(f"{item['link']}\t{type(e).__name__}: {e}")
    finally:
        client.close()

    # 이번 실행의 실패만 남긴다. 덮어쓰기라 재실행해도 줄이 쌓이지 않는다.
    FAILED_PATH.write_text(
        "".join(f"{line}\n" for line in failed), encoding="utf-8", newline="\n"
    )
    return saved, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    saved, failed = collect(args.base_url)
    print(f"saved={saved} failed={len(failed)} -> {POSTS_DIR}")
    for line in failed:
        print(f"FAILED {line}", file=sys.stderr)


if __name__ == "__main__":
    main()
