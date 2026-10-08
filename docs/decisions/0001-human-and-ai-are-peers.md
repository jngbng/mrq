# 0001. 사람과 AI를 대등한 경로로 둔다

날짜: 2026-10-11 · 상태: 채택

## 배경

리뷰 코멘트를 실제로 처리하는 주 작업자가 누구인지에 따라 설계가 갈린다. 사람 중심이면
`review.md`의 문법과 렌더 품질이 최우선이고, AI 중심이면 CLI 상태 변경 명령이
MVP에 들어가며 md는 사람이 읽는 뷰로 축소된다.

## 결정

양쪽을 모두 1급 경로로 설계한다. 사람은 `review.md`를 편집하고, AI는 md 또는
CLI(`mrq reply` / `mrq state`)를 쓴다. 둘이 동시에 작업하는 것이 정상 워크플로다.

## 결과

- CLI 상태 변경 명령이 MVP에 포함된다 ([0002](0002-per-thread-conflict-detection.md)의 충돌 감지도 여기서 나온다)
- VSCode 확장이 md를 파싱하지 않고도 상태를 바꿀 수 있다 — 같은 명령을 쓴다
- md 파서가 AI 생성 마크다운을 견뎌야 한다 ([0004](0004-single-edit-surface-hardened-grammar.md))
- 사람이 md를, AI가 CLI를 동시에 쓰므로 에디터는 `review.json`을 파일 감시해야 한다
