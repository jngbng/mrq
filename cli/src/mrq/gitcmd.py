"""git plumbing 서브프로세스 래퍼.

라이브러리(GitPython 등)를 쓰지 않는다. 재앵커링의 검증 대상이 `git diff` 의 실제
출력이므로, 래퍼가 그 출력을 가리면 안 된다. docs/spec/reanchoring.md
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mrq.errors import UsageError

# 비ASCII 경로를 8진 이스케이프하지 않게 한다. 한글 경로가 깨지는 흔한 원인.
_BASE = ["git", "-c", "core.quotepath=false"]


def run(args: list[str], *, cwd: Path, check: bool = True) -> str | None:
    """git 을 실행해 stdout 을 돌려준다. check=False 면 실패 시 None."""
    proc = subprocess.run(
        [*_BASE, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    if proc.returncode != 0:
        if check:
            raise UsageError(f"git {' '.join(args)} 실패: {proc.stderr.strip()}")
        return None
    return proc.stdout


def toplevel(cwd: Path) -> Path:
    out = run(["rev-parse", "--show-toplevel"], cwd=cwd, check=False)
    if out is None:
        raise UsageError("git 저장소가 아닙니다.")
    return Path(out.strip())


def have_commit(root: Path, sha: str) -> bool:
    return run(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=root, check=False) is not None


def has_path(root: Path, rev: str, path: str) -> bool:
    """`<rev>` 에 `<path>` 가 존재하는지.

    `git diff -- <없는 경로>` 는 변경 없는 경로와 똑같이 exit 0 + 빈 출력이라
    둘을 구별할 수 없다. line_map 이 "매핑 불가"와 "변경 없음"을 나누려면
    이 확인이 선행되어야 한다.
    """
    return run(["cat-file", "-e", f"{rev}:{path}"], cwd=root, check=False) is not None


def fetch(root: Path, refspec: str) -> bool:
    return run(["fetch", "--quiet", "origin", refspec], cwd=root, check=False) is not None


def show(root: Path, rev: str, path: str) -> str | None:
    """`git show <rev>:<path>`.

    git 은 첫 콜론까지를 rev 로 보므로 경로에 콜론이 있어도 안전하다. argv 를 직접
    넘기므로 공백과 유니코드도 셸을 거치지 않는다.
    """
    return run(["show", f"{rev}:{path}"], cwd=root, check=False)


def diff_name_status(root: Path, sha: str) -> str:
    """rename 추적용. pathspec 을 주면 -M 이 동작하지 않으므로 전체로 돌린다."""
    out = run(["diff", "-M", "--name-status", sha], cwd=root)
    assert out is not None
    return out


def diff_u0(root: Path, sha: str, *paths: str) -> str | None:
    """<sha> → 작업 트리. 커밋하지 않은 수정까지 포함한다.

    경로를 양쪽(rename 전·후) 모두 넘겨야 한다. 하나만 넘기면 rename 된 파일을
    git 이 "새 파일 추가"로 보고해 매핑이 전부 어긋난다.
    """
    return run(["diff", "-M", "-U0", sha, "--", *paths], cwd=root, check=False)


def diff_u3(root: Path, a: str, b: str, *paths: str) -> str | None:
    """anchor.hunk 추출용. 리뷰어가 본 diff 를 그대로 얻는다.

    `-M` 과 양쪽 경로가 모두 필요하다. 둘 중 하나라도 빠지면 rename 된 파일을
    git 이 "새 파일 추가"로 보고해 hunk 에 파일 전체가 `+` 로 들어온다.
    """
    return run(["diff", "-M", "-U3", a, b, "--", *paths], cwd=root, check=False)
