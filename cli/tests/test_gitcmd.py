import pytest

from mrq import gitcmd
from mrq.errors import UsageError

# Review Focus 3: 경로에 공백·한글·콜론이 들어 있다.
TRICKY_PATH = "src/한글 디렉터리/a:b.py"


def test_toplevel(git_repo, commit):
    commit({"a.py": "x\n"})
    assert gitcmd.toplevel(git_repo) == git_repo


def test_toplevel_outside_repo(tmp_path):
    with pytest.raises(UsageError, match="git 저장소가 아닙니다"):
        gitcmd.toplevel(tmp_path)


def test_show_handles_spaces_hangul_and_colon(git_repo, commit):
    sha = commit({TRICKY_PATH: "첫 줄\n두 번째 줄\n"})
    assert gitcmd.show(git_repo, sha, TRICKY_PATH) == "첫 줄\n두 번째 줄\n"


def test_name_status_does_not_octal_escape_hangul(git_repo, commit):
    # core.quotepath=false 가 없으면 git 이 "src/\355\225\234..." 로 내보낸다.
    commit({TRICKY_PATH: "x\n"})
    (git_repo / TRICKY_PATH).write_text("y\n", encoding="utf-8")
    out = gitcmd.diff_name_status(git_repo, "HEAD")
    assert TRICKY_PATH in out


def test_diff_u0_scopes_to_path(git_repo, commit):
    sha = commit({"a.py": "1\n2\n", "b.py": "1\n"})
    (git_repo / "a.py").write_text("1\nINSERT\n2\n", encoding="utf-8")
    (git_repo / "b.py").write_text("CHANGED\n", encoding="utf-8")
    out = gitcmd.diff_u0(git_repo, sha, "a.py")
    assert "INSERT" in out
    assert "CHANGED" not in out


def test_have_commit(git_repo, commit):
    sha = commit({"a.py": "x\n"})
    assert gitcmd.have_commit(git_repo, sha) is True
    assert gitcmd.have_commit(git_repo, "0" * 40) is False


def test_has_path(git_repo, commit):
    sha = commit({TRICKY_PATH: "content\n"})
    assert gitcmd.has_path(git_repo, sha, TRICKY_PATH) is True
    assert gitcmd.has_path(git_repo, sha, "없는파일.py") is False


def test_check_false_returns_none(git_repo, commit):
    commit({"a.py": "x\n"})
    assert gitcmd.show(git_repo, "HEAD", "없는파일.py") is None


def test_check_true_raises(git_repo, commit):
    commit({"a.py": "x\n"})
    with pytest.raises(UsageError, match="git "):
        gitcmd.run(["cat-file", "-p", "0" * 40], cwd=git_repo)
