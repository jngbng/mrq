from mrq import discussions, model, push

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"


def _review() -> model.Review:
    return model.loads(SAMPLE.read_text(encoding="utf-8"))


def _ready(review: model.Review, thread_id: str, *, state: str, reply: str = "") -> model.Thread:
    thread = next(t for t in review.threads if t.id == thread_id)
    thread.local.state = state
    thread.local.reply = reply
    return thread


def _blank(review: model.Review) -> model.Review:
    """샘플의 미전송 답글과 상태를 비운다.

    `testdata/review/rendered.json` 에는 `replied`/`done` + 답글이 섞여 있다
    (렌더러 테스트가 그것을 쓴다). 비우지 않으면 `sheet.replies == 0` 같은
    절대 수 단언이 그 스레드들 때문에 맞지 않는다 — 각 테스트가 필요한
    스레드만 채운다.
    """
    for thread in review.threads:
        thread.local.state = "todo"
        thread.local.reply = ""
        thread.local.pushed_hash = None
        thread.local.push_error = None
    return review


def test_plan_sends_reply_and_resolve_for_done_thread():
    review = _review()
    _ready(review, "a1b2c3d4e5f6", state="done", reply="확인했습니다")

    sheet = push.plan(review)

    decision = next(d for d in sheet.decisions if d.thread == "a1b2c3d4e5f6")
    assert decision.reply == "확인했습니다"
    assert decision.resolve is True
    assert decision.skip is None


def test_plan_does_not_resolve_a_replied_thread():
    review = _review()
    _ready(review, "a1b2c3d4e5f6", state="replied", reply="의견이 다릅니다")

    decision = next(d for d in push.plan(review).decisions if d.thread == "a1b2c3d4e5f6")

    assert decision.reply == "의견이 다릅니다"
    assert decision.resolve is False


def test_plan_ignores_whitespace_only_reply():
    # 빈 note 를 올리면 되돌릴 수 없다. 공백만인 답글은 전송 대상이 아니고
    # pushed_hash 도 쓰지 않는다 (Review Focus 2).
    review = _blank(_review())
    _ready(review, "a1b2c3d4e5f6", state="replied", reply="   \n\t\n")

    sheet = push.plan(review)

    assert all(d.thread != "a1b2c3d4e5f6" for d in sheet.decisions)
    assert sheet.replies == 0


def test_plan_skips_individual_note_with_no_reply_reason():
    review = _review()
    _ready(review, "7a0b1c2d3e4f", state="replied", reply="보낼 수 없는 답글")

    sheet = push.plan(review)

    decision = next(d for d in sheet.decisions if d.thread == "7a0b1c2d3e4f")
    assert decision.skip == "no-reply"
    assert decision.reply == ""
    assert {"thread": "7a0b1c2d3e4f", "reason": "no-reply"} in sheet.warnings
    assert sheet.skip == 1


def test_plan_skips_missing_thread_even_with_force():
    review = _review()
    thread = _ready(review, "a1b2c3d4e5f6", state="done", reply="보낼 답글")
    thread.server.missing = True

    sheet = push.plan(review, force=True)

    decision = next(d for d in sheet.decisions if d.thread == "a1b2c3d4e5f6")
    assert decision.skip == "server-missing"
    assert decision.reply == ""
    assert decision.resolve is False


def test_plan_first_defence_skips_already_pushed_body():
    # 표본에는 애초에 다른 스레드 둘(c3d4e5f6a1b2, d4e5f6a1b2c3)에도 미전송
    # 답글이 섞여 있다 — 비우지 않으면 `replies == 0` 이 그 스레드들 때문에
    # 거짓이 된다.
    review = _blank(_review())
    thread = _ready(review, "a1b2c3d4e5f6", state="replied", reply="이미 보냈다")
    thread.local.pushed_hash = push.body_hash("이미 보냈다")

    sheet = push.plan(review)

    assert sheet.replies == 0
    assert all(d.thread != "a1b2c3d4e5f6" for d in sheet.decisions)


def test_plan_second_defence_records_hash_without_sending():
    review = _review()
    _ready(review, "a1b2c3d4e5f6", state="replied", reply="보낸 뒤 죽었다")
    snapshot = _review().threads
    target = next(t for t in snapshot if t.id == "a1b2c3d4e5f6")
    target.notes.append(
        model.Note(
            id=9001,
            author="bongya",
            created_at="2026-10-13T12:00:00.000Z",
            updated_at="2026-10-13T12:00:00.000Z",
            body="보낸 뒤 죽었다\n",  # GitLab 이 끝 공백을 다듬어 돌려줄 수 있다
            mine=True,
        )
    )
    # 같은 함수로 계산한 지문이어야 한다 — 스냅샷에 note 가 하나 늘었으므로
    # 그 변화는 server-changed 로 보이지 않게 로컬 쪽도 맞춰 둔다.
    target.server.note_count = len(target.notes)
    local = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    local.server.note_count = target.server.note_count

    decision = next(
        d for d in push.plan(review, snapshot=snapshot).decisions if d.thread == "a1b2c3d4e5f6"
    )

    assert decision.reply == ""
    assert decision.record_hash == push.body_hash("보낸 뒤 죽었다")


