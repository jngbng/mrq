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
