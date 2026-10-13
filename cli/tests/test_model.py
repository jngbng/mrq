import json

import jsonschema
import pytest

from mrq import model
from mrq.errors import CorruptStateError, SchemaVersionError


def make_review(**overrides) -> model.Review:
    thread = model.Thread(
        id="a1b2c3d4e5f6",
        root_note_id=5566,
        server=model.Server(
            resolvable=True,
            resolved=False,
            repliable=True,
            updated_at="2026-10-05T15:30:00+09:00",
            note_count=2,
        ),
        position=model.Position(
            position_type="text",
            old_path="src/api/client.py",
            new_path="src/api/client.py",
            old_line=None,
            new_line=88,
            line_range=None,
        ),
        anchor=model.Anchor(
            line="    resp = session.get(url)",
            context_before=["def fetch(url):", "    session = make_session()"],
            context_after=["    return resp.json()"],
            hunk="@@ -84,6 +84,9 @@\n+    resp = session.get(url)\n",
        ),
        location=model.Location(
            path="src/api/client.py",
            line=102,
            line_end=None,
            confidence="exact",
            method="git-diff",
        ),
        notes=[
            model.Note(
                id=5566,
                author="jdoe",
                created_at="2026-10-05T14:02:11+09:00",
                updated_at="2026-10-05T14:02:11+09:00",
                body="타임아웃 설정이 빠졌습니다.",
                mine=False,
                suggestions=[],
            )
        ],
        local=model.Local(),
    )
    data = {
        "schema_version": model.SCHEMA_VERSION,
        "project": "group/sub/project",
        "iid": 1234,
        "title": "Add retry logic to API client",
        "web_url": "https://gitlab.example.com/group/sub/project/-/merge_requests/1234",
        "mr_state": "opened",
        "source_branch": "feat/retry",
        "diff_refs": model.DiffRefs("0000aaa", "0000bbb", "abc1234"),
        "me": model.Me(id=7, username="bongya", can_resolve=True),
        "capabilities": model.Capabilities(draft_notes=True),
        "pulled_at": "2026-10-11T09:12:00+09:00",
        "rendered_at": None,
        "threads": [thread],
    }
    data.update(overrides)
    return model.Review(**data)


def test_roundtrip():
    review = make_review()
    assert model.loads(model.dumps(review)) == review


def test_dumps_ends_with_newline():
    assert model.dumps(make_review()).endswith("\n")


def test_dumps_keeps_hangul_readable():
    assert "타임아웃" in model.dumps(make_review())


def test_null_location_roundtrips():
    # 파일 외 코멘트와 이미지 코멘트는 location 이 null 이다.
    review = make_review()
    review.threads[0].position = None
    review.threads[0].anchor = None
    review.threads[0].location = None
    assert model.loads(model.dumps(review)).threads[0].location is None


def test_dumps_rejects_invalid_confidence():
    review = make_review()
    review.threads[0].location.confidence = "shifted"
    with pytest.raises(jsonschema.ValidationError):
        model.dumps(review)


def test_dumps_rejects_unknown_state():
    review = make_review()
    review.threads[0].local.state = "maybe"
    with pytest.raises(jsonschema.ValidationError):
        model.dumps(review)


def test_higher_schema_version_is_refused():
    data = json.loads(model.dumps(make_review()))
    data["schema_version"] = model.SCHEMA_VERSION + 1
    with pytest.raises(SchemaVersionError) as excinfo:
        model.loads(json.dumps(data))
    assert excinfo.value.exit_code == 7
    assert "업그레이드" in str(excinfo.value)


def test_older_schema_version_is_refused_with_pull_hint():
    data = json.loads(model.dumps(make_review()))
    data["schema_version"] = 0
    with pytest.raises(SchemaVersionError, match="mrq pull"):
        model.loads(json.dumps(data))


def test_location_missing_path_is_rejected():
    # asdict() 는 Location 의 path/line/line_end 를 항상 내보낸다. 손으로 쓴
    # 파일이 이 중 하나를 빠뜨리면 model.Location(**data) 가 TypeError 로 죽는
    # 대신, 쓰기 전에 jsonschema 가 먼저 분명한 에러로 잡아야 한다.
    data = json.loads(model.dumps(make_review()))
    del data["threads"][0]["location"]["path"]
    with pytest.raises(jsonschema.ValidationError):
        model.validate(data)


def test_shared_sample_validates():
    # testdata/review/ 는 세 구현이 모두 이 스키마로 검증한다.
    sample = model.schema_path().parent.parent / "testdata" / "review" / "minimal.json"
    model.validate(json.loads(sample.read_text(encoding="utf-8")))


def test_loads_rejects_invalid_enum_as_mrq_error():
    # 손으로 고친 review.json 에 "state": "DONE" 을 넣으면 재현된다.
    text = (model.schema_path().parent.parent / "testdata" / "review" / "minimal.json").read_text(
        encoding="utf-8"
    )
    broken = text.replace('"state": "todo"', '"state": "DONE"', 1)
    with pytest.raises(CorruptStateError) as exc:
        model.loads(broken)
    assert exc.value.exit_code == 1
    assert "review.json" in str(exc.value)


