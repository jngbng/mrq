"""MR 탐지와 메타데이터. docs/spec/cli.md §4.

프로젝트 식별에 `git remote get-url origin` 을 파싱하지 않는다. `glab api` 의
`:fullpath` 플레이스홀더가 체크아웃 기준으로 확장한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrq import gitcmd, glab, model, store
from mrq.errors import GlabError, MrDetectionError

PROJECT = "projects/:fullpath"

# Developer 이상이면 남의 스레드도 resolve 할 수 있다.
DEVELOPER_ACCESS_LEVEL = 30


@dataclass
class MrInfo:
    iid: int
    title: str
    web_url: str
    mr_state: str
    source_branch: str


def _to_info(data: dict) -> MrInfo:
    return MrInfo(
        iid=data["iid"],
        title=data["title"],
        web_url=data["web_url"],
        mr_state=data["state"],
        source_branch=data["source_branch"],
    )


def _fetch(iid: int) -> MrInfo:
    data = glab.api(f"{PROJECT}/merge_requests/{iid}")
    if not data:
        raise MrDetectionError(f"!{iid} 를 찾을 수 없습니다.")
    return _to_info(data)


def detect(root: Path, explicit_iid: int | None = None) -> MrInfo:
    if explicit_iid is not None:
        return _fetch(explicit_iid)

    branch = gitcmd.current_branch(root)

    cached = store.read_current(root)
    if cached is not None:
        path = store.review_json_path(root, cached)
        if path.is_file():
            # source_branch 를 확인해야 한다. 브랜치를 바꿨는데 current 를 그대로
            # 쓰면 다른 MR 의 상태를 보게 된다. 스키마 유효성에 묶지 않는다 —
            # 손상된 json 때문에 pull 이 시작도 못 하면 탈출구가 rm -rf 뿐이다.
            if model.peek_source_branch(path.read_text(encoding="utf-8")) == branch:
                return _fetch(cached)

    found = glab.api(
        f"{PROJECT}/merge_requests",
        query={"source_branch": branch, "state": "opened", "per_page": "100"},
    )
    if not found:
        raise MrDetectionError(
            f"브랜치 {branch} 에 열린 MR 이 없습니다. `--mr <iid>` 로 지정하세요."
        )
    if len(found) > 1:
        candidates = "\n".join(f"  !{m['iid']}  {m['title']}" for m in found)
        raise MrDetectionError(
            f"브랜치 {branch} 에 열린 MR 이 {len(found)} 건입니다. "
            f"`--mr <iid>` 로 지정하세요.\n{candidates}"
        )
    return _to_info(found[0])


def project_info() -> tuple[str, bool]:
    """`(path_with_namespace, can_resolve)`.

    resolve 권한을 pull 시점에 확인해 `status` 가 사전에 알린다. 403 을 사후
    에러로 다루지 않는다 (docs/spec/cli.md §9).
    """
    data = glab.api(PROJECT)
    permissions = data.get("permissions") or {}
    levels = [
        (permissions.get(key) or {}).get("access_level") or 0
        for key in ("project_access", "group_access")
    ]
    return data["path_with_namespace"], max(levels) >= DEVELOPER_ACCESS_LEVEL


def diff_refs(iid: int) -> model.DiffRefs:
    versions = glab.api(f"{PROJECT}/merge_requests/{iid}/versions")
    if not versions:
        raise MrDetectionError(f"!{iid} 의 diff 버전을 가져올 수 없습니다.")
    latest = versions[0]
    return model.DiffRefs(
        base_sha=latest["base_commit_sha"],
        start_sha=latest["start_commit_sha"],
        head_sha=latest["head_commit_sha"],
    )


def whoami() -> tuple[int, str]:
    data = glab.api("user")
    return data["id"], data["username"]


def draft_notes_available(iid: int) -> bool:
    """가용성을 탐지만 한다. 미지원이면 `--draft` 를 명시적으로 거부한다.

    `status == 404`(이 GitLab 이 draft_notes 를 지원하지 않음)만 "미지원"으로
    확정해 `False` 를 돌려준다(Important 4). 그 외의 실패(네트워크 장애,
    5xx, 권한 문제 등)는 **그대로 올린다** — 404 와 똑같이 `False` 로 접으면
    "이 GitLab 은 draft_notes 를 지원하지 않는다" 는 틀린 결론이 영구히
    기록된다. `pull` 이 그 값을 `capabilities.draft_notes` 로 저장하고,
    `push --draft`/`doctor` 가 그 값만 보고 "GitLab 버전을 확인하라" 고
    안내하는데, 실제로는 일시적인 502 였을 뿐이라면 엉뚱한 곳을 가리킨다.
    호출자가 "확인 불가"(일시적)와 "미지원"(확정)을 구분할 수 있도록
    `GlabError` 를 그대로 전파한다 — `pull`은 이를 못 확인한 것으로 보고
    `False` 로 저장하고, `doctor`는 "확인 불가" 로 보고한다
    (`_stdin_field` 와 같은 패턴).
    """
    try:
        glab.api(f"{PROJECT}/merge_requests/{iid}/draft_notes")
    except GlabError as exc:
        if exc.status == 404:
            return False
        raise
    return True
