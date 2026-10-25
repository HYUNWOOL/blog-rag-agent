# 판단 기록

## 1주차 결정 (2026-10-25, 근거: notes/week1-decision-points.md)
- 스키마: posts(url UNIQUE) + chunks(post_id FK, UNIQUE(post_id, chunk_index)) 2개. 본문 해시가 같으면 재임베딩 안 함.
- 임베딩: 로컬 BAAI/bge-m3, 1024차원, sentence-transformers. API 키·비용 없음 대신 의존성과 모델 다운로드가 큼.
- 청킹: `##` 소제목 단위, 앞에 "글 제목 > 소제목", 이미지 alt·캡션은 남기고 URL은 뺌, 짧은 섹션은 합치고 긴 섹션은 문단 경계에서 자름, 코드 블록은 자르지 않음.
- 인덱스: HNSW(vector_cosine_ops). 1주차 프롬프트에서 지정.
- State: messages(add_messages) + llm_calls. 토큰은 메시지의 usage_metadata에서 합산.
- 상한: 넘으면 실패로 멈춤(raw_loop max_steps=6 예외, LangGraph recursion_limit=10 → GraphRecursionError). 강제 답변 없음.
- 툴 설명: 용도와 언제 쓸지까지 적음(search_posts 먼저, get_post는 청크로 부족할 때만).
- 답변 프롬프트: 블로그 글만 근거로 한국어로 답하고, 근거가 없으면 없다고 말하고, 끝에 참고한 글 제목과 URL. 세 버전 공통.

## 판단: (질문 한 줄)
- 상황:
- 선택지: A / B / C
- 결정:
- 포기한 것:
- 어떻게 확인했나:
- 결과(숫자):
