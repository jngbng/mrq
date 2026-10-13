import json
from pathlib import Path

from mrq import discussions

FIXTURES = Path(__file__).parent / "fixtures"


def note(**overrides) -> dict:
    base = {
        "id": 1,
        "author": {"username": "jdoe"},
        "created_at": "2026-10-05T14:02:11+09:00",
        "updated_at": "2026-10-05T14:02:11+09:00",
        "body": "타임아웃 설정이 빠졌습니다.",
        "system": False,
        "resolvable": True,
        "resolved": False,
    }
    return {**base, **overrides}


def test_system_notes_are_dropped():
    raw = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [
                note(id=1),
                note(id=2, system=True, body="changed the description", resolvable=False),
            ],
        }
    ]
    threads = discussions.to_threads(raw, "bongya")
    assert [n.id for n in threads[0].notes] == [1]


def test_note_count_and_updated_at_exclude_system_notes():
    # 필터 전 값을 쓰면 동료가 라벨만 바꿔도 push 가 멀쩡한 스레드를 건너뛴다.
    raw = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [
                note(id=1, updated_at="2026-10-05T14:00:00+09:00"),
                note(id=2, updated_at="2026-10-05T15:00:00+09:00"),
                note(id=3, system=True, updated_at="2026-10-09T23:59:00+09:00", resolvable=False),
            ],
        }
    ]
    server = discussions.to_threads(raw, "bongya")[0].server
    assert server.note_count == 2
    assert server.updated_at == "2026-10-05T15:00:00+09:00"


def test_discussion_with_only_system_notes_is_dropped():
    raw = [
        {"id": "d1", "individual_note": False, "notes": [note(id=1, system=True, resolvable=False)]}
    ]
    assert discussions.to_threads(raw, "bongya") == []


def test_individual_note_is_not_repliable():
    raw = [{"id": "d1", "individual_note": True, "notes": [note(id=1)]}]
    assert discussions.to_threads(raw, "bongya")[0].server.repliable is False


def test_thread_is_repliable():
    raw = [{"id": "d1", "individual_note": False, "notes": [note(id=1)]}]
    assert discussions.to_threads(raw, "bongya")[0].server.repliable is True


def test_resolved_requires_all_resolvable_notes_resolved():
    raw = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [
                note(id=1, resolved=True),
                note(id=2, resolved=False),
            ],
        }
    ]
    assert discussions.to_threads(raw, "bongya")[0].server.resolved is False

    raw[0]["notes"][1]["resolved"] = True
    assert discussions.to_threads(raw, "bongya")[0].server.resolved is True


def test_non_resolvable_thread_is_not_resolved():
    raw = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [note(id=1, resolvable=False, resolved=False)],
        }
    ]
    server = discussions.to_threads(raw, "bongya")[0].server
    assert (server.resolvable, server.resolved) == (False, False)


def test_position_is_preserved_verbatim():
    line_range = {
        "start": {"line_code": "x_10_10", "type": "new", "old_line": None, "new_line": 10},
        "end": {"line_code": "x_11_11", "type": "old", "old_line": 11, "new_line": 11},
    }
    raw = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [
                note(
                    id=1,
                    position={
                        "position_type": "image",
                        "old_path": "src/api/old_client.py",
                        "new_path": "src/api/client.py",
                        "old_line": 42,
                        "new_line": 88,
                        "line_range": line_range,
                        "base_sha": "0000aaa",
                    },
                )
            ],
        }
    ]
    position = discussions.to_threads(raw, "bongya")[0].position
    # 모든 필드를 확인한다. old_path/new_path 혼동이나 position_type 하드코딩은
    # anchor 추출을 깨뜨리고, image 코멘트가 location: null 이어야 한다는 불변식도
    # 위반한다. 다른 테스트는 이를 잡지 못한다.
    assert position.position_type == "image"
    assert position.old_path == "src/api/old_client.py"
    assert position.new_path == "src/api/client.py"
    assert position.old_line == 42
    assert position.new_line == 88
    assert position.line_range == line_range


def test_position_absent_is_none():
    raw = [{"id": "d1", "individual_note": True, "notes": [note(id=1)]}]
    assert discussions.to_threads(raw, "bongya")[0].position is None


def test_anchor_and_location_are_filled_later():
    raw = [{"id": "d1", "individual_note": False, "notes": [note(id=1)]}]
    thread = discussions.to_threads(raw, "bongya")[0]
    assert thread.anchor is None
    assert thread.location is None


def test_mine_is_computed_from_username():
    raw = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [
                note(id=1, author={"username": "jdoe"}),
                note(id=2, author={"username": "bongya"}),
            ],
        }
    ]
    assert [n.mine for n in discussions.to_threads(raw, "bongya")[0].notes] == [False, True]


def test_suggestions_are_preserved():
    suggestions = [
        {
            "id": 1,
            "from_line": 27,
            "to_line": 27,
            "appliable": True,
            "applied": False,
            "from_content": "x\n",
            "to_content": "b\n",
        }
    ]
    raw = [{"id": "d1", "individual_note": False, "notes": [note(id=1, suggestions=suggestions)]}]
    assert discussions.to_threads(raw, "bongya")[0].notes[0].suggestions == suggestions


def test_root_note_id_is_first_non_system_note():
    raw = [
        {
            "id": "d1",
            "individual_note": False,
            "notes": [
                note(id=99, system=True, resolvable=False),
                note(id=5566),
            ],
        }
    ]
    assert discussions.to_threads(raw, "bongya")[0].root_note_id == 5566


def test_fixture_file_produces_expected_thread_count():
    raw = [
        json.loads(line)
        for line in (FIXTURES / "discussions.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    threads = discussions.to_threads(raw, "bongya")
    # 9개 discussion 중 1개(00ff00ff00ff)는 system 노트만 있어 제외된다.
    assert len(threads) == 8
