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


def _register_routes(glab, sha: str) -> None:
    """건강한 설정의 라우트 전부. 개별 테스트가 한 라우트만 덮어써 특정 단계만
    실패시킨다 — 나머지 단계는 그대로 성공해야 그 실패가 "다음에 할 일" 과
    함께 보고되는지를 확인할 수 있다.
    """
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
    # markdown 렌더는 `-F text=@-` 로 stdin 을 보내는 경로(reply/push 가 타는
    # 경로)를 doctor 가 직접 확인하는 데 쓴다. 아무것도 만들지 않는다.
    glab.route("POST markdown", {"html": "<p>mrq doctor</p>"})


@pytest.fixture
def healthy(git_repo, commit, checkout, glab, monkeypatch):
    sha = commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _register_routes(glab, sha)
    return git_repo


def test_doctor_reports_every_check_on_a_healthy_setup(healthy, capsys):
    assert main(["doctor"]) == 0

    out = capsys.readouterr().out
    for label in (
        "glab",
        "glab auth",
        "remote",
        "MR",
        "head_sha",
        "stdin",
        "draft_notes",
        "storage",
    ):
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


def _line(out: str, label: str) -> str:
    """`label` 에 해당하는 줄 하나를 고른다.

    `Check.line()` 이 이름을 13칸으로 패딩한 뒤 공백 하나를 붙이고 마크를
    낸다(`doctor.py` 참고) — 그 포맷을 그대로 복제해야 `"glab"` 과
    `"glab auth"` 처럼 한쪽이 다른 쪽의 접두사인 두 줄을 혼동하지 않는다.
    """
    prefix = f"{label:<13} "
    return next(line for line in out.splitlines() if line.startswith(prefix))


def test_doctor_head_sha_failure_has_a_hint(git_repo, commit, checkout, glab, monkeypatch, capsys):
    # versions 가 비어 있으면 mr.diff_refs 가 MrDetectionError 를 던진다 —
    # head_sha 가 ✗ 를 받아야 하고, 그 줄에도 다음에 할 일이 있어야 한다(MUST).
    sha = commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _register_routes(glab, sha)
    glab.route("GET projects/:fullpath/merge_requests/1234/versions", [])

    assert main(["doctor"]) == 1

    out = capsys.readouterr().out
    line = _line(out, "head_sha")
    assert "✗" in line and "→" in line


def test_doctor_glab_version_failure_has_a_hint(healthy, monkeypatch, capsys):
    # glab 바이너리는 있지만 --version 이 비정상 종료하는 경우. 실물에는 없는
    # 테스트 전용 스위치(MRQ_GLAB_VERSION_STATUS)로 재현한다.
    monkeypatch.setenv("MRQ_GLAB_VERSION_STATUS", "1")

    assert main(["doctor"]) == 1

    out = capsys.readouterr().out
    line = _line(out, "glab")
    assert "✗" in line and "→" in line


def test_doctor_stdin_probe_reports_unavailable_without_failing(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # markdown 렌더 API 가 404(미지원)/403(권한 없음)이면 거짓 ✗ 대신 "확인
    # 불가"로 보고해야 한다 — 가짜 실패가 진단의 신뢰를 잃는 가장 빠른 길이다.
    sha = commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _register_routes(glab, sha)
    glab.route("POST markdown", status=404)

    assert main(["doctor"]) == 0

    out = capsys.readouterr().out
    line = _line(out, "stdin")
    assert "✗" not in line
    assert "확인 불가" in line


def test_doctor_stdin_probe_failure_has_a_hint(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # 404/403 이 아닌 실패(예: 500)는 진짜 실패다 — ✗ 와 다음에 할 일이 있어야
    # 하고, 전체 종료 코드도 1 이어야 한다.
    sha = commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _register_routes(glab, sha)
    glab.route("POST markdown", status=500)

    assert main(["doctor"]) == 1

    out = capsys.readouterr().out
    line = _line(out, "stdin")
    assert "✗" in line and "→" in line