def test_plan_skips_server_changed_thread_unless_forced():
    review = _review()
    _ready(review, "a1b2c3d4e5f6", state="done", reply="보낼 답글")
    snapshot = _review().threads
    next(t for t in snapshot if t.id == "a1b2c3d4e5f6").server.note_count = 5

    skipped = next(
        d for d in push.plan(review, snapshot=snapshot).decisions if d.thread == "a1b2c3d4e5f6"
    )
    forced = next(
        d
        for d in push.plan(review, snapshot=snapshot, force=True).decisions
        if d.thread == "a1b2c3d4e5f6"
    )

    assert skipped.skip == "server-changed"
    assert skipped.reply == ""
    assert forced.skip is None
    assert forced.reply == "보낼 답글"


def test_plan_does_not_skip_a_thread_that_only_gained_a_system_note():
    # 시스템 노트는 pull 과 스냅샷 양쪽에서 제외되므로 updated_at·note_count 가
    # 움직이지 않는다 (testing.md §5 첫 행).
    review = _review()
    _ready(review, "a1b2c3d4e5f6", state="done", reply="보낼 답글")
    raw = [
        {
            "id": "a1b2c3d4e5f6",
            "individual_note": False,
            "notes": [
                {
                    "id": 5566,
                    "author": {"username": "jdoe"},
                    "created_at": "2026-10-05T06:30:00.000Z",
                    "updated_at": "2026-10-05T06:30:00.000Z",
                    "body": "타임아웃 설정이 빠졌습니다.",
                    "resolvable": True,
                    "resolved": False,
                },
                {
                    "id": 5567,
                    "system": True,
                    "author": {"username": "park"},
                    "created_at": "2026-10-13T06:30:00.000Z",
                    "updated_at": "2026-10-13T06:30:00.000Z",
                    "body": "changed the description",
                    "resolvable": False,
                    "resolved": False,
                },
            ],
        }
    ]
    snapshot = discussions.to_threads(raw, "bongya")

    decision = next(
        d for d in push.plan(review, snapshot=snapshot).decisions if d.thread == "a1b2c3d4e5f6"
    )

    assert decision.skip is None
    assert decision.reply == "보낼 답글"


def test_plan_drops_resolve_without_permission_and_warns_once():
    review = _blank(_review())
    review.me.can_resolve = False
    _ready(review, "a1b2c3d4e5f6", state="done", reply="보낼 답글")
    _ready(review, "b2c3d4e5f6a1", state="done", reply="또 하나")

    sheet = push.plan(review)

    assert sheet.resolves == 0
    assert sheet.replies == 2
    assert sheet.warnings.count({"thread": None, "reason": "no-resolve-permission"}) == 1


def test_plan_resolve_skip_mode_sends_reply_only():
    review = _blank(_review())
    _ready(review, "a1b2c3d4e5f6", state="done", reply="보낼 답글")

    sheet = push.plan(review, resolve="skip")

    decision = next(d for d in sheet.decisions if d.thread == "a1b2c3d4e5f6")
    assert decision.resolve is False
    assert decision.reply == "보낼 답글"
    # 요청하지 않은 일은 실패도 skip 도 아니다 (cli.md §9).
    assert sheet.skip == 0


def test_plan_resolve_only_without_permission_survives_as_decision():
    # Important 2 — reply 가 없는 resolve-only 스레드가 권한 부족으로 막히면
    # Decision 의 모든 필드가 falsy 해져 `decisions` 에서 통째로 사라졌다.
    # `no-resolve-permission` 을 skip 이유로 남겨 살아 있어야 한다 — 그래야
    # `push --dry-run` 이 그 스레드를 보여줄 수 있다. 집계 `skip` 수는 그래도
    # 늘지 않는다(cli.md §8 은 세 가지로 한정한다).
    review = _blank(_review())
    review.me.can_resolve = False
    _ready(review, "a1b2c3d4e5f6", state="done")  # reply 없음 — resolve 만 요청

    sheet = push.plan(review)

    decision = next(d for d in sheet.decisions if d.thread == "a1b2c3d4e5f6")
    assert decision.skip == "no-resolve-permission"
    assert decision.resolve is False
    assert decision.reply == ""
    assert sheet.skip == 0
    assert sheet.resolves == 0
    assert sheet.pending_resolves == 1


