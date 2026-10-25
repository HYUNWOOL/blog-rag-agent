"""로컬 임베딩(1주차 결정: BAAI/bge-m3, 1024차원)."""

# chunks.embedding 컬럼 타입 vector(1024)와 같아야 한다.
EMBEDDING_DIM = 1024


class LocalEmbedder:
    def __init__(self, model_name: str) -> None:
        # torch까지 끌어오는 무거운 import라, 임베더를 실제로 만들 때만 불러온다.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # 단위 벡터로 정규화해 두면 코사인 거리(<=>)가 모델이 의도한 유사도와 같아진다.
        vectors = self._model.encode(texts, normalize_embeddings=True)
        if vectors.shape[1] != EMBEDDING_DIM:
            raise ValueError(f"임베딩 차원 {vectors.shape[1]} != {EMBEDDING_DIM}")
        return vectors.tolist()
