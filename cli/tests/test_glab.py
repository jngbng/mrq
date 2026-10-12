import pytest

from mrq import glab as glab_mod
from mrq.errors import NetworkError

LONG_REPLY = """확인했습니다. `timeout=10` 을 추가했습니다.

| 설정 | 이전 | 이후 |
|---|---|---|
| timeout | 없음 | 10s |

---

상위에서는 설정하지 않습니다.
"""


def test_get_parses_json(glab):
    glab.route("GET user", {"id": 7, "username": "bongya"})
    assert glab_mod.api("user") == {"id": 7, "username": "bongya"}


def test_get_builds_expected_argv(glab):
    glab.route("GET user", {"id": 7})
    glab_mod.api("user")
    assert glab.calls()[0]["argv"] == ["api", "user", "--method", "GET"]


def test_post_sends_body_through_stdin(glab):
    glab.route("POST notes", {"id": 1})
    glab_mod.api("notes", method="POST", body=("body", LONG_REPLY))
    call = glab.calls()[0]
    assert "-F" in call["argv"]
    assert "body=@-" in call["argv"]
    # 표와 수평선이 섞인 본문이 그대로 전달되어야 한다.
    assert call["stdin"] == LONG_REPLY


def test_fields_become_repeated_F_flags(glab):
    glab.route("PUT d/1", {"ok": True})
    glab_mod.api("d/1", method="PUT", fields={"resolved": "true"})
    assert "resolved=true" in glab.calls()[0]["argv"]


def test_paginate_reads_ndjson(glab):
    glab.route(
        "GET discussions",
        raw='{"id": "a"}\n{"id": "b"}\n',
    )
    assert glab_mod.api("discussions", paginate=True) == [{"id": "a"}, {"id": "b"}]
    assert "--paginate" in glab.calls()[0]["argv"]
    assert "ndjson" in glab.calls()[0]["argv"]


def test_unregistered_route_raises_network_error(glab):
    with pytest.raises(NetworkError) as excinfo:
        glab_mod.api("user")
    assert excinfo.value.exit_code == 5


def test_check_false_returns_none(glab):
    assert glab_mod.api("user", check=False) is None


def test_fail_at_simulates_crash(glab):
    glab.route("GET user", {"id": 7})
    glab.fail_at(1)
    with pytest.raises(NetworkError):
        glab_mod.api("user")


def test_empty_response_is_none(glab):
    glab.route("GET nothing", raw="")
    assert glab_mod.api("nothing") is None