def test_plan_retracts_superseded_warning_when_thread_goes_missing():
    # Minor 4 — no-reply 로 먼저 경고를 낸 뒤 같은 스레드가 server-missing 으로
    # 판정되면 앞선 경고는 철회해야 한다. 안 그러면 한 스레드에 이유가 둘
    # 찍히는데 skip 수는 하나뿐이라 어긋나 보인다.
    review = _review()
    thread = _ready(review, "7a0b1c2d3e4f", state="replied", reply="보낼 수 없는 답글")
    thread.server.missing = True

    sheet = push.plan(review)

    decision = next(d for d in sheet.decisions if d.thread == "7a0b1c2d3e4f")
    assert decision.skip == "server-missing"
    assert {"thread": "7a0b1c2d3e4f", "reason": "server-missing"} in sheet.warnings
    assert {"thread": "7a0b1c2d3e4f", "reason": "no-reply"} not in sheet.warnings


def test_plan_snapshot_absence_yields_server_missing_even_without_the_flag():
    # Minor 6a — push 시점의 server-missing 은 저장된 `server.missing` 플래그가
    # 아니라 스냅샷에 그 스레드가 없다는 사실에서도 나온다(cli.md §9 3단계 1행).
    review = _review()
    _ready(review, "a1b2c3d4e5f6", state="done", reply="보낼 답글")
    snapshot = [t for t in _review().threads if t.id != "a1b2c3d4e5f6"]

    decision = next(
        d for d in push.plan(review, snapshot=snapshot).decisions if d.thread == "a1b2c3d4e5f6"
    )

    assert decision.skip == "server-missing"
    assert decision.reply == ""
    assert decision.resolve is False


def test_plan_force_does_not_bypass_second_defence_for_already_posted_body():
    # Minor 6b — `--force` 가 무시하는 것은 "서버가 바뀌었다" 뿐이다. 이미
    # 보낸 본문을 다시 보내는 것은 force 로도 켜지지 않는다 — 2차 방어는
    # changed 검사 바로 아래에 있고 force 와 무관하게 늘 적용된다.
    review = _review()
    _ready(review, "a1b2c3d4e5f6", state="replied", reply="이미 서버에 있다")
    snapshot = _review().threads
    target = next(t for t in snapshot if t.id == "a1b2c3d4e5f6")
    target.notes.append(
        model.Note(
            id=9002,
            author="bongya",
            created_at="2026-10-13T12:00:00.000Z",
            updated_at="2026-10-13T12:00:00.000Z",
            body="이미 서버에 있다",
            mine=True,
        )
    )
    target.server.note_count = len(target.notes)
    local = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    local.server.note_count = target.server.note_count

    decision = next(
        d
        for d in push.plan(review, snapshot=snapshot, force=True).decisions
        if d.thread == "a1b2c3d4e5f6"
    )

    assert decision.reply == ""
    assert decision.record_hash == push.body_hash("이미 서버에 있다")


def test_plan_decision_skip_is_per_action_not_per_thread():
    # Minor 6c — repliable=False 지만 resolvable=True 인 done 스레드는 reply 는
    # no-reply 로 막히고 resolve 는 그대로 진행된다. skip 필드는 "이 스레드가
    # 통째로 막혔다" 가 아니라 "이 중 한 액션이 막혔다" 를 뜻한다
    # (Decision.skip 문서 참조).
    review = _review()
    thread = _ready(review, "a1b2c3d4e5f6", state="done", reply="못 보내는 답글")
    thread.server.repliable = False

    decision = next(d for d in push.plan(review).decisions if d.thread == "a1b2c3d4e5f6")

    assert decision.skip == "no-reply"
    assert decision.reply == ""
    assert decision.resolve is True


def test_plan_warns_about_recorded_push_error_and_todo_reply():
    review = _review()
    stale = next(t for t in review.threads if t.id == "b2c3d4e5f6a1")
    stale.local.push_error = {
        "op": "resolve",
        "status": 403,
        "reason": "forbidden",
        "retryable": False,
        "at": "2026-10-13T10:02:00+09:00",
        "message": "403 Forbidden",
    }
    _ready(review, "f6a1b2c3d4e5", state="todo", reply="초안")

    sheet = push.plan(review)

    assert {"thread": "b2c3d4e5f6a1", "reason": "push-failed"} in sheet.warnings
    assert {"thread": "f6a1b2c3d4e5", "reason": "todo-with-reply"} in sheet.warnings
