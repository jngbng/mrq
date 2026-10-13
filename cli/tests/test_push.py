import json
from pathlib import Path

import pytest

from mrq import discussions, model, push, store, surface
from mrq.__main__ import main

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


MR = {
    "iid": 1234,
    "title": "Add retry logic to API client",
    "web_url": "https://gitlab.example.com/g/p/-/merge_requests/1234",
    "state": "opened",
    "source_branch": "feat/retry",
}
FIXTURES = Path(__file__).parent / "fixtures"
NOTES = "POST projects/:fullpath/merge_requests/1234/discussions/{did}/notes"
RESOLVE = "PUT projects/:fullpath/merge_requests/1234/discussions/{did}"


@pytest.fixture
def pushable(git_repo, commit, checkout, glab, monkeypatch):
    """pull 이 끝난 상태 + 전송 라우트. 샘플 json 을 그대로 디스크에 둔다."""
    commit({"src/api/client.py": "def fetch(url):\n    resp = session.get(url)\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)

    review = _review()
    for thread in review.threads:
        # 샘플에는 미전송 답글이 섞여 있다. 테스트가 "무엇이 전송되는가" 를
        # 정확히 단언할 수 있도록 비운 뒤 각 테스트가 `set_local` 로 채운다.
        thread.local.state = "todo"
        thread.local.reply = ""
    with store.review_lock(git_repo, review.iid):
        surface.write(git_repo, review, include_resolved=True)
    store.write_current(git_repo, review.iid)

    # 재pull 과 스냅샷이 쓰는 읽기 라우트.
    glab.route("GET projects/:fullpath/merge_requests/1234", MR)
    glab.route(
        "GET projects/:fullpath",
        {
            "path_with_namespace": "group/sub/project",
            "permissions": {"project_access": {"access_level": 40}, "group_access": None},
        },
    )
    glab.route("GET user", {"id": 7, "username": "bongya"})
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/versions",
        [
            {
                "head_commit_sha": "abc1234",
                "base_commit_sha": "abc1234",
                "start_commit_sha": "abc1234",
            }
        ],
    )
    glab.route("GET projects/:fullpath/merge_requests/1234/draft_notes", [])
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        pages=[_snapshot_ndjson()],
    )
    return git_repo


