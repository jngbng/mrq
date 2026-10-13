"""`push`/`draft` 테스트가 공유하는 픽스처와 헬퍼.

`test_push.py`·`test_draft.py` 가 여기서 가져다 쓴다 — 세 구현이 공유하는
`testdata/`와는 다르다, 이건 Python CLI 테스트 전용 보조 모듈이라
`cli/tests/`에 둔다.

라우트 키는 `"<METHOD> <path>"`다. 경로만 두고 호출처에서 메서드를 붙인다 —
같은 경로의 GET과 POST가 서로 다른 키이고 충돌하지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mrq import model, store, surface

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"

MR = {
    "iid": 1234,
    "title": "Add retry logic to API client",
    "web_url": "https://gitlab.example.com/g/p/-/merge_requests/1234",
    "state": "opened",
    "source_branch": "feat/retry",
}

DRAFTS = "projects/:fullpath/merge_requests/1234/draft_notes"
PUBLISH = "projects/:fullpath/merge_requests/1234/draft_notes/bulk_publish"


def review() -> model.Review:
    return model.loads(SAMPLE.read_text(encoding="utf-8"))


def blank(review: model.Review) -> model.Review:
    """샘플의 미전송 답글과 상태를 비운다.

    `testdata/review/rendered.json`에는 `replied`/`done` + 답글이 섞여 있다
    (렌더러 테스트가 그것을 쓴다). 비우지 않으면 `sheet.replies == 0` 같은
    절대 수 단언이 그 스레드들 때문에 맞지 않는다 — 각 테스트가 필요한
    스레드만 채운다.
    """
    for thread in review.threads:
        thread.local.state = "todo"
        thread.local.reply = ""
        thread.local.pushed_hash = None
        thread.local.push_error = None
    return review


@pytest.fixture
def pushable(git_repo, commit, checkout, glab, monkeypatch):
    """pull이 끝난 상태 + 전송 라우트. 샘플 json을 그대로 디스크에 둔다."""
    commit({"src/api/client.py": "def fetch(url):\n    resp = session.get(url)\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)

    loaded = review()
    for thread in loaded.threads:
        # 샘플에는 미전송 답글이 섞여 있다. 테스트가 "무엇이 전송되는가"를
        # 정확히 단언할 수 있도록 비운 뒤 각 테스트가 `set_local`로 채운다.
        thread.local.state = "todo"
        thread.local.reply = ""
    with store.review_lock(git_repo, loaded.iid):
        surface.write(git_repo, loaded, include_resolved=True)
    store.write_current(git_repo, loaded.iid)

    # 재pull과 스냅샷이 쓰는 읽기 라우트.
    glab.route("GET projects/:fullpath/merge_requests/1234", MR)
    glab.route(
        "GET projects/:fullpath",
        {
            "path_with_namespace": "group/sub/project",
            "permissions": {"project_access": {"access_level": 40}, "group_access": None},
        },
    )
    glab.route("GET user", {"id": 7, "username": "bongya"})
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/versions",
        [
            {
                "head_commit_sha": "abc1234",
                "base_commit_sha": "abc1234",
                "start_commit_sha": "abc1234",
            }
        ],
    )
    glab.route(f"GET {DRAFTS}", [])
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        pages=[snapshot_ndjson()],
    )
    return git_repo


def snapshot_ndjson(
    *,
    bodies: dict[str, list[str]] | None = None,
    resolved: set[str] | None = None,
) -> str:
    """샘플 review.json의 스레드를 GitLab discussions 응답 모양으로 되돌린다.

    스냅샷 비교(updated_at/note_count)가 성립해야 하므로 값을 샘플에서 그대로
    가져온다. `bodies`로 특정 스레드에 2차 방어용 "이미 보낸 note"를 둘 수
    있다 — 그 스레드는 **원본 노트를 대체한다**(추가하지 않는다). 추가하면
    `note_count`가 샘플의 `server.note_count`와 달라져 `push.plan`이
    `server-changed`로 먼저 건너뛰어 버리고 2차 방어(`_already_posted`)에
    닿지 못한다 — `discussions.to_threads`가 실제로 세는 값(필터 후 notes의
    길이)과 이 헬퍼가 만드는 값을 맞추기 위한 수정이다.

    `resolved`로 특정 스레드를 "서버에서 이미 resolve됐다"로 강제할 수 있다
    — 실제 GitLab은 resolve PUT이 성공한 뒤의 조회에서 `resolved: true`를
    돌려주지만, 샘플은 항상 고정값(`false`)이다. 연속 두 번의 `push`가 같은
    스레드를 다루는 테스트(중복 resolve 방지)에서 "성공 전/후" 스냅샷을
    구분하는 데 쓴다.
    """
    out = []
    for thread in review().threads:
        is_resolved = thread.id in (resolved or set()) or thread.server.resolved
        extra = (bodies or {}).get(thread.id)
        if extra:
            notes = [
                {
                    "id": 9000 + i,
                    "author": {"username": "bongya"},
                    "created_at": thread.server.updated_at,
                    "updated_at": thread.server.updated_at,
                    "body": body,
                    "resolvable": thread.server.resolvable,
                    "resolved": is_resolved,
                    "position": None,
                }
                for i, body in enumerate(extra)
            ]
        else:
            notes = [
                {
                    "id": thread.notes[0].id,
                    "author": {"username": thread.notes[0].author},
                    "created_at": thread.notes[0].created_at,
                    "updated_at": thread.server.updated_at,
                    "body": thread.notes[0].body,
                    "resolvable": thread.server.resolvable,
                    "resolved": is_resolved,
                    "position": None,
                }
            ]
        out.append(
            json.dumps(
                {
                    "id": thread.id,
                    "individual_note": not thread.server.repliable,
                    "notes": notes,
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(out) + "\n"


def set_local(root: Path, thread_id: str, *, state: str, reply: str) -> None:
    path = store.review_json_path(root, 1234)
    loaded = model.loads(path.read_text(encoding="utf-8"))
    target = next(t for t in loaded.threads if t.id == thread_id)
    target.local.state = state
    target.local.reply = reply
    store.atomic_write_text(path, model.dumps(loaded))


def read(root: Path) -> model.Review:
    return model.loads(store.review_json_path(root, 1234).read_text(encoding="utf-8"))
