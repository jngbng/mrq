# 0012. draft 생성은 전송이 아니다

날짜: 2026-10-13 · 상태: 채택 (`cli.md` §9 의 `--draft` 절을 구체화)

## 배경

`push` 의 일반 경로는 답글 POST 가 성공하면 즉시 `pushed_hash` 를 기록하고
`local.reply` 를 비운다 (`cli.md` §9 4a). 비우는 것이 MUST 인 이유는 재pull 후
md 에 같은 답글이 인용과 reply 양쪽에 두 번 보이기 때문이다.

`--draft` 경로에 같은 규칙을 그대로 적용하면 두 가지가 깨진다.

1. draft 는 발행하지 않으면 **note 가 되지 않는다.** `local.reply` 를 비우면 그
   답글은 GitLab 의 내 draft 안에만 남고, 로컬에는 흔적이 없다. 사용자가 발행을
   잊거나 draft 를 UI 에서 지우면 자기 글을 잃는다.
2. 중복 방어가 한 겹뿐이다. 일반 경로는 `pushed_hash` 와 "스냅샷의 내 note 중
   같은 본문" 두 겹이지만, draft 는 아직 note 가 아니므로 `discussions` 스냅샷에
   나타나지 않는다.

## 결정

**draft 생성 시점에 `pushed_hash` 를 기록하지 않고 `local.reply` 도 비우지
않는다.** 둘은 `bulk_publish` 가 성공한 시점에만 갱신한다.

**중복 방어는 `GET draft_notes` 한 번이 전부다.** `(discussion_id, note)` 쌍을
비교해 같은 것이 있으면 생성을 생략한다. 이 조회가 실패하면 draft 를 만들지
않는다.

**resolve 는 `resolve_discussion` 으로 draft 에 묶는다.** 별도 `PUT discussions`
를 보내지 않는다.

**`--publish` 는 mrq 가 만들지 않은(foreign) draft 가 있으면 확인을 요구한다.**
**foreign 판정은 `discussion_id` 만 본다** — 이 리뷰의 스레드 id 와 일치하면
ours, 아니면(`discussion_id` 가 없는 경우를 포함) foreign 이다. body(note) 비교는
여기 쓰지 않는다 — draft 를 만든 뒤 사용자가 md 에서 답글을 고치면 body 가
달라지는데, 그걸로 ours/foreign 을 가르면 **자기 자신의 draft** 를 foreign 으로
잘못 보고 불필요한 확인을 요구하게 된다.

이 판정의 받아들인 결과: GitLab UI 에서 **mrq 가 추적하는 스레드 위에** 만든
draft 는 discussion_id 가 일치하므로 ours 로 분류되어 확인 없이 함께 발행되고,
그 본문이 그 스레드의 `local.reply` 를 비울 수 있다. 괜찮다 — `bulk_publish` 가
선택적 발행을 지원하지 않으므로 그 draft 는 ours 로 분류하든 안 하든 어차피
같이 나가고, 그것은 **같은 스레드의 같은 리뷰 라운드**이지 남의 작업이 아니다.
확인이 막아야 하는 것은 "모르는 별개의 작업이 같이 나가는 것" 이고, 이 경우는
그게 아니다.

발행 시점의 정리도 조건부다 — `local.reply` 는 **발행된 draft 본문과 현재 값이
같을 때만** 비운다. draft 를 만든 뒤 md 에서 답글을 고친 사용자의 수정을 지우지
않기 위해서다. `pushed_hash` 는 발행된 본문의 해시로 기록하므로, 고친 답글은
해시가 달라 다음 `push` 에서 정상 전송된다.

**발행 실패는 스레드 하나의 일이 아니다.** `bulk_publish` 는 선택적 발행이 없는
MR 전체 단위 호출이므로, 실패하면 이번에 발행하려던 내(ours) draft 전부의
스레드에 `push_error{op: "publish"}` 를 기록한다 — 임의의 스레드 하나에
떠넘기지 않는다.

