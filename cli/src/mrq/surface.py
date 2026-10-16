"""정본 json 과 편집면 md 를 함께 갱신하는 유일한 지점.

docs/spec/data-model.md §6 의 쓰기 주체 표를 코드로 옮긴 곳이다. pull/sync/
reanchor/reply/state 가 모두 이 함수를 지나므로 "md 재렌더를 빼먹은 명령" 이
생기지 않는다 (cli.md §1 MUST).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from mrq import model, render, store


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def write(
    root: Path,
    review: model.Review,
    *,
    include_resolved: bool,
    md: bool = True,
) -> None:
    """json 을 먼저 쓰고 md 를 쓴다. 호출자가 review_lock 을 잡고 있어야 한다.

    `md=False` 면 `rendered_at` 을 건드리지 않는다 — 그 값은 "md 를 마지막으로
    렌더한 시각" 이고 충돌 감지의 기준이다 (data-model.md §3).
    """
    if md:
        review.rendered_at = now()
    store.atomic_write_text(store.review_json_path(root, review.iid), model.dumps(review))
    if md:
        _write_md_if_changed(
            store.review_md_path(root, review.iid),
            render.render(review, include_resolved=include_resolved),
        )


def _write_md_if_changed(path: Path, text: str) -> None:
    """내용이 같으면 쓰지 않는다 — mtime 도 건드리지 않는다.

    `render.render` 는 같은 상태에 대해 **바이트까지 같은** 결과를 낸다
    (머리글에서 `rendered=<시각>` 을 뺀 뒤로). 그래서 아무것도 바뀌지 않은
    `sync` 가 파일을 건드릴 이유가 없고, 건드리면 에디터가 버퍼를 통째로
    되읽어 화면이 흔들린다 (`editor.md` §3.3).

    `review.json` 은 그대로 매번 쓴다 — `rendered_at`/`touched_at` 이 바뀌고,
    그 파일은 사람이 열어 두는 면이 아니다.
    """
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    store.atomic_write_text(path, text)
