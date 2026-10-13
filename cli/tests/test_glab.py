import pytest

from mrq import glab as glab_mod
from mrq.errors import GlabError, NetworkError

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
    assert glab.calls()[0]["argv"] == ["api", "user", "--method", "GET", "-i"]


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


def test_fail_at_simulates_crash(glab):
    glab.route("GET user", {"id": 7})
    glab.fail_at(1)
    with pytest.raises(NetworkError):
        glab_mod.api("user")


def test_empty_response_is_none(glab):
    glab.route("GET nothing", raw="")
    assert glab_mod.api("nothing") is None


def test_route_seq_returns_a_different_response_per_call(glab):
    glab.route_seq("GET user", [{"payload": {"id": 1}}, {"payload": {"id": 2}}])
    assert glab_mod.api("user") == {"id": 1}
    assert glab_mod.api("user") == {"id": 2}


def test_route_seq_repeats_the_last_response_when_exhausted(glab):
    # 크래시 복구 테스트가 같은 명령을 재실행한다. 목록이 소진되면 마지막
    # 응답이 반복되어야 한다 — 소진을 에러로 만들면 재실행이 하네스 때문에
    # 실패한다.
    glab.route_seq("GET user", [{"payload": {"id": 1}}, {"payload": {"id": 2}}])
    glab_mod.api("user")
    glab_mod.api("user")
    assert glab_mod.api("user") == {"id": 2}
    assert glab_mod.api("user") == {"id": 2}


def test_route_seq_counts_calls_per_route_not_globally(glab):
    # 다른 경로의 호출이 끼어들어도 순서가 밀리면 안 된다. pull 은 한 번에
    # 대여섯 경로를 부른다.
    glab.route_seq("GET user", [{"payload": {"id": 1}}, {"payload": {"id": 2}}])
    glab.route("GET other", {"ok": True})
    assert glab_mod.api("user") == {"id": 1}
    glab_mod.api("other")
    assert glab_mod.api("user") == {"id": 2}


def test_include_flag_is_added_when_not_paginating(glab):
    glab.route("GET user", {"id": 7})
    glab_mod.api("user")
    assert "-i" in glab.calls()[0]["argv"]


def test_include_flag_is_not_added_when_paginating(glab):
    # -i 와 --paginate 를 같이 쓰면 glab 이 페이지마다 헤더 블록을 내 ndjson
    # 파싱이 깨진다 (1.114 실측). 그 경로는 상태 코드를 쓰지 않는다.
    glab.route("GET discussions", raw='{"id": "a"}\n')
    glab_mod.api("discussions", paginate=True)
    assert "-i" not in glab.calls()[0]["argv"]


def test_success_strips_headers_and_parses_body(glab):
    glab.route("GET user", {"id": 7, "username": "bongya"})
    assert glab_mod.api("user") == {"id": 7, "username": "bongya"}


def test_body_containing_a_blank_crlf_line_is_not_truncated(glab):
    # 본문 안에 CRLFCRLF 가 들어 있어도 헤더/본문 구분은 **첫** 구분자에서만
    # 일어나야 한다. raw 로 넣는다 — json.dumps 는 CR 을 이스케이프해서
    # 실제 바이트가 들어가지 않는다.
    glab.route("GET note", raw='{\r\n\r\n  "ok": true\r\n}')
    assert glab_mod.api("note") == {"ok": True}


def test_status_204_with_no_body_is_none(glab):
    glab.route("PUT d/1", raw="", status=204)
    assert glab_mod.api("d/1", method="PUT") is None


@pytest.mark.parametrize(
    "status,reason,retryable",
    [
        (403, "forbidden", False),
        (404, "not-found", False),
        (409, "conflict", False),
        (500, "unknown", True),
        (503, "unknown", True),
        (418, "unknown", False),
    ],
)
def test_http_error_carries_status_reason_and_retryable(glab, status, reason, retryable):
    glab.route("GET user", {"message": f"{status} nope"}, status=status)
    with pytest.raises(GlabError) as excinfo:
        glab_mod.api("user")
    assert excinfo.value.status == status
    assert excinfo.value.reason == reason
    assert excinfo.value.retryable is retryable
    assert excinfo.value.exit_code == 5


def test_error_without_a_parseable_status_is_network(glab):
    # 등록되지 않은 경로는 HTTP 실패가 아니라 프로세스 실패다. 상태를 모른다.
    with pytest.raises(GlabError) as excinfo:
        glab_mod.api("user")
    assert excinfo.value.status is None
    assert excinfo.value.reason == "network"
    assert excinfo.value.retryable is True


def test_non_json_error_body_does_not_crash(glab):
    # 리버스 프록시가 HTML 에러 페이지를 돌려줄 수 있다.
    glab.route("GET user", raw="<html>502 Bad Gateway</html>", status=502)
    with pytest.raises(GlabError) as excinfo:
        glab_mod.api("user")
    assert excinfo.value.status == 502
