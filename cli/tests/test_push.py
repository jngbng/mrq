import json
from pathlib import Path

import pytest

from mrq import discussions, model, push, store, surface, transport
from mrq.__main__ import main
from mrq.errors import GlabError
from tests.pushkit import blank as _blank
from tests.pushkit import pushable  # noqa: F401
from tests.pushkit import read as _read
from tests.pushkit import review as _review
from tests.pushkit import set_local as _set_local
from tests.pushkit import snapshot_ndjson as _snapshot_ndjson


def _ready(review: model.Review, thread_id: str, *, state: str, reply: str = "") -> model.Thread:
    thread = next(t for t in review.threads if t.id == thread_id)
    thread.local.state = state
    thread.local.reply = reply
    return thread


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


def test_plan_keeps_both_reasons_when_reply_and_resolve_are_blocked_differently():
    # 라운드 2 Important — no-reply 로 reply 가 막히면서 resolve 가 독립적으로
    # 권한 부족으로 막히면 두 이유가 모두 살아 있어야 한다. 단일 슬롯이었을
    # 때는 먼저 걸린 no-reply 가 `or` 로 권한 이유를 지워 pending_resolves 와
    # 경고가 조용히 0 이 됐다.
    review = _blank(_review())
    review.me.can_resolve = False
    thread = _ready(review, "a1b2c3d4e5f6", state="done", reply="못 보내는 답글")
    thread.server.repliable = False

    sheet = push.plan(review)

    decision = next(d for d in sheet.decisions if d.thread == "a1b2c3d4e5f6")
    assert set(decision.skips) == {"no-reply", "no-resolve-permission"}
    assert decision.reply == ""
    assert decision.resolve is False
    assert sheet.pending_resolves == 1
    assert {"thread": "a1b2c3d4e5f6", "reason": "no-reply"} in sheet.warnings
    assert {"thread": None, "reason": "no-resolve-permission"} in sheet.warnings
    # no-reply 가 세 가지 집계 이유(cli.md §8) 중 하나이므로 스레드 하나로
    # 한 번만 센다 — no-resolve-permission 과 동시에 걸려도 두 번이 아니다.
    assert sheet.skip == 1


def test_plan_retracts_superseded_warning_when_server_changed_overrides_no_reply():
    # 라운드 2 Minor — server-changed 도 server-missing 과 똑같이 앞서 쌓인
    # no-reply/not-resolvable 경고를 철회해야 한다. 새 구조에서는 "스레드
    # 단위 이유는 skips 를 통째로 교체한다" 는 한 규칙이 server-missing 과
    # server-changed 둘 다 해결한다 — 두 번째 특별 케이스가 아니다.
    review = _review()
    _ready(review, "7a0b1c2d3e4f", state="replied", reply="보낼 수 없는 답글")
    snapshot = _review().threads
    next(t for t in snapshot if t.id == "7a0b1c2d3e4f").server.note_count = 99

    sheet = push.plan(review, snapshot=snapshot)

    decision = next(d for d in sheet.decisions if d.thread == "7a0b1c2d3e4f")
    assert decision.skips == ("server-changed",)
    assert {"thread": "7a0b1c2d3e4f", "reason": "no-reply"} not in sheet.warnings


def test_decision_skip_display_precedence_is_pinned():
    # not-resolvable + 권한 부족은 plan() 으로는 만들 수 없다(둘 다 resolve
    # 액션의 이유라 같은 if/else 에서 배타적이다) — 표시 우선순위 자체를
    # 주석이 아니라 테스트로 고정한다.
    assert push.Decision(thread="x", skips=("not-resolvable", "no-resolve-permission")).skip == (
        "not-resolvable"
    )
    assert push.Decision(thread="x", skips=("no-resolve-permission", "no-reply")).skip == "no-reply"
    assert push.Decision(thread="x", skips=("server-changed", "no-reply")).skip == "server-changed"
    assert (
        push.Decision(thread="x", skips=("server-missing", "server-changed")).skip
        == "server-missing"
    )
    assert push.Decision(thread="x").skip is None


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


FIXTURES = Path(__file__).parent / "fixtures"
NOTES = "POST projects/:fullpath/merge_requests/1234/discussions/{did}/notes"
RESOLVE = "PUT projects/:fullpath/merge_requests/1234/discussions/{did}"


