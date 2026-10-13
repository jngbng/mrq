import pytest

from mrq import transport
from mrq.errors import GlabError


def test_post_reply_sends_body_on_stdin(glab):
    glab.route(
        "POST projects/:fullpath/merge_requests/1234/discussions/abc/notes",
        {"id": 9001},
        status=201,
    )
    body = "확인했습니다\n\n```python\nx = 1\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"

    transport.post_reply(1234, "abc", body)

    call = glab.calls()[-1]
    assert "-F" in call["argv"]
    assert "body=@-" in call["argv"]
    # 본문은 argv 에 절대 들어가지 않는다 (cli.md §3 MUST NOT).
    assert all("확인했습니다" not in arg for arg in call["argv"])
    assert call["stdin"] == body
    assert call["argv"][call["argv"].index("--method") + 1] == "POST"


def test_resolve_sends_boolean_field(glab):
    glab.route("PUT projects/:fullpath/merge_requests/1234/discussions/abc", {"id": "abc"})

    transport.resolve(1234, "abc")

    argv = glab.calls()[-1]["argv"]
    # `-F` 다. `-f` 로 보내면 "true" 문자열이 된다 (cli.md §3 의 표).
    assert "-F" in argv
    assert "resolved=true" in argv
    assert argv[argv.index("--method") + 1] == "PUT"


def test_post_reply_raises_glab_error_with_status(glab):
    glab.route(
        "POST projects/:fullpath/merge_requests/1234/discussions/abc/notes",
        raw='{"message":"404 Not found"}',
        status=404,
    )

    with pytest.raises(GlabError) as caught:
        transport.post_reply(1234, "abc", "본문")

    assert caught.value.status == 404
    assert caught.value.reason == "not-found"
    assert caught.value.retryable is False
