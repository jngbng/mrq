"""GitLab 에 **쓰는** 유일한 지점. docs/spec/cli.md §3 의 엔드포인트 표.

읽기 메타 조회는 `mr.py`, 스레드 목록은 `discussions.py` 다. 쓰기를 한 파일에
모아 두는 이유는 `gitcmd` 래퍼와 같다 — "바깥으로 나가는 요청은 전부 여기"
여야 감사할 수 있고, `reanchor`/`status` 가 네트워크를 안 탄다는 것을 증명해 준
장치가 그것이다.
"""

from __future__ import annotations

from typing import Any

from mrq import glab
from mrq.mr import PROJECT


def post_reply(iid: int, discussion_id: str, body: str) -> Any:
    """기존 스레드에 답글을 단다.

    본문은 `-F body=@-` 로 stdin 에 넣는다(MUST). 인자로 넘기면 길이 제한과
    셸 인용 문제가 생기고, 표와 코드 블록이 섞인 답글이 깨진다.
    """
    return glab.api(
        f"{PROJECT}/merge_requests/{iid}/discussions/{discussion_id}/notes",
        method="POST",
        body=("body", body),
    )


def resolve(iid: int, discussion_id: str) -> Any:
    """스레드를 resolve 한다. `resolved` 는 불리언이어야 하므로 `fields` 다."""
    return glab.api(
        f"{PROJECT}/merge_requests/{iid}/discussions/{discussion_id}",
        method="PUT",
        fields={"resolved": "true"},
    )


def list_drafts(iid: int) -> list[dict]:
    """내 미발행 draft 목록. draft 경로의 **중복 방어 전부**다 (결정 0012)."""
    return glab.api(f"{PROJECT}/merge_requests/{iid}/draft_notes") or []


def create_draft(iid: int, discussion_id: str, body: str, *, resolve: bool) -> Any:
    """답글과 resolve 를 draft 하나로 묶는다.

    `resolve_discussion` 이 발행 시점에 resolve 를 수행하므로 draft 경로에서는
    별도 `PUT discussions` 를 보내지 않는다(MUST NOT).
    """
    return glab.api(
        f"{PROJECT}/merge_requests/{iid}/draft_notes",
        method="POST",
        fields={
            "in_reply_to_discussion_id": discussion_id,
            "resolve_discussion": "true" if resolve else "false",
        },
        body=("note", body),
    )


def bulk_publish(iid: int) -> Any:
    """내 pending draft **전부**를 발행한다. 선택적 발행 파라미터가 없다."""
    return glab.api(
        f"{PROJECT}/merge_requests/{iid}/draft_notes/bulk_publish",
        method="POST",
    )
