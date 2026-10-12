import fcntl
import subprocess

import pytest

from mrq import store
from mrq.__main__ import main
from mrq.errors import UsageError


def test_ensure_git_exclude_adds_once(git_repo, commit):
    commit({"a.py": "x\n"})
    store.ensure_git_exclude(git_repo)
    store.ensure_git_exclude(git_repo)
    exclude = (git_repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.splitlines().count("/.mrq/") == 1


def test_ensure_git_exclude_never_touches_gitignore(git_repo, commit):
    commit({"a.py": "x\n", ".gitignore": "*.pyc\n"})
    store.ensure_git_exclude(git_repo)
    assert (git_repo / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n"


def test_ensure_git_exclude_works_in_linked_worktree(git_repo, commit, tmp_path):
    """linked worktree 에서 .mrq/ 가 제외되는지 확인한다.

    git 은 worktree 마다 다른 --git-dir 을 주지만 info/exclude 는 --git-common-dir
    에서만 읽으므로, git_common_dir 을 써야 한다.
    """
    commit({"a.py": "x\n"})
    # worktree 생성
    worktree_root = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", str(worktree_root), "-b", "wt"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    # worktree 에서 ensure_git_exclude 호출
    store.ensure_git_exclude(worktree_root)

    # .mrq/ 디렉터리와 파일 생성
    mrq_path = store.mrq_dir(worktree_root)
    mrq_path.mkdir(parents=True, exist_ok=True)
    (mrq_path / "test_file.txt").write_text("test\n", encoding="utf-8")

    # git status 실행 — .mrq/ 가 나오면 안 됨
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert ".mrq" not in result.stdout, (
        f".mrq/ 가 제외되지 않았습니다. git status 결과:\n{result.stdout}"
    )


def test_current_roundtrip_via_symlink(git_repo, commit):
    commit({"a.py": "x\n"})
    store.write_current(git_repo, 1234)
    assert (store.mrq_dir(git_repo) / "current").is_symlink()
    assert store.read_current(git_repo) == 1234
    assert (store.mrq_dir(git_repo) / "current" / ".").is_dir()


def test_current_switches_without_leaving_stale_link(git_repo, commit):
    commit({"a.py": "x\n"})
    store.write_current(git_repo, 1234)
    store.write_current(git_repo, 5678)
    assert store.read_current(git_repo) == 5678


def test_current_falls_back_to_pointer_file(git_repo, commit):
    commit({"a.py": "x\n"})
    store.review_dir(git_repo, 42).mkdir(parents=True)
    (store.mrq_dir(git_repo) / "current").write_text("42\n", encoding="utf-8")
    assert store.read_current(git_repo) == 42


def test_current_absent(git_repo, commit):
    commit({"a.py": "x\n"})
    assert store.read_current(git_repo) is None


def test_clear_current(git_repo, commit):
    commit({"a.py": "x\n"})
    store.write_current(git_repo, 7)
    store.clear_current(git_repo)
    assert store.read_current(git_repo) is None


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "d" / "review.json"
    store.atomic_write_text(target, '{"a": 1}')
    assert target.read_text(encoding="utf-8") == '{"a": 1}'
    assert [p.name for p in target.parent.iterdir()] == ["review.json"]


def test_atomic_write_preserves_original_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "review.json"
    store.atomic_write_text(target, "원본")

    def boom(*args, **kwargs):
        raise OSError("디스크 꽉 찼습니다")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.atomic_write_text(target, "새 내용")
    assert target.read_text(encoding="utf-8") == "원본"
    assert [p.name for p in tmp_path.iterdir()] == ["review.json"]


def test_review_lock_is_exclusive(git_repo, commit, monkeypatch):
    commit({"a.py": "x\n"})
    monkeypatch.setattr(store, "LOCK_RETRIES", 1)
    monkeypatch.setattr(store, "LOCK_INTERVAL", 0)
    lock_path = store.review_dir(git_repo, 7) / "lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.touch()
    with open(lock_path, "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        with pytest.raises(UsageError, match="락을 얻지 못했습니다"):
            with store.review_lock(git_repo, 7):
                pass


def test_reanchor_registers_git_exclude(git_repo, commit, review_json, monkeypatch):
    # data-model.md §1 은 "모든 명령의 시작"에서 exclude 등록을 요구한다.
    # pull 만 ensure_git_exclude 를 호출하던 시절에는 pull 없이 review.json 을
    # 손으로 둔 상태에서 reanchor 만 돌리면 .mrq/ 가 등록되지 않았다.
    commit({"a.py": "x\n"})
    review_json(git_repo, iid=1234, source_branch="feat/retry")
    store.write_current(git_repo, 1234)
    monkeypatch.chdir(git_repo)

    assert main(["reanchor"]) == 0

    exclude_text = (git_repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert "/.mrq/" in exclude_text

    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo, capture_output=True, text=True, check=True
    )
    assert ".mrq" not in result.stdout


def test_review_lock_releases(git_repo, commit):
    commit({"a.py": "x\n"})
    with store.review_lock(git_repo, 7):
        pass
    with store.review_lock(git_repo, 7):
        pass
