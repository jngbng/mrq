"""`--prefer [ID=]md|json` 의 파싱과 해소. docs/spec/cli.md §5."""

from __future__ import annotations

import json as _json

import pytest

from mrq import model, prefer
from mrq.errors import UsageError


def test_scopeless_value_is_a_default():
    assert prefer.parse(["md"]) == [prefer.Preference(None, "md")]


def test_scoped_value_binds_to_a_thread_ref():
    assert prefer.parse(["a1b2=json"]) == [prefer.Preference("a1b2", "json")]


def test_mixed_values_keep_their_order():
    assert prefer.parse(["md", "f6e5=json"]) == [
        prefer.Preference(None, "md"),
        prefer.Preference("f6e5", "json"),
    ]


def test_no_values_is_empty():
    assert prefer.parse([]) == []
    assert prefer.parse(None) == []


@pytest.mark.parametrize(
    "value",
    ["", "=", "a1b2=", "=md", "a1b2=xml", "xml", "a1b2=md=json"],
)
def test_broken_values_are_usage_errors(value):
    with pytest.raises(UsageError):
        prefer.parse([value])


def test_error_message_names_the_bad_value_and_the_grammar():
    with pytest.raises(UsageError) as caught:
        prefer.parse(["a1b2=xml"])
    assert "a1b2=xml" in str(caught.value)
    assert "md" in str(caught.value) and "json" in str(caught.value)


def test_three_scopeless_values_all_survive_parsing():
    # 어느 것이 이기는지는 resolve 의 몫이다. parse 는 버리지 않는다.
    assert prefer.parse(["md", "json", "md"]) == [
        prefer.Preference(None, "md"),
        prefer.Preference(None, "json"),
        prefer.Preference(None, "md"),
    ]


def _review(*ids: str) -> model.Review:
    """`prefer.resolve` 는 id 만 본다. 나머지 필드는 스키마를 만족하는 최소값이다."""
    source = {
        "schema_version": 1,
        "project": "g/p",
        "iid": 1,
        "title": "t",
        "web_url": "http://x/-/merge_requests/1",
        "mr_state": "opened",
        "source_branch": "b",
        "diff_refs": {"base_sha": "a", "start_sha": "b", "head_sha": "c"},
        "me": {"id": 1, "username": "me", "can_resolve": True},
        "capabilities": {"draft_notes": True},
        "pulled_at": "2026-10-14T00:00:00+09:00",
        "rendered_at": None,
        "threads": [
            {
                "id": tid,
                "root_note_id": 100 + i,
                "server": {
                    "resolvable": True,
                    "resolved": False,
                    "repliable": True,
                    "updated_at": "2026-10-05T06:30:00.000Z",
                    "note_count": 1,
                },
                "position": None,
                "anchor": None,
                "location": None,
                "notes": [
                    {
                        "id": 100 + i,
                        "author": "jdoe",
                        "created_at": "2026-10-05T05:02:11.000Z",
                        "updated_at": "2026-10-05T05:02:11.000Z",
                        "body": "b",
                        "mine": False,
                        "suggestions": [],
                    }
                ],
                "local": {
                    "state": "todo",
                    "reply": "",
                    "touched_at": None,
                    "touched_by": None,
                    "pushed_hash": None,
                    "push_error": None,
                },
            }
            for i, tid in enumerate(ids)
        ],
    }
    return model.loads(_json.dumps(source))


def test_scopeless_sets_the_default():
    got = prefer.resolve(_review("aaa111", "bbb222"), prefer.parse(["md"]))
    assert got.default == "md"
    assert got.picks == {}
    assert got.direction_for("aaa111") == "md"


def test_scoped_beats_the_default_regardless_of_order():
    review = _review("aaa111", "bbb222")
    forward = prefer.resolve(review, prefer.parse(["md", "bbb=json"]))
    backward = prefer.resolve(review, prefer.parse(["bbb=json", "md"]))
    assert forward == backward
    assert forward.direction_for("aaa111") == "md"
    assert forward.direction_for("bbb222") == "json"


def test_last_wins_within_the_same_scope():
    review = _review("aaa111", "bbb222")
    got = prefer.resolve(review, prefer.parse(["md", "json", "md"]))
    assert got.default == "md"
    scoped = prefer.resolve(review, prefer.parse(["aaa=md", "aaa=json"]))
    assert scoped.picks == {"aaa111": "json"}


def test_no_preferences_resolves_to_nothing():
    got = prefer.resolve(_review("aaa111"), [])
    assert got.default is None
    assert got.picks == {}
    assert got.direction_for("aaa111") is None


def test_unknown_ref_is_a_usage_error():
    with pytest.raises(UsageError):
        prefer.resolve(_review("aaa111"), prefer.parse(["zzz=md"]))


def test_ambiguous_prefix_is_a_usage_error_listing_candidates():
    with pytest.raises(UsageError) as caught:
        prefer.resolve(_review("aaa111", "aaa222"), prefer.parse(["aaa=md"]))
    assert "aaa111" in str(caught.value) and "aaa222" in str(caught.value)


def test_scopeless_value_colliding_with_a_thread_prefix_is_refused():
    # discussion id 는 SHA1 16진수라 도달 불가다. 가정을 불변식으로 바꾼다 —
    # 깨지면 조용한 오동작이 아니라 에러가 난다.
    with pytest.raises(UsageError) as caught:
        prefer.resolve(_review("md0001"), prefer.parse(["md"]))
    assert "md0001" in str(caught.value)