def test_push_posts_reply_and_resolves(pushable, glab):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(RESOLVE.format(did="a1b2c3d4e5f6"), {"id": "a1b2c3d4e5f6"})

    assert main(["push"]) == 0

    # `"notes" in path` 는 `draft_notes`(repull 이 `pull` 의 일부로 조회하는
    # 가용성 체크) 까지 걸려든다 — `/notes` 로 끝나는 것만 골라야 답글 POST
    # 만 남는다.
    posted = [c for c in glab.calls() if c["argv"][1].endswith("/notes")]
    assert len(posted) == 1
    assert posted[0]["stdin"] == "확인했습니다"
    review = _read(pushable)
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    # 전송 성공 시 reply 를 비운다(MUST) — 비우지 않으면 재pull 후 md 에 같은
    # 답글이 인용과 reply 양쪽에 두 번 보인다.
    assert target.local.reply == ""
    assert target.local.pushed_hash == push.body_hash("확인했습니다")
    assert target.local.push_error is None
    assert target.local.touched_by == "push"


def test_push_sends_fenced_body_byte_for_byte(pushable, glab):  # noqa: F811
    # Review Focus 3. 코드 펜스·표·CRLF 가 섞인 답글이 그대로 가야 한다. 펜스
    # 내부는 실제 CRLF 로 둬 LF 와 섞인 본문이 그대로(변환 없이) 전송되는지도
    # 검증한다 — 리뷰가 "주석이 약속한 것과 리터럴이 다르다" 고 지적한 지점.
    body = (
        "다음과 같이 고쳤습니다\n\n```python\r\nif x:\r\n    pass\r\n```\n\n"
        "| 전 | 후 |\n|---|---|\n| 1 | 2 |"
    )
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply=body)
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)

    assert main(["push"]) == 0

    posted = [c for c in glab.calls() if c["argv"][1].endswith("/notes")][-1]
    assert posted["stdin"] == body


def test_push_twice_sends_nothing_the_second_time(pushable, glab):  # noqa: F811
    # Review Focus 4 + PRD 의 "중복 전송 0건".
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(RESOLVE.format(did="a1b2c3d4e5f6"), {"id": "a1b2c3d4e5f6"})
    # 실제 GitLab 은 resolve PUT 이 성공한 뒤의 조회에서 resolved:true 를
    # 돌려준다. `pushable` 의 고정 스냅샷 하나로는 그 변화를 표현할 수 없으므로
    # (resolve 가 성공하기 전/후를 구분해야 한다) 이 테스트에서만 순서를 바꿔
    # 등록한다 — 1 번째 조회(이번 push 의 사전 판정)는 미해결, 그 뒤로는 해결됨.
    glab.route_seq(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        [
            {"pages": [_snapshot_ndjson()]},
            {"pages": [_snapshot_ndjson(resolved={"a1b2c3d4e5f6"})]},
        ],
    )
    assert main(["push"]) == 0

    assert main(["push"]) == 0

    writes = [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]
    # 첫 push 의 POST 1 + PUT 1 이 전부여야 한다.
    assert len(writes) == 2, "두 번째 push 가 쓰기 요청을 다시 보냈다"


def test_push_flushes_json_after_each_thread(pushable, glab, monkeypatch):  # noqa: F811
    # Important 2 — `glab.fail_at` 로 두 번째 POST 를 "exit 1" 시키면 `_send`
    # 가 그 실패를 잡아 루프를 끝까지 돈다. 그 경로는 루프가 끝난 뒤 한 번만
    # flush 해도 디스크 결과가 바이트 단위로 같아, "스레드마다 flush 한다" 는
    # MUST 를 실제로는 검증하지 못한다. 대신 두 번째 스레드에서 **진짜로
    # 죽어서**(비정상 예외가 `_send` 를 빠져나간다) 그 뒤로는 아무것도 쓰지
    # 않는 경로와 "루프 안에서 매번 쓴다" 는 경로를 구분한다. `transport`
    # 자체를 패치하는 것은 네트워크 경계(가짜 glab)를 건너뛰는 것이 아니다 —
    # 가짜 glab 의 어떤 응답으로도 "프로세스가 죽었다" 를 표현할 수 없으므로
    # 여기서만 그 모양을 만든다.
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="첫 번째")
    _set_local(pushable, "b2c3d4e5f6a1", state="replied", reply="두 번째")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)

    original_post_reply = transport.post_reply

    def _die_on_second_thread(iid, discussion_id, body):
        if discussion_id == "b2c3d4e5f6a1":
            raise RuntimeError("프로세스가 죽었다")
        return original_post_reply(iid, discussion_id, body)

    monkeypatch.setattr(transport, "post_reply", _die_on_second_thread)

    with pytest.raises(RuntimeError):
        main(["push"])

    review = _read(pushable)
    first = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    second = next(t for t in review.threads if t.id == "b2c3d4e5f6a1")
    # 첫 스레드는 완전히 끝나 flush 됐다 — 두 번째가 죽기 **전** 디스크에
    # 반영됐다는 뜻이고, 루프가 끝난 뒤 한 번만 쓰는 구현이었다면 이 값들은
    # 전부 죽기 전 상태(빈 pushed_hash, 원래 reply)로 남아 있어야 한다.
    assert first.local.pushed_hash == push.body_hash("첫 번째")
    assert first.local.reply == ""
    # 죽은 쪽은 답글이 그대로 남아 재실행으로 복구된다.
    assert second.local.reply == "두 번째"