def test_loads_rejects_malformed_json_as_mrq_error():
    with pytest.raises(CorruptStateError):
        model.loads("{not json")


def _minimal_text() -> str:
    return (model.schema_path().parent.parent / "testdata" / "review" / "minimal.json").read_text(
        encoding="utf-8"
    )


def test_peek_source_branch_skips_validation():
    broken = _minimal_text().replace('"state": "todo"', '"state": "DONE"', 1)
    assert model.peek_source_branch(broken) == "feat/retry"


def test_peek_source_branch_returns_none_on_garbage():
    assert model.peek_source_branch("{not json") is None


def test_read_previous_keeps_local_on_current_version():
    text = _minimal_text().replace('"reply": ""', '"reply": "보존되어야 한다"', 1)
    previous, warnings = model.read_previous(text)
    local, anchor = previous["a1b2c3d4e5f6"]
    assert local.reply == "보존되어야 한다"
    assert anchor is not None and anchor.hunk is not None
    assert warnings == []


def test_read_previous_salvages_local_from_older_version():
    text = _minimal_text().replace('"schema_version": 1', '"schema_version": 0', 1)
    text = text.replace('"reply": ""', '"reply": "구버전에서도 건져야 한다"', 1)
    previous, warnings = model.read_previous(text)
    assert previous["a1b2c3d4e5f6"][0].reply == "구버전에서도 건져야 한다"
    assert any("schema_version" in w for w in warnings)


def test_read_previous_salvages_local_from_schema_violation():
    text = _minimal_text().replace('"reply": ""', '"reply": "건져야 한다"', 1)
    text = text.replace('"state": "todo"', '"state": "DONE"', 1)
    previous, warnings = model.read_previous(text)
    # 해석 불가한 state 는 버리고 기본값으로 떨어뜨리되 reply 는 살린다.
    assert previous["a1b2c3d4e5f6"][0].reply == "건져야 한다"
    assert previous["a1b2c3d4e5f6"][0].state == "todo"
    assert warnings != []


def test_read_previous_refuses_newer_version():
    text = _minimal_text().replace('"schema_version": 1', '"schema_version": 99', 1)
    with pytest.raises(SchemaVersionError) as exc:
        model.read_previous(text)
    assert exc.value.exit_code == 7


def test_read_previous_on_garbage_returns_empty_with_warning():
    previous, warnings = model.read_previous("{not json")
    assert previous == {}
    assert warnings != []


def test_read_previous_salvage_keeps_valid_push_error_and_pushed_hash():
    # 다른 필드(state) 하나를 깨서 _salvage 경로를 타게 하되, push_error 와
    # pushed_hash 자체는 유효한 값을 넣어 살아남는지 확인한다 — reply/state 만
    # 검사하던 기존 테스트들의 사각지대.
    text = _minimal_text().replace('"state": "todo"', '"state": "DONE"', 1)
    text = text.replace(
        '"push_error": null',
        '"push_error": {"op": "reply", "reason": "network", "retryable": true, '
        '"at": "2026-10-05T10:00:00+09:00"}',
        1,
    )
    text = text.replace('"pushed_hash": null', '"pushed_hash": "deadbeef"', 1)
    previous, warnings = model.read_previous(text)
    local, _ = previous["a1b2c3d4e5f6"]
    assert local.pushed_hash == "deadbeef"
    assert local.push_error == {
        "op": "reply",
        "reason": "network",
        "retryable": True,
        "at": "2026-10-05T10:00:00+09:00",
    }
    assert not any("push_error" in w for w in warnings)


def test_read_previous_drops_invalid_push_error_but_dumps_still_succeeds():
    text = _minimal_text().replace('"state": "todo"', '"state": "DONE"', 1)
    text = text.replace('"push_error": null', '"push_error": {"bogus": "shape"}', 1)
    previous, warnings = model.read_previous(text)
    local, anchor = previous["a1b2c3d4e5f6"]
    assert local.push_error is None
    assert any("push_error" in w for w in warnings)

    review = make_review()
    review.threads[0].local = local
    review.threads[0].anchor = anchor
    # model.dumps 는 검증 실패를 감싸지 않는다 — 여기서 터지면 살려낸 push_error
    # 가 스키마를 어긴 채로 넘어갔다는 뜻이다.
    roundtripped = model.loads(model.dumps(review))
    assert roundtripped.threads[0].local.push_error is None


def test_read_threads_gives_up_on_corrupt_or_older_schema_json():
    # §4.10 보존은 검증을 통과하는 현재 스키마 json 에서만 가능하다 —
    # server/position/notes 를 통째로 복원할 근거가 없으면 포기한다
    # (`read_previous` 와 다른 지점: 그것은 `local`/`anchor` 만 최선 노력으로
    # 건지지만, `read_threads` 는 스레드 전체가 필요해서 반쪽짜리를 안 받는다).
    assert model.read_threads("{not json") == {}
    older = _minimal_text().replace('"schema_version": 1', '"schema_version": 0', 1)
    assert model.read_threads(older) == {}
