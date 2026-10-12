"""GitLab discussions 응답을 Thread 로 바꾼다.

GitLab 의 discussion 객체에는 `{id, individual_note, notes[]}` 만 있다. thread
레벨의 resolved/resolvable/updated_at 은 존재하지 않으므로 notes 에서 계산한다
(docs/spec/data-model.md §4.2).
"""

from __future__ import annotations

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
            updated_at=max(n["updated_at"] for n in notes),
            note_count=len(notes),
        ),
        position=_to_position(root.get("position")),
        anchor=None,
        location=None,
        notes=[_to_note(n, me_username) for n in notes],
        local=model.Local(),
    )


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