def test_push_records_second_defence_hash_without_posting(pushable, glab):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="이미 올라갔다")
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        pages=[_snapshot_ndjson(bodies={"a1b2c3d4e5f6": ["이미 올라갔다\n"]})],
    )

    assert main(["push"]) == 0

    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] == "POST"
    ]
    target = next(t for t in _read(pushable).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.pushed_hash == push.body_hash("이미 올라갔다")
    assert target.local.reply == ""


def test_push_demotes_state_and_records_error_on_resolve_403(pushable, glab):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(
        RESOLVE.format(did="a1b2c3d4e5f6"),
        raw='{"message":"403 Forbidden"}',
        status=403,
    )

    assert main(["push"]) == 4

    target = next(t for t in _read(pushable).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.state == "replied"
    assert target.local.push_error["op"] == "resolve"
    assert target.local.push_error["status"] == 403
    assert target.local.push_error["reason"] == "forbidden"
    assert target.local.push_error["retryable"] is False
    # 답글은 성공했으므로 비워져 있고 다시 보내지 않는다.
    assert target.local.reply == ""


def test_push_does_not_retry_resolve_after_demotion(pushable, glab):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(
        RESOLVE.format(did="a1b2c3d4e5f6"),
        raw='{"message":"403 Forbidden"}',
        status=403,
    )
    assert main(["push"]) == 4

    assert main(["push"]) == 0

    puts = [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] == "PUT"
    ]
    assert len(puts) == 1, "강등된 뒤에도 resolve 를 재시도했다 — 루프가 열려 있다"


def test_push_keeps_reply_when_post_fails(pushable, glab):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="보내야 한다")
    glab.route(
        NOTES.format(did="a1b2c3d4e5f6"),
        raw='{"message":"502 Bad Gateway"}',
        status=502,
    )

    assert main(["push"]) == 4

    target = next(t for t in _read(pushable).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.reply == "보내야 한다"
    assert target.local.pushed_hash is None
    assert target.local.push_error["op"] == "reply"
    assert target.local.push_error["retryable"] is True


def test_push_does_not_resolve_when_reply_fails(pushable, glab, capsys):  # noqa: F811
    # Important 1 — "done" + reply 는 POST 와 PUT 둘 다를 만든다. POST 가
    # 실패하면 그 스레드는 아직 "done" 이 아니므로 resolve 를 시도하면 안
    # 된다 — 리뷰어가 "답글 없이 닫힌 스레드" 를 보게 된다. resolve 가 성공해
    # `push_error = None` 으로 되돌리면 §9 가 요구하는 reply 실패 기록도
    # 사라져 `status` 의 `push-failed` 경고가 다시는 뜨지 않는다.
    #
    # Important 3 — `_report` 가 `sheet.resolves`(계획) 에서 실패 건수를 빼
    # `pushed.resolves` 를 재구성하면, resolve 를 **시도조차 하지 않았는데도**
    # 계획에 잡혀 있던 1 건이 그대로 "보냈다" 로 보고된다. 실제로 나간 건수를
    # `_send` 가 직접 세어 돌려줘야 한다.
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(
        NOTES.format(did="a1b2c3d4e5f6"),
        raw='{"message":"502 Bad Gateway"}',
        status=502,
    )
    # 성공했을 resolve 라우트 — 그래도 호출되면 안 된다.
    glab.route(RESOLVE.format(did="a1b2c3d4e5f6"), {"id": "a1b2c3d4e5f6"})

    assert main(["push", "--json"]) == 4

    puts = [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] == "PUT"
    ]
    assert not puts, "답글이 실패했는데도 resolve 를 시도했다"
    target = next(t for t in _read(pushable).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.push_error["op"] == "reply"
    payload = json.loads(capsys.readouterr().out)
    # resolve 는 시도조차 하지 않았다 — 계획에는 1건 있었지만 실제로 나간
    # 것은 0건이어야 한다. 리뷰어가 "답글 없이 닫혔다" 는 실제로 일어나지
    # 않은 일을 봤다고 믿게 하면 안 된다(cli.md §8).
    assert payload["pushed"] == {"replies": 0, "resolves": 0}
    assert target.local.reply == "확인했습니다"


def test_push_refuses_on_a_different_branch(pushable, checkout, glab):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="보내야 한다")
    checkout("other/branch")

    assert main(["push"]) == 1

    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]


