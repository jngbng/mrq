# 계획 1 잔여 항목 (계획 3 시작 전에 읽을 것)

계획 1의 최종 브랜치 리뷰가 "나중에"로 판정한 것들이다. 계획 1 의 계획서는 작업
완료 후 삭제됐고, 범위와 결과는 `README.md`에 있다.
병합을 막지는 않지만, 각 항목에는 그것을 먼저 필요로 하는 계획이 적혀 있다.

**R6~R8은 계획 2를 실제 MR로 검증하면서 나왔다** (2026-10-13,
`gitlab.com/jngbng/mr-helper` 의 MR `!1` — 코멘트 15개, 재사용 가능한 픽스처로
남겨 뒀다). 단위 테스트가 전부 통과하는 상태에서 나온 것들이므로, 셋 다 "테스트가
덮지 못한 모양의 입력"이라는 공통점이 있다.


**R5·R8 은 계획 3 의 범위로 들어갔다** (2026-10-13 설계). 규범은
`spec/data-model.md` §4.10(`server.missing`)과 `spec/cli.md` §5(답글이 있는데
`todo` 인 스레드)이며 근거는 결정 0011·0012 에 있다. 여기서는 더 다루지 않는다.


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
- `discussions._to_thread`가 `updated_at` 문자열에 사전식 `max()`를 쓴다. GitLab이
  오프셋 형식을 하나로 유지하는 동안만 맞고, `Z`와 `+09:00`이 섞이면 순서가
  틀린다 — `data-model.md` §4.2에 따라 `push`가 멀쩡한 스레드를 건너뛴다.
- `store.read_current`가 `ValueError`를 낼 수 있다. 손으로 만든 비숫자 `current`
  심링크에서 `int(current.resolve().name)`이 터진다.
- `.gitignore`가 `cli/uv.lock`을 제외하는데 `make deps`는 `uv sync`다. 하위 프로젝트
  셋과 계획 넷이 남은 상태에서 고정되지 않은 락파일은 피할 수 있는 드리프트다.
- `Stats.count`가 검증 없이 `setattr`을 쓴다. 지금은 도달 불가지만, 네 번째
  confidence 값이 생기면 `as_dict`가 버리는 유령 속성이 조용히 만들어진다 —
  거짓말하는 품질 게이트가 된다.

## 테스트 스위트

346개가 50초. 가장 느린 테스트가 0.51초이고 비용은 함수 스코프 `git_repo`
픽스처(테스트당 git 서브프로세스 약 6회)가 지배한다. 성장이 테스트당 약 40ms로
선형이므로 지금의 네 배에서 30초쯤 된다. 실제 git 저장소를 쓰는 것은 옳은 선택이고
(`reanchoring.md` §8이 MUST로 요구하며, `.mrq/` 가시성·`git mv`·rename pathspec
결함을 모두 그것이 잡았다), 60초를 넘길 때 세션 스코프 템플릿 저장소 + `cp -r`로
바꾸면 된다. 그 전에 손댈 필요 없다.
