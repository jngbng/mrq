import json

from mrq import model, store
from mrq.__main__ import main
from tests.pushkit import DRAFTS, PUBLISH, pushable, read, set_local  # noqa: F401


def test_draft_bundles_reply_and_resolve(pushable, glab):  # noqa: F811
    set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(f"GET {DRAFTS}", [])
    glab.route(f"POST {DRAFTS}", {"id": 5}, status=201)

    assert main(["push", "--draft"]) == 0

    created = [c for c in glab.calls() if "draft_notes" in c["argv"][1] and "--method" in c["argv"]]
    posted = [c for c in created if c["argv"][c["argv"].index("--method") + 1] == "POST"]
    assert len(posted) == 1
    assert posted[0]["stdin"] == "확인했습니다"
    assert "in_reply_to_discussion_id=a1b2c3d4e5f6" in posted[0]["argv"]
    assert "resolve_discussion=true" in posted[0]["argv"]
    # draft 는 전송이 아니다 — reply 와 pushed_hash 를 건드리지 않는다.
    target = next(t for t in read(pushable).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.reply == "확인했습니다"
    assert target.local.pushed_hash is None


def test_draft_does_not_duplicate_on_rerun(pushable, glab):  # noqa: F811
    set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="확인했습니다")
    glab.route(
        f"GET {DRAFTS}",
        [
            {
                "id": 5,
                "discussion_id": "a1b2c3d4e5f6",
                "note": "확인했습니다",
                "resolve_discussion": False,
            }
        ],
    )

    assert main(["push", "--draft"]) == 0

    assert not [
        c
        for c in glab.calls()
        if "draft_notes" in c["argv"][1]
        and "--method" in c["argv"]
        and c["argv"][c["argv"].index("--method") + 1] == "POST"
    ]


def test_draft_refuses_when_listing_fails(pushable, glab):  # noqa: F811
    set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="확인했습니다")
    glab.route(f"GET {DRAFTS}", raw='{"message":"502"}', status=502)

    assert main(["push", "--draft"]) == 5

    assert not [
        c
        for c in glab.calls()
        if "draft_notes" in c["argv"][1]
        and "--method" in c["argv"]
        and c["argv"][c["argv"].index("--method") + 1] == "POST"
    ]


def test_draft_rejected_when_capability_missing(pushable, glab):  # noqa: F811
    set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="확인했습니다")
    path = store.review_json_path(pushable, 1234)
    review = model.loads(path.read_text(encoding="utf-8"))
    review.capabilities.draft_notes = False
    store.atomic_write_text(path, model.dumps(review))

    assert main(["push", "--draft"]) == 1

    # 조용히 일반 notes 경로로 빠지면 안 된다(MUST NOT).
    assert not [c for c in glab.calls() if c["argv"][1].endswith("/notes")]


def test_publish_clears_reply_only_when_body_still_matches(pushable, glab):  # noqa: F811
    set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="그대로")
    set_local(pushable, "b2c3d4e5f6a1", state="replied", reply="고친 뒤의 답글")
    glab.route(
        f"GET {DRAFTS}",
        [
            {
                "id": 5,
                "discussion_id": "a1b2c3d4e5f6",
                "note": "그대로",
                "resolve_discussion": False,
            },
            {
                "id": 6,
                "discussion_id": "b2c3d4e5f6a1",
                "note": "draft 만들 때의 답글",
                "resolve_discussion": False,
            },
        ],
    )
    glab.route(f"POST {PUBLISH}", {})

    assert main(["push", "--publish", "--force"]) == 0

    review = read(pushable)
    kept = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    edited = next(t for t in review.threads if t.id == "b2c3d4e5f6a1")
    assert kept.local.reply == ""
    assert kept.local.pushed_hash is not None
    # draft 를 만든 뒤 md 에서 고친 답글을 지우면 그 수정이 사라진다 (결정 0012).
    assert edited.local.reply == "고친 뒤의 답글"


def test_publish_asks_before_sending_foreign_drafts(pushable, glab, monkeypatch):  # noqa: F811
    set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="내 답글")
    glab.route(
        f"GET {DRAFTS}",
        [
            {
                "id": 5,
                "discussion_id": "a1b2c3d4e5f6",
                "note": "내 답글",
                "resolve_discussion": False,
            },
            {
                "id": 7,
                "discussion_id": None,
                "note": "UI 에서 쓰던 미완성 리뷰",
                "resolve_discussion": False,
            },
        ],
    )
    glab.route(f"POST {PUBLISH}", {})
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["push", "--publish"]) == 1
    assert not [c for c in glab.calls() if "bulk_publish" in c["argv"][1]]

    assert main(["push", "--publish", "--force"]) == 0
    assert [c for c in glab.calls() if "bulk_publish" in c["argv"][1]]


