import json

from mrq.__main__ import main
from tests.test_status import ready  # noqa: F401  — 같은 픽스처를 쓴다


def test_list_json_emits_threads_verbatim(ready, capsys):  # noqa: F811
    assert main(["list", "--json", "--all"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["iid"] == 1234
    assert payload["schema_version"] == 1
    assert len(payload["threads"]) == 6
    # 필드를 가공하거나 줄이지 않는다(MUST) — 소비자가 스키마 하나만 알면 된다.
    assert set(payload["threads"][0]) == {
        "id",
        "root_note_id",
        "server",
        "position",
        "anchor",
        "location",
        "notes",
        "local",
    }


def test_list_hides_server_resolved_without_all(ready, capsys):  # noqa: F811
    assert main(["list", "--json"]) == 0
    ids = [t["id"] for t in json.loads(capsys.readouterr().out)["threads"]]
    # e5f6a1b2c3d4 는 서버에서 resolve 됐고 전송하지 않은 작업도 없다 — 숨긴다.
    assert "e5f6a1b2c3d4" not in ids


def test_list_keeps_resolved_thread_with_unsent_work_without_all(ready, capsys):  # noqa: F811
    # d4e5f6a1b2c3 는 서버에서 resolve 됐지만 local.reply 가 비어 있지 않다.
    # review-md.md §5 의 예외를 list 도 따라야 한다(MUST, cli.md §7) — 사람이
    # review.md 에서 보는 것과 AI 가 list 로 보는 것이 갈리면 안 된다.
    assert main(["list", "--json"]) == 0
    ids = [t["id"] for t in json.loads(capsys.readouterr().out)["threads"]]
    assert "d4e5f6a1b2c3" in ids


def test_list_filters_by_state_and_confidence(ready, capsys):  # noqa: F811
    assert main(["list", "--json", "--all", "--state", "replied"]) == 0
    assert [t["id"] for t in json.loads(capsys.readouterr().out)["threads"]] == ["c3d4e5f6a1b2"]

    assert main(["list", "--json", "--all", "--confidence", "stale"]) == 0
    assert [t["id"] for t in json.loads(capsys.readouterr().out)["threads"]] == ["c3d4e5f6a1b2"]


def test_list_human_output_is_one_line_per_thread(ready, capsys):  # noqa: F811
    assert main(["list"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    # 6 스레드 중 서버에서 resolve 된 둘(d4e5f6a1b2c3, e5f6a1b2c3d4) 중
    # 전송하지 않은 작업이 없는 e5f6a1b2c3d4 만 숨는다 — review-md.md §5 의
    # 예외로 d4e5f6a1b2c3 는 여전히 보인다. 그래서 5줄이다.
    assert len(lines) == 5
    assert lines[0].startswith("7a0b1c2d")  # location 없는 스레드가 먼저
    assert "@kim" in lines[0] or "@jdoe" in lines[0]
    ids = [line[:8] for line in lines]
    assert "d4e5f6a1" in ids
    assert "e5f6a1b2" not in ids


def test_list_warns_but_still_lists_after_the_checkout_moved(ready, checkout, capsys):  # noqa: F811
    # testing.md §5 — 읽기 경로는 경고만 한다. AI 가 세션 중간에 목록을 못
    # 읽게 되는 것이 낡은 목록을 보는 것보다 나쁘다.
    checkout("feat/other")
    assert main(["list", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["iid"] == 1234  # stdout 은 순수 JSON 이다
    assert "feat/other" in captured.err and "feat/retry" in captured.err
