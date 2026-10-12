"""`.mrq/` 레이아웃, 원자적 쓰기, 락, git ignore 보장.

docs/spec/data-model.md §1. 저장 위치는 리포 루트의 `.mrq/` 이며 worktree 마다
독립적이다 (docs/decisions/0005-storage-location.md).
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mrq import gitcmd
from mrq.errors import UsageError

GITIGNORE_LINE = "*"
GITIGNORE_HEADER = "# mrq 가 관리하는 리뷰 상태. 커밋하지 않는다."
LOCK_RETRIES = 5
LOCK_INTERVAL = 1.0


def repo_root(cwd: Path | None = None) -> Path:
    """`git rev-parse --show-toplevel`. worktree 에서는 그 worktree 의 루트다."""
    return gitcmd.toplevel(cwd or Path.cwd())


def mrq_dir(root: Path) -> Path:
    return root / ".mrq"


def review_dir(root: Path, iid: int) -> Path:
    return mrq_dir(root) / str(iid)


def review_json_path(root: Path, iid: int) -> Path:
    return review_dir(root, iid) / "review.json"


def review_md_path(root: Path, iid: int) -> Path:
    return review_dir(root, iid) / "review.md"


def ensure_mrq_gitignore(root: Path) -> None:
    """`.mrq/.gitignore` 에 `*` 를 보장한다 (data-model.md §1).

    `*` 가 `.gitignore` 자신까지 매치하므로 `.mrq/` 전체가 git 에서 사라진다.
    리포 루트의 `.gitignore` 는 건드리지 않는다 — 개인 도구의 항목을 팀 리포
    히스토리에 넣지 않는다.

    `.git/` 에 쓰지 않는 것이 핵심이다. 샌드박스가 `.git/` 쓰기를 거부해도
    동작하고, ignore 규칙이 상태와 같은 디렉터리에 살아서 worktree 분기가 없다
    (docs/decisions/0007-mrq-gitignore.md).
    """
    path = mrq_dir(root) / ".gitignore"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if any(line.strip() == GITIGNORE_LINE for line in lines):
        return
    if not lines:
        lines = [GITIGNORE_HEADER]
    lines.append(GITIGNORE_LINE)
    atomic_write_text(path, "\n".join(lines) + "\n")


@dataclass
class ReviewContext:
    root: Path
    iid: int
    path: Path


def open_review(*, require_state: bool = True) -> ReviewContext:
    """모든 명령의 공통 진입점.

    `.mrq/.gitignore` 를 보장하고(data-model.md §1), 리뷰 상태를 찾는다.
    `require_state=True` 면 상태가 없을 때 UsageError(exit 1) 로 `mrq pull` 을
    안내한다 — 빈 결과를 성공으로 보고하지 않는다(cli.md §2).
    """
    root = repo_root()
    ensure_mrq_gitignore(root)
    iid = read_current(root)
    path = review_json_path(root, iid) if iid is not None else None
    if require_state and (path is None or not path.is_file()):
        raise UsageError("리뷰 상태가 없습니다. `mrq pull` 을 먼저 실행하세요.")
    if iid is None:
        # require_state=False 이고 아직 current 가 없는 경우 (pull 의 첫 실행).
        # 루트와 ignore 보장만 필요하므로 iid/path 는 자리표시자다.
        return ReviewContext(root=root, iid=0, path=mrq_dir(root) / "none")
    return ReviewContext(root=root, iid=iid, path=path)


def read_current(root: Path) -> int | None:
    current = mrq_dir(root) / "current"
    if current.is_dir():
        return int(current.resolve().name)
    if current.is_file():
        text = current.read_text(encoding="utf-8").strip()
        return int(text) if text.isdigit() else None
    return None


def write_current(root: Path, iid: int) -> None:
    """`.mrq/current` 를 `<iid>/` 심링크로 만든다.

    `.mrq/current/review.md` 가 iid 를 모르는 소비자(AI 프롬프트, 에디터)의 안정
    경로다. 심링크를 못 만드는 환경에서는 iid 만 담은 파일로 폴백한다.
    """
    review_dir(root, iid).mkdir(parents=True, exist_ok=True)
    current = mrq_dir(root) / "current"
    if current.is_symlink() or current.exists():
        current.unlink()
    try:
        current.symlink_to(str(iid), target_is_directory=True)
    except OSError:
        current.write_text(f"{iid}\n", encoding="utf-8")


def clear_current(root: Path) -> None:
    current = mrq_dir(root) / "current"
    if current.is_symlink() or current.exists():
        current.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    """같은 디렉터리의 temp 파일에 쓴 뒤 `os.replace` 로 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def review_lock(root: Path, iid: int):
    """`.mrq/<iid>/lock` 에 배타 flock.

    프로세스가 죽어도 커널이 해제하므로 고아 락이 남지 않는다. 에디터의 `sync` 와
    터미널의 `push` 가 동시에 돌 수 있다.
    """
    directory = review_dir(root, iid)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "lock"
    with open(lock_path, "a+") as handle:
        for attempt in range(LOCK_RETRIES):
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == LOCK_RETRIES - 1:
                    raise UsageError(
                        f"{lock_path} 락을 얻지 못했습니다. 다른 mrq 가 실행 중인지 확인하세요."
                    ) from None
                time.sleep(LOCK_INTERVAL)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
