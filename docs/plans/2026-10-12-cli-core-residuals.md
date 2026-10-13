# 잔여 항목 (계획 1·3의 최종 리뷰에서 남은 것)

계획 1의 최종 브랜치 리뷰가 "나중에"로 판정한 것들이다. 계획 1 의 계획서는 작업
완료 후 삭제됐고, 범위와 결과는 `README.md`에 있다.

R1~R8은 모두 해소됐다 — R1·R2는 계획 2의 첫 두 과제로, R3·R4는 "계획 3 전 과제"로,
R6·R7은 같은 전 과제로, R5·R8은 계획 3의 설계(결정 0011·0012, `spec/data-model.md`
§4.10, `spec/cli.md` §5·§8 — `sync`의 규범은 §5이고 §8은 `status`에서 그것을
되비춘다)로 들어갔다. 아래는 그 R 번호가 붙지 않은, 아직 플랜에 배정되지 않은
항목들이다.

계획 3 의 최종 리뷰가 남긴 계약 두 건(`sync --json` 의 nullable `line`,
`capabilities.draft_notes` 정의)은 2026-10-14 에 해소했다 — `spec/cli.md` §5,
`spec/editor.md` §3.4, `spec/data-model.md` §3, 그리고 `mrq-design.md` §6 의
future work 한 행.

## `push` 의 전송 처리량 (실측에서 나온 것)

2026-10-14 실측(`README.md` 계획 3)에서 쓰기 14회에 16.17초가 들었다 — 호출당 약
1.2초이고 전부 순차다. 코멘트 50개 MR 이면 같은 비율로 1분가량이며 그동안 진행
표시가 없다.

지금 결함은 아니다 — `PRD` §6 의 성능 요구는 `pull` 10초만 못박고 `push` 는 비워
뒀다. 다만 손대려면 순서가 있다: **스레드마다 결과를 즉시 json 에 쓰는 구조
(`spec/cli.md` §9 4c MUST)가 병렬 전송과 같이 갈 수 없다.** 동시성을 넣는 작업은
그 MUST 를 먼저 다시 설계하는 일이고, 크래시 복구 보장을 건드리는 변경이므로
진행 표시(스레드별 한 줄 출력)부터 하는 쪽이 훨씬 싸다.

## 위치 코멘트를 새로 만들 때 필요한 것 (future work)

`mrq` 는 기존 스레드에 답글만 단다. 새 위치 코멘트를 만드는 기능
(`mrq-design.md` §6 의 future work)을 할 때 아래가 걸린다. 2026-10-13 실측이다.

- `-F "position[new_line]=15"` 식 bracket 키는 JSON 본문에서 중첩으로 가지
  않는다. glab 1.114 는 조용히 무시했고(위치 없는 스레드가 성공 응답과 함께
  만들어진다), 최신 문서는 에러로 거부한다고 적는다. 어느 쪽이든 쓰면 안 된다.
- 중첩은 `-F 'position={"position_type":"text","new_line":15}'` 로 보낸다.
  `--input` 은 필요 없다.
- `--input` 을 쓴다면 `-H "Content-Type: application/json"` 을 함께 줘야 한다.
  빼면 GitLab 이 `HTTP 415` 를 돌려준다.

## 코드 모양 (다음 계획을 쉽게 만드는 것들)

- `anchor.read_lines`와 `reanchor._read_worktree`가 같은 CRLF 정규화·분할·끝 빈 줄
  제거 루틴이다. `anchor._HUNK_HEADER`와 `linemap._HUNK`는 플래그만 다른 같은
  정규식이고 각자 별도의 hunk 파서를 먹인다. 계획 2의 렌더러가 세 번째를 원할 것이다.
  공유 헬퍼로 모으면 드리프트를 막는다.
- `anchor._split_hunks`가 파일 경계를 무시하고 diff의 모든 파일 섹션의 hunk를 한
  리스트로 평탄화한다. `hunk_for`는 줄 번호만으로 고른다. `-M`이 rename을 놓치면
  (유사도 50% 미만) git이 두 경로의 delete+add 섹션을 내보내고, 선택이 우연히만
  맞는다. 렌더러가 `hunk`를 그대로 소비하기 시작하면 `+++ b/<path>` 섹션에 선택을
  묶어야 한다.
- 스키마의 `format: "date-time"`은 파이썬 쪽에서 장식이다. `model.validate`가
  기본 검증기를 쓰고 `FormatChecker`도 `rfc3339-validator`도 없으므로
  `"pulled_at": "not-a-date"`가 통과한다. 세 구현이 공유하는 계약이므로 더 엄격한
  Emacs/VSCode 리더가 CLI가 쓴 것을 거부할 수 있다. `validate`에서 포맷을
  단언하든 키워드를 빼든 하나를 골라야 한다.
- `gitcmd.run`이 공개다. 한 번 우회된 적이 있던 `rev-parse --abbrev-ref HEAD`는
  `gitcmd.current_branch`로 옮겼지만(계획 2 최종 리뷰), 래퍼를 거치지 않을 수 있는
  문은 그대로 열려 있다. "모든 git 호출이 이름 붙은 감사 가능한 래퍼"라는 규율이
  `reanchor`가 네트워크를 안 탄다는 것을 증명할 수 있게 해 준 바로 그 장치다.
  `_run` + 이름 붙은 래퍼를 고려할 것.
- `.gitignore`가 `cli/uv.lock`을 제외하는데 `make deps`는 `uv sync`다. 하위 프로젝트
  셋과 계획 넷이 남은 상태에서 고정되지 않은 락파일은 피할 수 있는 드리프트다.
- `Stats.count`가 검증 없이 `setattr`을 쓴다. 지금은 도달 불가지만, 네 번째
  confidence 값이 생기면 `as_dict`가 버리는 유령 속성이 조용히 만들어진다 —
  거짓말하는 품질 게이트가 된다.

## 테스트 스위트

346개가 50초였던 것(계획 1 종료 시점)이 계획 3을 마친 지금 483개 81.05초다(2026-10-14
실측) — 선형 성장 추정(테스트당 약 40ms)과 맞고, 예고했던 60초 선을 넘었다. 비용은
함수 스코프 `git_repo` 픽스처(테스트당 git 서브프로세스 약 6회)가 지배한다. 실제 git
저장소를 쓰는 것은 옳은 선택이고(`reanchoring.md` §8이 MUST로 요구하며, `.mrq/`
가시성·`git mv`·rename pathspec 결함을 모두 그것이 잡았다) — 바꿔야 하는 것은
저장소를 매 테스트 새로 만드는 방식이다. 세션 스코프 템플릿 저장소 + `cp -r`로
바꾸는 작업이 이제 밀렸다. 계획 4(Emacs ERT는 별개 하네스라 영향 없음)나 계획
5보다는, 이 스위트를 계속 돌릴 계획 4·5 작업 자체가 다음으로 이걸 만날 계획이다.
