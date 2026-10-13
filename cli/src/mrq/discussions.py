"""GitLab discussions 응답을 Thread 로 바꾼다.

GitLab 의 discussion 객체에는 `{id, individual_note, notes[]}` 만 있다. thread
레벨의 resolved/resolvable/updated_at 은 존재하지 않으므로 notes 에서 계산한다
(docs/spec/data-model.md §4.2).
"""

from __future__ import annotations

import datetime as dt

from mrq import glab, model
from mrq.mr import PROJECT


def fetch(iid: int) -> list[dict]:
    raw = glab.api(f"{PROJECT}/merge_requests/{iid}/discussions", paginate=True)
    return raw or []


def to_threads(raw: list[dict], me_username: str) -> list[model.Thread]:
    threads = []
    for discussion in raw:
        # 시스템 노트는 pull 단계에서 전량 제외한다. 라벨 변경·할당·approve 가
        # 여기로 내려오며, 걸러내지 않으면 노이즈가 절반을 넘는다.
        notes = [n for n in discussion.get("notes", []) if not n.get("system")]
        if not notes:
            continue
        threads.append(_to_thread(discussion, notes, me_username))
    return threads


def _to_thread(discussion: dict, notes: list[dict], me_username: str) -> model.Thread:
    root = notes[0]
    return model.Thread(
        id=discussion["id"],
        root_note_id=root["id"],
        server=model.Server(
            resolvable=bool(root.get("resolvable")),
            resolved=_all_resolved(notes),
            # individual_note 인 스레드에는 POST .../notes 가 거부된다.
            repliable=not discussion.get("individual_note", False),
            # 필터 후 notes 로 계산한다. 필터 전 값을 쓰면 라벨 변경만으로
            # updated_at 이 움직여 push 가 멀쩡한 스레드를 건너뛴다.
            updated_at=_latest_updated_at(notes),
            note_count=len(notes),
        ),
        position=_to_position(root.get("position")),
        anchor=None,
        location=None,
        notes=[_to_note(n, me_username) for n in notes],
        local=model.Local(),
    )


def _latest_updated_at(notes: list[dict]) -> str:
    """가장 늦은 `updated_at` 을 **원본 문자열 그대로** 돌려준다.

    문자열 `max()` 를 쓰면 안 된다 — GitLab 이 `Z` 와 `+09:00` 을 섞어 주면
    사전식 순서가 실제 시각과 어긋나고, 더 이른 시각이 "가장 늦은 것" 으로
    뽑힌다. 그러면 노트 수가 그대로인 채 본문만 수정된 스레드의 변경을 `push`
    가 놓치고(`cli.md` §9 3단계), 동료가 고친 내용 위에 답글이 올라간다.

    값을 정규화해 저장하지는 않는다. `server.updated_at` 은 서버 스냅샷의
    지문이고, `push` 는 같은 함수로 계산한 두 값을 **같음/다름**으로만 비교한다.
    """
    return max(notes, key=lambda note: _instant(note.get("updated_at")))["updated_at"]


def _instant(value: object) -> dt.datetime:
    """비교용 절대 시각. 파싱할 수 없으면 "가장 이른 것" 으로 둔다.

    `render.stamp` 와 별도인 이유는 폴백이 다르기 때문이다 — 표시 경로는 원본
    문자열을 그대로 보여주고, 여기서는 비교 가능한 값이 필요하다.
    """
    if not isinstance(value, str):
        return dt.datetime.min.replace(tzinfo=dt.UTC)
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return dt.datetime.min.replace(tzinfo=dt.UTC)
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _all_resolved(notes: list[dict]) -> bool:
    resolvable = [n for n in notes if n.get("resolvable")]
    return bool(resolvable) and all(n.get("resolved") for n in resolvable)


def _to_position(raw: dict | None) -> model.Position | None:
    if not raw:
        return None
    # 변형하지 않고 보관한다. push 가 draft note 를 만들 때 그대로 되돌려 보낸다.
    return model.Position(
        position_type=raw.get("position_type", "text"),
        old_path=raw.get("old_path"),
        new_path=raw.get("new_path"),
        old_line=raw.get("old_line"),
        new_line=raw.get("new_line"),
        line_range=raw.get("line_range"),
    )


def _to_note(raw: dict, me_username: str) -> model.Note:
    username = raw["author"]["username"]
    return model.Note(
        id=raw["id"],
        author=username,
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        body=raw.get("body") or "",
        mine=username == me_username,
        # 지금은 쓰지 않지만 버리면 apply-suggestion 추가 시 스키마를 깨야 한다.
        suggestions=raw.get("suggestions") or [],
    )