**`pushed.replies`/`pushed.resolves` 는 실제로 나간 것만 센다.** draft 생성
단독은 전송이 아니므로 둘 다 `0` 이다. `--publish` 가 수행되면 발행된 draft 중
**ours** 의 수(및 그중 `resolve_discussion` 을 담은 것의 수)를 센다 — 전송
여부와 무관한 `push.plan` 의 판정(일반 경로의 미리보기용)과 섞이지 않는다.

**`--publish` 단독 뒤의 재pull 은 md 를 다시 그리지 않는다.** `--publish` 단독은
sync 를 건너뛰므로, 로컬 `review.md` 에 아직 `sync`되지 않은 사용자의 수정이
남아 있을 수 있다. 재pull 이 md 를 덮어쓰면 그 수정이 흔적 없이 사라진다 —
이 결정이 막으려는 것과 정확히 같은 손실이다. 대신 md 를 그대로 둔다. 발행된
draft 의 `touched_by` 는 `"push"` 이므로(`data-model.md` §5.2) 다음 `sync`는
이것을 충돌이 아니라 "md 적용" 으로 판정해 사용자의 수정을 받아들이고,
`pushed_hash` 는 발행된(옛) 본문의 해시라 새 본문과 달라 그 뒤의 `push` 가
정상 전송한다.

## 근거

**`local.reply` 를 비우는 비용과 남기는 비용이 비대칭이다.** 비우면 발행 전에
데이터가 사라지는 경로가 생긴다(복구 불가). 남기면 발행 후 재pull 까지의 짧은
구간에 md 에서 답글이 두 번 보인다(보기 문제, 다음 렌더에 사라진다). 전자가
비싸다.

**조회 실패 시 draft 를 만들지 않는 것이 MUST 인 이유.** 방어가 한 겹이므로
그것이 없는 상태의 생성은 재실행마다 draft 를 복제한다. 복제된 draft 는 mrq 가
지울 수 없고(수정·삭제는 범위 밖) 사용자가 GitLab UI 에서 손으로 정리해야 한다.
"보내지 못함" 은 재실행으로 회복되지만 "복제" 는 그렇지 않다.

**`bulk_publish` 는 선택적 발행을 지원하지 않는다.** 내 pending draft 전부를
발행한다. 따라서 사용자가 UI 에서 쓰던 미완성 리뷰가 함께 공개될 수 있다 —
바깥으로 나가고 되돌릴 수 없는 작업이므로 `mr_state != "opened"` 와 같은 모양의
확인을 요구한다. 자동으로 건너뛰는 선택지는 없다. `bulk_publish` 가 그 구분을
받지 않으므로, 할 수 있는 일은 "알리고 묻는 것" 뿐이다.

**draft 에 `PUT discussions` 를 섞지 않는 이유.** 묶는 것이 `--draft` 의 전부다.
resolve 만 즉시 반영하면 "발행하지 않았는데 스레드가 닫혀 있다" 는 상태가 되고,
리뷰 한 라운드를 통째로 보낸다는 의미가 사라진다.

## 대가

- draft 경로의 멱등성이 네트워크 한 번에 의존한다. 일반 경로의 두 겹보다 약하고,
  `GET draft_notes` 가 성공했지만 목록이 불완전한 경우(결손)는 막지 못한다.
  대안은 draft id 를 `local` 에 저장하는 것인데, 스키마 필드를 더하면서도 UI 에서
  지워진 draft 와 동기를 맞출 방법이 없어 기각했다
- `--publish` 가 확인을 요구하는 경우가 생긴다. 비대화형 사용에서는 `--force` 가
  필요하다
- 중복 방어의 키는 `(discussion_id, body)` 뿐이고 `resolve_discussion` 은 보지
  않는다. 답글 본문은 그대로인데 새로 resolve 가 필요해진 스레드는 이미 있는
  (resolve 없는) draft 에 가로막혀 조용히 생략된다 — draft 수정이 범위 밖이라
  고칠 수 없고, 이름을 대고 경고하는 것이 할 수 있는 전부다
- foreign 판정을 `discussion_id` 로 좁히면서, UI 에서 추적 중인 스레드에 만든
  draft 는 ours 로 분류되어 확인 없이 발행되고 그 본문이 `local.reply` 를 비울
  수 있게 됐다. 위 "받아들인 결과" 가 그 비용이 괜찮은 이유다