def test_draft_then_publish_in_one_call_updates_the_freshly_created_draft(pushable, glab):  # noqa: F811
    # `--draft --publish` 를 한 번에 쓰면 `_run_draft` 가 처음 조회한 draft
    # 목록에는 방금 만든 draft 가 없다 — 발행 뒤 pushed_hash 기록·reply 정리가
    # 그 스레드만 건너뛰면 "발행은 됐는데 로컬은 그대로" 가 생긴다. 발행 전에
    # 목록을 다시 조회해야 한다.
    set_local(pushable, "a1b2c3d4e5f6", state="done", reply="한 번에 보낸다")
    glab.route_seq(
        f"GET {DRAFTS}",
        [
            {"payload": []},
            {
                "payload": [
                    {
                        "id": 5,
                        "discussion_id": "a1b2c3d4e5f6",
                        "note": "한 번에 보낸다",
                        "resolve_discussion": True,
                    }
                ]
            },
        ],
    )
    glab.route(f"POST {DRAFTS}", {"id": 5}, status=201)
    glab.route(f"POST {PUBLISH}", {})

    assert main(["push", "--draft", "--publish"]) == 0

    target = next(t for t in read(pushable).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.reply == ""
    assert target.local.pushed_hash is not None


def test_publish_alone_ignores_review_md_parse_errors(pushable, glab):  # noqa: F811
    # ruling 1 — `--publish` 단독은 sync 도 건너뛴다(cli.md §9). 발행은 서버에
    # 이미 있는 draft 를 내보내는 일이라 로컬 review.md 와 무관하다. md 가 파싱
    # 에러를 안고 있어도, 이미 사용자 손을 떠난 draft 를 발행하지 못하게 막으면
    # 안 된다.
    glab.route(
        f"GET {DRAFTS}",
        [
            {
                "id": 5,
                "discussion_id": "a1b2c3d4e5f6",
                "note": "확인했습니다",
                "resolve_discussion": False,
            }
        ],
    )
    glab.route(f"POST {PUBLISH}", {})
    md_path = store.review_md_path(pushable, 1234)
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(text + "\n```python\nif True:\n    pass\n", encoding="utf-8")

    assert main(["push", "--publish", "--force"]) == 0


def test_publish_does_not_flag_edited_reply_as_foreign(pushable, glab):  # noqa: F811
    # ruling 2 — ours/foreign 판정은 discussion_id 만 본다. draft 를 만든 뒤
    # md 에서 답글을 고쳤다는 이유로 "낯선 draft" 로 보고 확인을 요구하면 안
    # 된다 — body 비교는 발행 시점에 local.reply 를 비울지 정하는 데만 쓴다.
    set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="고친 뒤의 답글")
    glab.route(
        f"GET {DRAFTS}",
        [
            {
                "id": 5,
                "discussion_id": "a1b2c3d4e5f6",
                "note": "draft 만들 때의 답글",
                "resolve_discussion": False,
            }
        ],
    )
    glab.route(f"POST {PUBLISH}", {})

    # --force 없이도 성공해야 한다 — 확인을 요구하면 비대화형이라 바로 실패한다.
    assert main(["push", "--publish"]) == 0


def test_publish_failure_records_push_error_on_every_thread_with_a_pending_draft(
    pushable,  # noqa: F811
    glab,
):
    # ruling 3 — bulk_publish 실패는 스레드 하나의 일이 아니다. 이번에
    # 발행하려던 내 draft 전부에 push_error 를 남겨야 status 가 실제 범위를
    # 보여준다.
    set_local(pushable, "a1b2c3d4e5f6", state="replied", reply="A")
    set_local(pushable, "b2c3d4e5f6a1", state="replied", reply="B")
    glab.route(
        f"GET {DRAFTS}",
        [
            {"id": 5, "discussion_id": "a1b2c3d4e5f6", "note": "A", "resolve_discussion": False},
            {"id": 6, "discussion_id": "b2c3d4e5f6a1", "note": "B", "resolve_discussion": False},
        ],
    )
    glab.route(f"POST {PUBLISH}", raw='{"message":"502 Bad Gateway"}', status=502)

    assert main(["push", "--publish", "--force"]) == 4

    review = read(pushable)
    first = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    second = next(t for t in review.threads if t.id == "b2c3d4e5f6a1")
    assert first.local.push_error["op"] == "publish"
    assert second.local.push_error["op"] == "publish"
    # 발행이 실패했으니 답글은 그대로 남아 재실행으로 복구된다.
    assert first.local.reply == "A"
    assert second.local.reply == "B"


def test_draft_only_reports_zero_pushed_in_json(pushable, glab, capsys):  # noqa: F811
    # ruling 4 — draft 생성은 전송이 아니다. draft 가 몇 건 만들어졌든
    # `pushed.replies`/`resolves` 는 0 이어야 한다 — "draft 가 있으니 답글이
    # 간 것" 처럼 보고하면 안 된다.
    set_local(pushable, "a1b2c3d4e5f6", state="done", reply="확인했습니다")
    glab.route(f"GET {DRAFTS}", [])
    glab.route(f"POST {DRAFTS}", {"id": 5}, status=201)

    assert main(["push", "--draft", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["pushed"] == {"replies": 0, "resolves": 0}


def test_publish_reports_published_counts_not_plan_counts(pushable, glab, capsys):  # noqa: F811
    # ruling 4 — 발행 시점에는 실제로 발행된 draft 수를 센다. local.reply 는
    # 전부 비어 있어(기본 `pushable` 상태) 일반 판정(`push.plan`)으로는
    # replies/resolves 가 0 이어야 하지만, 이미 서버에 있는 draft 둘(하나는
    # resolve_discussion)을 발행하면 그 수가 그대로 보고돼야 한다.
    glab.route(
        f"GET {DRAFTS}",
        [
            {"id": 5, "discussion_id": "a1b2c3d4e5f6", "note": "A", "resolve_discussion": True},
            {"id": 6, "discussion_id": "b2c3d4e5f6a1", "note": "B", "resolve_discussion": False},
        ],
    )
    glab.route(f"POST {PUBLISH}", {})

    assert main(["push", "--publish", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["pushed"] == {"replies": 2, "resolves": 1}
