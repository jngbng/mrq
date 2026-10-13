"""`status` 집계. docs/spec/cli.md §8. 파일도 네트워크도 만지지 않는다.

`push` 블록은 `push.plan` 이 계산한다 — 검토면의 숫자가 실제 전송량과 어긋나지
않게 하는 유일한 방법이 판정을 한 함수에 두는 것이다. `status` 는 스냅샷 없이
기본 플래그(`--resolve auto`, `--force` 없음)로 부른다(MUST): 검토면은 사용자가
플래그 없이 `push` 를 쳤을 때 일어날 일을 보여야 한다.

**`server-changed` 는 여기 없다.** `status` 는 네트워크를 쓰지 않으므로 "pull
이후 서버에서 바뀌었는가" 에 정직하게 답할 수 없다. 그 판정은 `push` 의 재조회
단계가 한다.
"""

from __future__ import annotations

from mrq import model, push


def status_payload(review: model.Review) -> dict:
    local = {"todo": 0, "done": 0, "replied": 0, "skipped": 0}
    anchors = {"exact": 0, "fuzzy": 0, "stale": 0}
    for thread in review.threads:
        local[thread.local.state] += 1
        # server.missing 스레드는 재앵커링 통계에서 제외한다(data-model.md
        # §4.9) — 사라진 스레드의 위치 품질은 "현재 활성 코멘트를 얼마나 잘
        # 재배치했는가"를 재는 이 지표의 모집단이 아니다. threads/local 집계는
        # 모든 스레드를 그대로 센다 — 이 제외가 적용되지 않는다.
        if (
            not thread.server.missing
            and thread.location is not None
            and thread.location.confidence in anchors
        ):
            anchors[thread.location.confidence] += 1

    sheet = push.plan(review)
    return {
        "iid": review.iid,
        "title": review.title,
        "mr_state": review.mr_state,
        "head_sha": review.diff_refs.head_sha,
        "pulled_at": review.pulled_at,
        "rendered_at": review.rendered_at,
        "threads": {
            "total": len(review.threads),
            "unresolved": sum(1 for t in review.threads if not t.server.resolved),
            "resolved_on_server": sum(1 for t in review.threads if t.server.resolved),
        },
        "local": local,
        "anchors": anchors,
        "push": {
            "replies": sheet.replies,
            "resolves": sheet.resolves,
            "skip": sheet.skip,
        },
        "warnings": sheet.warnings,
    }
