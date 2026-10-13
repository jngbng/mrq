"""`status` 집계. docs/spec/cli.md §8. 파일도 네트워크도 만지지 않는다.

`push` 블록이 전송 직전 검토면이다 (30분 예산에서 사용자가 마지막으로 보는
화면). 숫자가 push 의 실제 동작과 어긋나면 검토면의 의미가 없다.

**`server-changed` 경고는 여기 없다.** `status` 는 네트워크를 쓰지 않으므로
(cli.md §1) "pull 이후 서버에서 바뀌었는가" 에 정직하게 답할 수 없다 —
`server.*` 는 `pulled_at` 을 기록한 같은 스냅샷이 쓰므로 `server.updated_at >
pulled_at` 은 구조적으로 거짓이고, 클라이언트 시계가 뒤처지면 최근에 건드린
스레드가 전부 "서버에서 변경됨" 으로 뒤집혀 검토면이 보낼 양을 **적게**
보고한다. 이 판정은 `push` 의 재조회 단계(계획 3)가 한다.
"""

from __future__ import annotations

from mrq import model


def status_payload(review: model.Review) -> dict:
    threads = review.threads
    local = {"todo": 0, "done": 0, "replied": 0, "skipped": 0}
    anchors = {"exact": 0, "fuzzy": 0, "stale": 0}
    warnings: list[dict] = []
    replies = resolves = skip = 0
    pending_resolve_total = 0

    for thread in threads:
        local[thread.local.state] += 1
        # server.missing 스레드는 재앵커링 통계와 같은 이유로 제외한다 — 사라진
        # 스레드의 위치 품질은 "현재 활성 코멘트를 얼마나 잘 찾았는가"를 재는
        # 이 지표의 모집단이 아니다 (data-model.md §4.9). threads/local 집계는
        # 모든 스레드를 그대로 센다 — 거기엔 이 제외가 적용되지 않는다.
        if (
            not thread.server.missing
            and thread.location is not None
            and thread.location.confidence in anchors
        ):
            anchors[thread.location.confidence] += 1

        pending_reply = bool(thread.local.reply.strip()) and thread.local.state in (
            "done",
            "replied",
        )
        pending_resolve = thread.local.state == "done" and not thread.server.resolved
        if not (pending_reply or pending_resolve):
            continue

        blocked = False
        if pending_reply and not thread.server.repliable:
            warnings.append({"thread": thread.id, "reason": "no-reply"})
            blocked = True
        elif pending_reply:
            replies += 1
        if pending_resolve and not thread.server.resolvable:
            warnings.append({"thread": thread.id, "reason": "not-resolvable"})
            blocked = True
        elif pending_resolve:
            pending_resolve_total += 1
        if blocked:
            skip += 1

    if pending_resolve_total and not review.me.can_resolve:
        warnings.append({"thread": None, "reason": "no-resolve-permission"})
    else:
        resolves = pending_resolve_total
    if review.mr_state != "opened":
        warnings.append({"thread": None, "reason": "mr-not-opened"})

    return {
        "iid": review.iid,
        "title": review.title,
        "mr_state": review.mr_state,
        "head_sha": review.diff_refs.head_sha,
        "pulled_at": review.pulled_at,
        "rendered_at": review.rendered_at,
        "threads": {
            "total": len(threads),
            "unresolved": sum(1 for t in threads if not t.server.resolved),
            "resolved_on_server": sum(1 for t in threads if t.server.resolved),
        },
        "local": local,
        "anchors": anchors,
        "push": {"replies": replies, "resolves": resolves, "skip": skip},
        "warnings": warnings,
    }
