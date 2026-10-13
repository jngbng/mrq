# 계획 1 잔여 항목 (계획 3 시작 전에 읽을 것)

계획 1의 최종 브랜치 리뷰가 "나중에"로 판정한 것들이다. 계획 1 의 계획서는 작업
완료 후 삭제됐고, 범위와 결과는 `README.md`에 있다.
병합을 막지는 않지만, 각 항목에는 그것을 먼저 필요로 하는 계획이 적혀 있다.

R1(`model`의 예외가 종료 코드 계약을 빠져나가는 것)과 R2(`pull`이 스키마 버전
불일치에서 복구 못 하는 것)는 계획 2의 첫 두 과제로 해소됐다.

**R6~R8은 계획 2를 실제 MR로 검증하면서 나왔다** (2026-10-13,
`gitlab.com/jngbng/mr-helper` 의 MR `!1` — 코멘트 15개, 재사용 가능한 픽스처로
남겨 뒀다). 단위 테스트가 전부 통과하는 상태에서 나온 것들이므로, 셋 다 "테스트가
덮지 못한 모양의 입력"이라는 공통점이 있다.

**R6(멀티라인 앵커)과 R7(UTC 렌더)은 브랜치 `jbseo/pre_step3`에서 해소됐다.**
둘 다 손으로 쓴 픽스처가 구현과 같은 틀린 가정을 공유해 테스트를 통과하고 있던
경우였다. 규범은 `reanchoring.md` §3·§5.4와 `review-md.md` §5에, 결정은
[0009](../decisions/0009-render-timestamps-in-local-timezone.md)에 남겼다.

## 계획 3(`push`) 전에 반드시 다룰 것

R3·R4는 **계획 3에 통합하지 않고 그 전 과제로 남긴다.** 둘은 "`push`를 쓸 수
없다"가 아니라 "`push`의 테스트를 쓸 수 없다"는 문제다 — 가짜 `glab`이 상태
코드도 2페이지 응답도 호출별 다른 응답도 만들지 못한다. 계획 3 안에 넣으면
멱등성·크래시 복구를 TDD로 쓸 수 없고 "구현 먼저, 테스트는 하네스를 고친 뒤"가
된다.

**R3. `glab.api`의 시그니처가 `push`를 버틸 수 없다.** (`cli.md` §3에 이미 기록)
두 문제가 같은 뿌리에서 나온다.

- **지금 당장**: `mr.detect`가 브랜치 이름을 경로에 그대로 보간한다
  (`?source_branch={branch}&...`). `#`·`&`·`%`·`+`를 담은 적법한 브랜치 이름이
  요청을 망가뜨린다 — `feat/#123`은 프래그먼트에서 잘려 GitLab이
  `source_branch=feat/`를 보고, 존재하는 MR에 "열린 MR이 없습니다"가 나온다.
  `fields`로 대체할 수 없다 — `-F` 값은 JSON 요청 **본문**으로 가고 쿼리
  직렬화는 `--input` 모드에서만 일어난다(glab 1.114로 확인). `urllib.parse.urlencode`를
  거치는 `query: dict[str, str]`를 추가해야 한다.
- **계획 3**: `local.push_error.status`를 채울 수 없고, `check=False`가 403·404·
  네트워크 장애를 모두 `None`으로 접는다. `draft_notes_available`은 이미 네트워크
  장애를 `draft_notes: false`로 기록한다. `glab api -i/--include`가 응답 헤더를
  출력하므로 `api()`를 `(status: int, data: Any)` 형태로 바꾸면 "실패"와 "성공했지만
  본문이 비었음"도 함께 구분된다.
- **`--input` 모드에는 `Content-Type` 을 직접 붙여야 한다** (2026-10-13 실측).
  `glab api --input -` 만 쓰면 GitLab이 `HTTP 415 The provided content-type '' is
  not supported` 를 돌려준다. `-H "Content-Type: application/json"` 을 함께 줘야
  한다. 그리고 `-F "position[new_line]=15"` 식 bracket 키는 중첩 JSON으로 가지
  않아 **GitLab이 조용히 무시한다** — 위치 코멘트를 만들려다 위치 없는 스레드를
  만들고도 성공 응답을 받는다. 위 `query: dict` 를 넣을 때 이 둘을 같이 처리할 것.

**R4. 가짜 `glab` 하네스가 페이지네이션과 상태 코드를 표현할 수 없다.**
`cli/tests/bin/glab`은 `"<METHOD> <path>"` 키마다 응답 파일 하나를 매핑한다.
따라서 2페이지 이상 응답, 같은 경로에 대한 호출별 다른 응답, HTTP 상태 코드를
만들 수 없다. `testing.md` §3이 요구하는 2페이지 픽스처가 이 때문에 빠져 있다.
계획 3의 push 멱등성·크래시 복구 테스트(`testing.md` §5)에 셋 다 필요하다.
`MRQ_GLAB_FAIL_AT`이 확장의 올바른 모양이다. R3과 같은 변경에서 함께 하는 것이 좋다.

**R5. 스레드가 응답에서 사라졌다 다시 나타나면 `local.*`가 영구 소실된다.**
`data-model.md` §6에 결정과 미루는 이유가 기록되어 있다. 완화책은 `local.reply`가
비어 있지 않거나 `state != todo`인 스레드를 제거하지 말고 "서버에서 사라짐"으로
표시만 하는 것이다. 그 표시를 렌더링·`status`·`push`가 어떻게 다룰지가 계획 2·3의
영역이라 미뤘다. `test_pull_drops_threads_removed_on_server`가 현재의 손실 동작을
고정하고 있으므로 완화책이 들어오면 그 테스트가 바뀐다.

**R8. 답글을 썼는데 상태가 `todo`면 조용히 전송되지 않는다.** `data-model.md` §4.7의
의도대로다(`todo` → push는 아무것도 하지 않음) — 그리고 `status`의 `push replies 0`이
그것을 알려준다. 다만 사람이 "답글을 썼으니 보내질 것"으로 읽기 쉬운 자리이므로,
`sync`가 "답글이 있는데 상태가 `todo`입니다 — 전송되지 않습니다"를 경고로 알리는 쪽이
낫다. 경고는 §7의 경고 목록에 한 행을 더하는 일이고 `push`의 동작은 그대로 둔다.
계획 3에서 `push`를 만들 때 함께 결정하면 된다.


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