def test_push_stops_on_sync_conflict_without_sending(pushable, glab):  # noqa: F811
    # md 와 CLI 가 같은 스레드를 다르게 고친 상태를 만든다.
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="json 쪽")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.touched_by = "cli"
    target.local.touched_at = surface.now()
    store.atomic_write_text(path, model.dumps(review))
    md_path = store.review_md_path(pushable, 1234)
    text = md_path.read_text(encoding="utf-8")
    marker = text.index("### reply", text.index("<!-- mrq:a1b2c3d4e5f6"))
    md_path.write_text(
        text[: marker + len("### reply")] + "\n\nmd 쪽\n" + text[marker + len("### reply") :],
        encoding="utf-8",
    )

    assert main(["push"]) == 3

    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]


def test_push_resolve_require_without_permission_refuses_before_sending(pushable, glab):  # noqa: F811
    # Minor 4 — §9 는 `require` 에 권한이 없으면 "push 를 시작하지 않고 exit 1"
    # 이라고 쓴다. sync(mdsync.perform) 보다 앞서 끊어야 글자 그대로 맞는다.
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    review.me.can_resolve = False
    store.atomic_write_text(path, model.dumps(review))

    assert main(["push", "--resolve", "require"]) == 1

    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]


def test_push_failed_repull_does_not_override_send_result(pushable, glab, monkeypatch):  # noqa: F811
    # Minor 6a — repull(§9 5단계) 이 실패해도 전송 결과는 이미 json 에 있다
    # (MUST). `discussions.fetch` 를 두 번째 호출(=repull 의 조회)에서만
    # 실패시켜 push 자신의 사전 판정은 그대로 두고 repull 만 네트워크 실패로
    # 만든다.
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(RESOLVE.format(did="a1b2c3d4e5f6"), {"id": "a1b2c3d4e5f6"})

    original_fetch = discussions.fetch
    calls = {"n": 0}

    def _fail_second_fetch(iid):
        calls["n"] += 1
        if calls["n"] == 2:
            raise GlabError("네트워크 실패", status=None)
        return original_fetch(iid)

    monkeypatch.setattr(discussions, "fetch", _fail_second_fetch)

    assert main(["push"]) == 0

    target = next(t for t in _read(pushable).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.reply == ""
    assert target.local.pushed_hash == push.body_hash("확인했습니다")


def test_push_returns_parse_error_without_sending(pushable, glab):  # noqa: F811
    # Minor 6b — review.md 파싱 에러는 exit 2 이고 아무것도 쓰지 않는다
    # (닫히지 않은 코드 펜스가 트리거다, cli.md §5).
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="답글")
    md_path = store.review_md_path(pushable, 1234)
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(text + "\n```python\nif True:\n    pass\n", encoding="utf-8")

    assert main(["push"]) == 2

    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]


def test_push_json_keeps_stdout_as_a_single_json_object(pushable, glab, capsys):  # noqa: F811
    # Important 3 — repull(=pull.run) 이 사람용 요약 두 줄을 stdout 에 찍는다.
    # `--json` 일 때 그 줄이 `_report` 의 JSON 객체와 함께 stdout 에 섞이면
    # cli.md §2 의 "stdout 은 순수 JSON 객체 하나" 를 깬다.
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(RESOLVE.format(did="a1b2c3d4e5f6"), {"id": "a1b2c3d4e5f6"})

    assert main(["push", "--json"]) == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["pushed"]["replies"] == 1