def _snapshot_ndjson(
    *,
    bodies: dict[str, list[str]] | None = None,
    resolved: set[str] | None = None,
) -> str:
    """샘플 review.json 의 스레드를 GitLab discussions 응답 모양으로 되돌린다.

    스냅샷 비교(updated_at/note_count)가 성립해야 하므로 값을 샘플에서 그대로
    가져온다. `bodies` 로 특정 스레드에 2차 방어용 "이미 보낸 note" 를 둘 수
    있다 — 그 스레드는 **원본 노트를 대체한다**(추가하지 않는다). 추가하면
    `note_count` 가 샘플의 `server.note_count` 와 달라져 `push.plan` 이
    `server-changed` 로 먼저 건너뛰어 버리고 2차 방어(`_already_posted`)에
    닿지 못한다 — `discussions.to_threads` 가 실제로 세는 값(필터 후 notes 의
    길이)과 이 헬퍼가 만드는 값을 맞추기 위한 수정이다.

    `resolved` 로 특정 스레드를 "서버에서 이미 resolve 됐다" 로 강제할 수 있다
    — 실제 GitLab 은 resolve PUT 이 성공한 뒤의 조회에서 `resolved: true` 를
    돌려주지만, 샘플은 항상 고정값(`false`)이다. 연속 두 번의 `push` 가 같은
    스레드를 다루는 테스트(중복 resolve 방지)에서 "성공 전/후" 스냅샷을
    구분하는 데 쓴다.
    """
    out = []
    for thread in _review().threads:
        is_resolved = thread.id in (resolved or set()) or thread.server.resolved
        extra = (bodies or {}).get(thread.id)
        if extra:
            notes = [
                {
                    "id": 9000 + i,
                    "author": {"username": "bongya"},
                    "created_at": thread.server.updated_at,
                    "updated_at": thread.server.updated_at,
                    "body": body,
                    "resolvable": thread.server.resolvable,
                    "resolved": is_resolved,
                    "position": None,
                }
                for i, body in enumerate(extra)
            ]
        else:
            notes = [
                {
                    "id": thread.notes[0].id,
                    "author": {"username": thread.notes[0].author},
                    "created_at": thread.notes[0].created_at,
                    "updated_at": thread.server.updated_at,
                    "body": thread.notes[0].body,
                    "resolvable": thread.server.resolvable,
                    "resolved": is_resolved,
                    "position": None,
                }
            ]
        out.append(
            json.dumps(
                {
                    "id": thread.id,
                    "individual_note": not thread.server.repliable,
                    "notes": notes,
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(out) + "\n"


def _set_local(root: Path, thread_id: str, *, state: str, reply: str) -> None:
    path = store.review_json_path(root, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    target = next(t for t in review.threads if t.id == thread_id)
    target.local.state = state
    target.local.reply = reply
    store.atomic_write_text(path, model.dumps(review))


def _read(root: Path) -> model.Review:
    return model.loads(store.review_json_path(root, 1234).read_text(encoding="utf-8"))


def test_push_posts_reply_and_resolves(pushable, glab):
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


def test_push_sends_fenced_body_byte_for_byte(pushable, glab):
    # Review Focus 3. 코드 펜스·표·CRLF 가 섞인 답글이 그대로 가야 한다.
    body = (
        "다음과 같이 고쳤습니다\n\n```python\nif x:\n    pass\n```\n\n"
        "| 전 | 후 |\n|---|---|\n| 1 | 2 |"
    )
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply=body)
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)

    assert main(["push"]) == 0

    posted = [c for c in glab.calls() if c["argv"][1].endswith("/notes")][-1]
    assert posted["stdin"] == body


def test_push_twice_sends_nothing_the_second_time(pushable, glab):
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


def test_push_flushes_json_after_each_thread(pushable, glab):
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="첫 번째")
    _set_local(pushable, "b2c3d4e5f6a1", state="replied", reply="두 번째")
    glab.route(NOTES.format(did="a1b2c3d4e5f6"), {"id": 9001}, status=201)
    glab.route(NOTES.format(did="b2c3d4e5f6a1"), {"id": 9002}, status=201)
    # 호출 순서는 1 = discussions GET(스냅샷), 2 = 첫 POST, 3 = 두 번째 POST 다.
    # 가짜 glab 은 **로그에 기록한 뒤** 죽으므로 "요청은 갔는데 그 뒤에 실패"
    # 라는 모양이 된다 (testing.md §2).
    glab.fail_at(3)

    assert main(["push"]) == 4

    review = _read(pushable)
    first = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    second = next(t for t in review.threads if t.id == "b2c3d4e5f6a1")
    assert first.local.pushed_hash == push.body_hash("첫 번째")
    assert first.local.reply == ""
    # 죽은 쪽은 답글이 그대로 남아 재실행으로 복구된다.
    assert second.local.reply == "두 번째"


def test_push_records_second_defence_hash_without_posting(pushable, glab):
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


def test_push_demotes_state_and_records_error_on_resolve_403(pushable, glab):
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


def test_push_does_not_retry_resolve_after_demotion(pushable, glab):
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


def test_push_keeps_reply_when_post_fails(pushable, glab):
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


def test_push_refuses_on_a_different_branch(pushable, checkout, glab):
    _set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="보내야 한다")
    checkout("other/branch")

    assert main(["push"]) == 1

    assert not [
        c
        for c in glab.calls()
        if "--method" in c["argv"] and c["argv"][c["argv"].index("--method") + 1] in ("POST", "PUT")
    ]


def test_push_stops_on_sync_conflict_without_sending(pushable, glab):
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
