"""answer 노드의 구조화 출력 JSON 조각에서 "answer" 문자열 값만 조금씩 꺼낸다.

그래프는 {"answer": "...", "source_post_ids": [...]}를 토큰 단위로 내보낸다. 그래프를 바꾸지 않고
사용자에게 답 글자만 흘리려고, 쌓인 JSON에서 answer 값의 해석 가능한 앞부분을 매번 디코딩한다.
"""

import json
import re

ANSWER_START = re.compile(r'"answer"\s*:\s*"')
MAX_ESCAPE = 12  # 😀처럼 서로게이트 쌍 하나가 이스케이프로 12자다


class AnswerExtractor:
    def __init__(self) -> None:
        self.buffer = ""  # answer 값 시작 전까지의 JSON
        self.body = ""  # answer 문자열 값의 원문(이스케이프 그대로)
        self.started = False
        self.done = False
        self.escaped = False
        self.sent = 0  # 이미 내보낸 디코딩 글자 수

    def feed(self, text: str) -> str:
        """새 JSON 조각을 받고, 이번에 새로 확정된 답 글자를 돌려준다."""
        if self.done or not text:
            return ""
        if not self.started:
            self.buffer += text
            match = ANSWER_START.search(self.buffer)
            if not match:
                return ""
            self.started = True
            text = self.buffer[match.end():]
        for ch in text:
            if self.escaped:
                self.escaped = False
            elif ch == "\\":
                self.escaped = True
            elif ch == '"':
                self.done = True
                break
            self.body += ch
        return self._new_text()

    def _new_text(self) -> str:
        decoded = self._decodable_prefix()
        piece = decoded[self.sent:]
        self.sent = len(decoded)
        return piece

    def _decodable_prefix(self) -> str:
        # 끝에 덜 온 이스케이프(\, \u00 등)가 있으면 잘라 가며 해석되는 가장 긴 앞부분을 찾는다.
        for cut in range(min(MAX_ESCAPE, len(self.body)) + 1):
            raw = self.body[: len(self.body) - cut]
            try:
                # strict=False: 줄바꿈 같은 제어 문자가 이스케이프 없이 와도 받는다.
                decoded = json.loads(f'"{raw}"', strict=False)
            except json.JSONDecodeError:
                continue
            # 서로게이트 쌍의 앞 절반만 왔으면 다음 조각과 합쳐질 때까지 내보내지 않는다.
            if decoded and "\ud800" <= decoded[-1] <= "\udbff":
                decoded = decoded[:-1]
            return decoded
        return self.body[:0]
