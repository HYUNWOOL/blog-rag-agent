import hashlib
import math


class FakeEmbedder:
    """네트워크·모델 없이 입력 텍스트만으로 정해지는 벡터를 만들고, 호출을 센다.

    shortcut: 인터페이스(embed(texts) -> vectors)는 임시다. 실제 임베더를 정하면 그 모양에 맞춘다.
    """

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        # embed() 호출 횟수. 재적재 때 다시 임베딩했는지 확인하는 데 쓴다.
        self.calls = 0
        self.texts: list[str] = []  # 지금까지 받은 텍스트 전부

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts.extend(texts)
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        # shake_256은 원하는 길이만큼 바이트를 주므로 dim이 커도 된다. 같은 텍스트면 항상 같은 값.
        raw = [
            (b - 127.5) / 127.5
            for b in hashlib.shake_256(text.encode()).digest(self.dim)
        ]
        # 단위 벡터로 맞춰 코사인 거리 계산이 실제 임베딩과 같은 성질을 갖게 한다. 0 벡터는 나올 수 없다.
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]
