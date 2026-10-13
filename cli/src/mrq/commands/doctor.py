"""`mrq doctor`. docs/spec/cli.md §13.

환경 문제가 전부 한 머신에서 발생하는 범위이므로, 설정 실패를 추측하게 만들지
않는 것만으로 충분하다. 실패한 항목에는 **다음에 할 일**을 적는다(MUST).

`.mrq/` 를 만들지 않는다(MUST NOT) — 진단이 상태를 만들면 "없음" 을 진단할 수
없다. 그래서 `store.open_review` 를 쓰지 않는다 (그 함수가 ignore 를 보장한다).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mrq import gitcmd, glab, mr, store
from mrq.errors import MrqError

_VERSION = re.compile(r"\d+\.\d+\.\d+")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""

    def line(self) -> str:
        mark = "✓" if self.ok else "✗"
        tail = f"  → {self.hint}" if (not self.ok and self.hint) else ""
        return f"{self.name:<13} {mark} {self.detail}{tail}"


def run(args) -> int:
    checks = list(_checks())
    for check in checks:
        print(check.line())
    return 0 if all(c.ok for c in checks) else 1


def _checks():
    yield _glab_version()

    try:
        user_id, username = mr.whoami()
    except MrqError as exc:
        yield Check("glab auth", False, str(exc), "`glab auth login` 으로 로그인하세요")
        return
    yield Check("glab auth", True, f"{username} (id {user_id})")

    try:
        project, can_resolve = mr.project_info()
    except MrqError as exc:
        yield Check(
            "remote",
            False,
            str(exc),
            "origin 이 GitLab 리포인지, 그 프로젝트에 접근 권한이 있는지 확인하세요",
        )
        return
    yield Check("remote", True, f"origin → {project}")

    root = gitcmd.toplevel(Path.cwd())
    try:
        info = mr.detect(root)
    except MrqError as exc:
        yield Check("MR", False, str(exc), "`mrq pull --mr <iid>` 로 지정할 수 있습니다")
        yield _storage(root)
        return
    yield Check("MR", True, f"!{info.iid} (source_branch {info.source_branch})")

    try:
        refs = mr.diff_refs(info.iid)
    except MrqError as exc:
        yield Check("head_sha", False, str(exc))
    else:
        present = gitcmd.run(
            ["cat-file", "-e", f"{refs.head_sha}^{{commit}}"], cwd=root, check=False
        )
        yield Check(
            "head_sha",
            present is not None,
            f"{refs.head_sha[:7]} ({'로컬에 있음' if present is not None else '로컬에 없음'})",
            "`mrq pull` 이 자동으로 fetch 합니다",
        )

    # `--paginate --output ndjson` 경로를 실제로 한 번 태운다. `pull` 이 그
    # 경로에 전부 의존하므로 doctor 가 그것을 확인해야 한다 (cli.md §3).
    try:
        glab.api(f"{mr.PROJECT}/merge_requests/{info.iid}/discussions", paginate=True)
    except MrqError as exc:
        yield Check("discussions", False, str(exc), "glab 의 --paginate 지원을 확인하세요")
    else:
        yield Check("discussions", True, "--paginate --output ndjson 동작")

    drafts_ok = mr.draft_notes_available(info.iid)
    yield Check(
        "draft_notes",
        drafts_ok,
        "사용 가능" if drafts_ok else "사용 불가 (--draft 를 쓸 수 없습니다)",
        "이 GitLab 버전이 draft_notes API 를 지원하지 않습니다",
    )
    yield Check(
        "resolve 권한",
        can_resolve,
        "Developer 이상" if can_resolve else "권한 없음 (resolve 는 전송되지 않습니다)",
        "프로젝트 권한을 올리거나 `--resolve skip` 을 쓰세요",
    )
    yield _storage(root)


def _glab_version() -> Check:
    try:
        proc = subprocess.run(
            ["glab", "--version"], capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError:
        return Check("glab", False, "설치되어 있지 않습니다", "https://gitlab.com/gitlab-org/cli")
    found = _VERSION.search(proc.stdout or "")
    # 버전 번호로 기능을 분기하지 않는다(MUST NOT). 표시용이다.
    return Check("glab", proc.returncode == 0, f"v{found[0]}" if found else "버전 확인 불가")


def _storage(root: Path) -> Check:
    """`.mrq/` 의 **현재 상태**를 보고한다. 만들지 않는다."""
    directory = store.mrq_dir(root)
    if not directory.exists():
        return Check("storage", True, f"{directory} (아직 없음 — `mrq pull` 이 만듭니다)")
    ignored = (directory / ".gitignore").is_file()
    return Check(
        "storage",
        ignored,
        f"{directory}" + ("" if ignored else " (.gitignore 없음)"),
        "`mrq pull` 이 `.mrq/.gitignore` 에 `*` 를 씁니다",
    )
