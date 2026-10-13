import pytest

from mrq import model, store, surface
from mrq.__main__ import main

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"


@pytest.fixture
def opened(git_repo, commit, checkout, monkeypatch):
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    review = model.loads(SAMPLE.read_text(encoding="utf-8"))
    with store.review_lock(git_repo, review.iid):
        surface.write(git_repo, review, include_resolved=True)
    store.write_current(git_repo, review.iid)
    return git_repo


@pytest.fixture
def browser(monkeypatch):
    seen = []
    monkeypatch.setattr("webbrowser.open", lambda url: seen.append(url) or True)
    return seen


def test_open_uses_web_url_from_json_without_network(opened, browser, glab):
    assert main(["open"]) == 0

    # 샘플 json(testdata/review/rendered.json)의 web_url 그대로다.
    assert browser == ["https://gitlab.example.com/group/sub/project/-/merge_requests/1234"]
    # 네트워크를 쓰지 않는다 (cli.md §1 의 표).
    assert glab.calls() == []


def test_open_thread_appends_note_anchor(opened, browser):
    assert main(["open", "--thread", "a1b2"]) == 0

    assert browser[-1].endswith("#note_5566")


def test_open_rejects_an_unresolvable_thread_ref(opened, browser):
    # 빈 접두사는 전체에 걸리므로 거부한다 (threads.resolve_ref). 모호한
    # 접두사도 같은 경로로 exit 1 이다 (§1 MUST).
    assert main(["open", "--thread", ""]) == 1
    assert browser == []
