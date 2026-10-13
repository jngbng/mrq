import fcntl
import subprocess

import pytest

from mrq import store
from mrq.__main__ import main
from mrq.errors import UsageError


def _git(repo, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def test_ensure_mrq_gitignore_adds_once(git_repo, commit):
    commit({"a.py": "x\n"})
    store.ensure_mrq_gitignore(git_repo)
    store.ensure_mrq_gitignore(git_repo)
    text = (git_repo / ".mrq" / ".gitignore").read_text(encoding="utf-8")
    assert text.splitlines().count("*") == 1


def test_ensure_mrq_gitignore_never_touches_repo_gitignore(git_repo, commit):
    commit({"a.py": "x\n", ".gitignore": "*.pyc\n"})
    store.ensure_mrq_gitignore(git_repo)
    assert (git_repo / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n"


def test_mrq_dir_is_invisible_to_git(git_repo, commit):
    """git 에 직접 물어본다 — 파일 내용이 아니라 실제 동작이 계약이다.

    루트 `.gitignore` 의 역부활 패턴(`!*.json`) 을 깔아두고도 가려져야 한다.
    같은 디렉터리의 `.gitignore` 가 상위 규칙보다 우선하기 때문이다.
    """
    commit({"a.py": "x\n", ".gitignore": "!*.json\n"})
    store.ensure_mrq_gitignore(git_repo)
    review = store.review_dir(git_repo, 7)
    review.mkdir(parents=True, exist_ok=True)
    (review / "review.json").write_text("{}\n", encoding="utf-8")
    (review / "review.md").write_text("# md\n", encoding="utf-8")
    store.write_current(git_repo, 7)

    assert _git(git_repo, "status", "--porcelain", "-uall") == ""
    _git(git_repo, "add", "-A")
    assert ".mrq" not in _git(git_repo, "ls-files")


def test_ensure_mrq_gitignore_works_in_linked_worktree(git_repo, commit, tmp_path):
    """linked worktree 에서 .mrq/ 가 제외되는지 확인한다.

    `.mrq/` 가 worktree 루트마다 독립이므로 `.gitignore` 도 그 worktree 안에
    생겨야 한다. common dir 분기는 존재하지 않는다.
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

    store.ensure_mrq_gitignore(worktree_root)
    assert (worktree_root / ".mrq" / ".gitignore").is_file()

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


def test_reanchor_writes_mrq_gitignore(git_repo, commit, review_json, checkout, monkeypatch):
    # data-model.md §1 은 "모든 명령의 시작"에서 ignore 보장을 요구한다.
    # pull 만 보장하던 시절에는 pull 없이 review.json 을 손으로 둔 상태에서
    # reanchor 만 돌리면 .mrq/ 가 git 에 그대로 노출됐다.
    commit({"a.py": "x\n"})
    checkout("feat/retry")  # review.json 의 source_branch (cli.md §2 의 브랜치 가드)
    review_json(git_repo, iid=1234, source_branch="feat/retry")
    store.write_current(git_repo, 1234)
    monkeypatch.chdir(git_repo)

    assert main(["reanchor"]) == 0

    ignore_text = (git_repo / ".mrq" / ".gitignore").read_text(encoding="utf-8")
    assert "*" in ignore_text.splitlines()

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


def test_read_current_survives_a_non_numeric_pointer(git_repo, commit):
    commit({"a.txt": "x\n"})
    store.mrq_dir(git_repo).mkdir(parents=True, exist_ok=True)
    # 대상 디렉터리가 실제로 있어야 `current.is_dir()`가 True 가 되어 `int()`
    # 분기까지 들어간다 — 매달린 심링크는 `is_dir()`/`is_file()` 모두 False 라
    # 고치기 전 코드에서도 터지지 않고 조용히 통과해, 이 테스트가 지키려는
    # 줄을 전혀 실행하지 않는다.
    (store.mrq_dir(git_repo) / "not-a-number").mkdir()
    (store.mrq_dir(git_repo) / "current").symlink_to("not-a-number", target_is_directory=True)

    # 손으로 만든 포인터에서 int() 가 터지면 사용자의 탈출구가 rm -rf 뿐이다.
    assert store.read_current(git_repo) is None
