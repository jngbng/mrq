import pytest

from mrq import model, store, surface
from mrq.__main__ import main

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"


def _place(root, iid: int, *, state: str = "opened", unsent: bool = False):
    review = model.loads(SAMPLE.read_text(encoding="utf-8"))
    review.iid = iid
    review.mr_state = state
    # `rendered.json` 에는 렌더러 테스트가 쓰는 `replied`/`done` + 답글이 이미
    # 섞여 있다 (test_push.py 의 `_blank` 와 같은 이유). 비우지 않으면
    # unsent=False 호출도 미전송 스레드 2개를 물고 들어와 확인을 요구한다.
    for thread in review.threads:
        thread.local.state = "todo"
        thread.local.reply = ""
        thread.local.pushed_hash = None
        thread.local.push_error = None
    if unsent:
        review.threads[1].local.state = "done"
        review.threads[1].local.reply = "아직 보내지 않았다"
    with store.review_lock(root, iid):
        surface.write(root, review, include_resolved=True)
    return review


@pytest.fixture
def stocked(git_repo, commit, checkout, glab, monkeypatch):
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234)
    _place(git_repo, 1235)
    store.write_current(git_repo, 1234)
    glab.route(
        "GET projects/:fullpath/merge_requests/1234",
        {"iid": 1234, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    glab.route(
        "GET projects/:fullpath/merge_requests/1235",
        {"iid": 1235, "title": "t", "web_url": "u", "state": "opened", "source_branch": "b"},
    )
    return git_repo


def test_clean_removes_merged_and_clears_current(stocked):
    assert main(["clean", "--merged"]) == 0

    assert not store.review_dir(stocked, 1234).exists()
    assert store.review_dir(stocked, 1235).exists()
    # current 가 가리키는 MR 을 제거하면 current 도 지운다(MUST) — 끊어진
    # 심링크를 남기지 않는다.
    assert store.read_current(stocked) is None


def test_clean_dry_run_removes_nothing(stocked, capsys):
    assert main(["clean", "--merged", "--dry-run"]) == 0

    assert store.review_dir(stocked, 1234).exists()
    assert "1234" in capsys.readouterr().out


def test_clean_refuses_when_unsent_work_remains(git_repo, commit, checkout, glab, monkeypatch):
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234, unsent=True)
    glab.route(
        "GET projects/:fullpath/merge_requests/1234",
        {"iid": 1234, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["clean", "--merged"]) == 1
    assert store.review_dir(git_repo, 1234).exists()

    assert main(["clean", "--merged", "--force"]) == 0
    assert not store.review_dir(git_repo, 1234).exists()


def test_clean_skips_mr_whose_state_lookup_fails(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # 가짜 glab 은 등록되지 않은 경로에서 exit 1 이다 (testing.md §2) — 네트워크
    # 장애를 흉내 내는 데 새 하네스 기능이 필요 없다. 1234 는 라우트를 등록하지
    # 않아 상태 조회가 실패하고, 1235 는 정상 응답으로 제거된다. 하나가
    # 실패해도 전체 명령이 죽지 않아야 한다.
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234)
    _place(git_repo, 1235)
    glab.route(
        "GET projects/:fullpath/merge_requests/1235",
        {"iid": 1235, "title": "t", "web_url": "u", "state": "merged", "source_branch": "b"},
    )

    assert main(["clean", "--merged"]) == 0

    assert store.review_dir(git_repo, 1234).exists()
    assert not store.review_dir(git_repo, 1235).exists()
    assert "1234" in capsys.readouterr().err
