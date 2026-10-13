import pytest

from mrq import store
from mrq.__main__ import main

MR = {
    "iid": 1234,
    "title": "Add retry logic to API client",
    "web_url": "https://gitlab.example.com/g/p/-/merge_requests/1234",
    "state": "opened",
    "source_branch": "feat/retry",
}


@pytest.fixture
def healthy(git_repo, commit, checkout, glab, monkeypatch):
    sha = commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    glab.route("GET projects/:fullpath/merge_requests", [MR])
    glab.route(
        "GET projects/:fullpath",
        {
            "path_with_namespace": "group/sub/project",
            "web_url": "https://gitlab.example.com/group/sub/project",
            "permissions": {"project_access": {"access_level": 40}, "group_access": None},
        },
    )
    glab.route("GET user", {"id": 7, "username": "bongya"})
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/versions",
        [{"head_commit_sha": sha, "base_commit_sha": sha, "start_commit_sha": sha}],
    )
    glab.route("GET projects/:fullpath/merge_requests/1234/draft_notes", [])
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        pages=['{"id":"abc","individual_note":false,"notes":[]}\n'],
    )
    return git_repo


def test_doctor_reports_every_check_on_a_healthy_setup(healthy, capsys):
    assert main(["doctor"]) == 0

    out = capsys.readouterr().out
    for label in ("glab", "glab auth", "remote", "MR", "head_sha", "draft_notes", "storage"):
        assert label in out
    assert "✗" not in out


def test_doctor_does_not_create_mrq_directory(healthy):
    # 진단이 상태를 만들면 "없음" 을 진단할 수 없다 (cli.md §13 MUST NOT).
    assert main(["doctor"]) == 0

    assert not store.mrq_dir(healthy).exists()


def test_doctor_marks_failures_and_exits_one(git_repo, commit, glab, monkeypatch, capsys):
    commit({"a.txt": "x\n"})
    monkeypatch.chdir(git_repo)
    # 라우트를 등록하지 않으면 가짜 glab 이 exit 1 을 낸다 = 인증·연결 실패.
    assert main(["doctor"]) == 1

    out = capsys.readouterr().out
    assert "✗" in out
    # 실패한 항목에는 다음에 할 일이 적혀 있어야 한다(MUST).
    assert "glab auth login" in out