def test_dry_run_lists_targets_and_sends_nothing(pushable, glab, capsys):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    _set_local(pushable, "7a0b1c2d3e4f", state="replied", reply="개별 노트라 못 보낸다")

    assert main(["push", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "a1b2c3d4" in out
    assert "reply" in out and "resolve" in out
    assert "skip  no-reply" in out
    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]


def test_dry_run_location_column_shows_server_missing_badge(pushable, glab, capsys):  # noqa: F811
    # Minor 7 — `--dry-run`의 위치 칼럼(`_where`)이 `review.md` 헤더
    # (`render.header_line`)와 같은 배지 규칙을 쓰지 않아 `server-missing`
    # 배지가 빠져 있었다. 공유 헬퍼(`render.where`)를 거치게 고친 뒤에는
    # 위치 칼럼에도 그 배지가 보여야 한다.
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="보낼 답글")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.server.missing = True
    store.atomic_write_text(path, model.dumps(review))

    assert main(["push", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "a1b2c3d4" in out
    assert "server-missing" in out
    assert "`server-missing`" in out


def test_dry_run_json_is_the_only_thing_on_stdout(pushable, capsys):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")

    assert main(["push", "--dry-run", "--json"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)  # 섞인 것이 있으면 여기서 터진다
    assert payload["push"]["replies"] == 1
    assert payload["push"]["resolves"] == 1


def test_push_json_reports_failures_with_retryable(pushable, glab, capsys):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(
        RESOLVE.format(did="a1b2c3d4e5f6"),
        raw='{"message":"403 Forbidden"}',
        status=403,
    )

    assert main(["push", "--json"]) == 4

    payload = json.loads(capsys.readouterr().out)
    assert payload["pushed"] == {"replies": 1, "resolves": 0}
    assert payload["failures"] == [
        {
            "thread": "a1b2c3d4e5f6",
            "op": "resolve",
            "status": 403,
            "reason": "forbidden",
            "retryable": False,
        }
    ]


def test_push_with_nothing_to_send_is_success(pushable, glab, capsys):  # noqa: F811
    # Review Focus 5. 빈 결과를 실패로 보고하면 안 된다.
    assert main(["push"]) == 0

    assert "보낼 것이 없습니다" in capsys.readouterr().out


def test_push_refuses_merged_mr_without_force(pushable, glab, monkeypatch, capsys):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="확인했습니다")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    review.mr_state = "merged"
    store.atomic_write_text(path, model.dumps(review))
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    # 비대화형이므로 묻지 않고 거부한다 — AI 가 부르는 경로에서 input() 이
    # 블로킹되면 세션이 멈춘다.
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["push"]) == 1
    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] == "POST"
    ]

    assert main(["push", "--force"]) == 0


def test_resolve_auto_without_permission_is_exit_zero(pushable, glab, capsys):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    review.me.can_resolve = False
    store.atomic_write_text(path, model.dumps(review))
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(
        "GET projects/:fullpath",
        {
            "path_with_namespace": "group/sub/project",
            "permissions": {"project_access": {"access_level": 20}, "group_access": None},
        },
    )

    # 요청하지 않은 일은 실패가 아니다 (cli.md §9).
    assert main(["push"]) == 0


def test_resolve_require_without_permission_sends_nothing(pushable, glab):  # noqa: F811
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    review.me.can_resolve = False
    store.atomic_write_text(path, model.dumps(review))

    assert main(["push", "--resolve", "require"]) == 1

    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] == "POST"
    ]


def test_dry_run_on_unopened_mr_shows_preview_without_force(pushable, glab, capsys):  # noqa: F811
    # dry-run 은 mr_state 확인보다 먼저다 — merged MR 에서도 --force 없이
    # 미리보기를 볼 수 있어야 한다(확인 절차 자체가 전송 전용이므로). 이
    # 스레드는 reply 와 no-resolve-permission skip 을 동시에 가진다 — 한쪽
    # 액션(reply)은 보내지고 다른 쪽(resolve)만 막히는 조합이 "skip" 한 줄로만
    # 찍혀 보낼 게 없는 것처럼 보이면, 다음 실제 push 가 그 reply 를 보낸다.
    _set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    review.mr_state = "merged"
    review.me.can_resolve = False
    store.atomic_write_text(path, model.dumps(review))

    assert main(["push", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "a1b2c3d4" in out
    assert "reply" in out
    assert "no-resolve-permission" in out
    # "skip" 단독 줄이 아니라 reply 와 같은 줄에 덧붙어야 한다 — 순수 skip
    # 줄의 시작 모양("<id>  skip  ...")이 아님을 확인한다.
    assert "a1b2c3d4  skip" not in out
    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]


def test_push_json_payloads_validate_against_the_contract(pushable, glab, capsys):  # noqa: F811
    # cli.md §9 의 페이로드 모양. 키가 바뀌면 에디터와 AI 가 조용히 깨진다.
    assert main(["push", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"pushed", "failures"}
    assert set(payload["pushed"]) == {"replies", "resolves"}
