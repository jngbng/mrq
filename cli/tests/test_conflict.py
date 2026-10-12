from mrq import conflict, mdparse, render
from tests.test_render import thread  # 과제 3의 헬퍼

# "렌더 후 json 변경"은 시각이 아니라 v 핑거프린트로 판정한다
# (docs/decisions/0008-conflict-signal-v-hash-not-timestamp.md). `touched_at` 은
# 판정에 쓰이지 않으므로 아래 값은 자리표시자이고, 특정 시각보다 전/후인지는
# 어떤 테스트도 따지지 않는다 — 그런 비교 자체가 생산 경로에서 결코 참이 될 수
# 없기 때문이다. `classify` 의 `rendered_at` 인자는 제거됐다.
IGNORED_TOUCHED_AT = "2026-10-11T10:00:00+09:00"


def block(*, state="todo", reply="", v=None, thread_id="a1b2c3d4e5f6", line=10):
    return mdparse.Block(
        thread_id=thread_id,
        v=render.vhash(state, reply) if v is None else v,
        line=line,
        state=state,
        reply=reply,
    )


def test_md_equals_v_and_json_untouched_keeps_json():
    t = thread(state="todo", reply="")
    assert conflict.classify(t, block()) == "keep-json"


def test_md_equals_v_and_json_touched_by_cli_keeps_json():
    # 거짓 충돌 금지 — md 가 손대지 않았으면 json 쪽이 무엇을 했든 유지한다.
    t = thread(state="done", reply="AI 가 쓴 답글")
    t.local.touched_by, t.local.touched_at = "cli", IGNORED_TOUCHED_AT
    md = block(state="done", reply="AI 가 쓴 답글")
    assert conflict.classify(t, md) == "keep-json"


def test_md_differs_and_json_untouched_applies_md():
    t = thread(state="todo", reply="")
    md = block(state="done", reply="사람이 쓴 답글", v=render.vhash("todo", ""))
    assert conflict.classify(t, md) == "apply-md"


def test_md_differs_and_json_touched_by_cli_conflicts():
    t = thread(state="replied", reply="AI: 상위에서 설정 중입니다.")
    t.local.touched_by, t.local.touched_at = "cli", IGNORED_TOUCHED_AT
    md = block(state="done", reply="확인했습니다. timeout=10 추가.", v=render.vhash("todo", ""))
    assert conflict.classify(t, md) == "conflict"


def test_missing_v_token_applies_md_when_json_untouched():
    t = thread(state="todo", reply="")
    md = mdparse.Block(thread_id=t.id, v=None, line=10, state="done", reply="본문")
    assert conflict.classify(t, md) == "apply-md"


def test_missing_v_token_conflicts_when_json_touched():
    t = thread(state="todo", reply="")
    t.local.touched_by, t.local.touched_at = "cli", IGNORED_TOUCHED_AT
    md = mdparse.Block(thread_id=t.id, v=None, line=10, state="done", reply="본문")
    assert conflict.classify(t, md) == "conflict"


def test_cli_touch_with_value_unchanged_since_render_is_not_flagged():
    # json 의 지금 (state, reply) 가 md 에 박힌 v 와 정확히 같으면, touched_by
    # 가 "cli" 여도 "그 뒤 json 이 움직인" 것이 아니다 — v 핑거프린트가 그렇게
    # 말한다. (이 시나리오는 과거엔 "렌더보다 먼저 일어난 cli 터치"로 표현했지만
    # 실제 판정은 시각과 무관하다 — 값이 같은지만 본다.)
    t = thread(state="done", reply="이미 렌더에 반영된 값")
    t.local.touched_by, t.local.touched_at = "cli", IGNORED_TOUCHED_AT
    md = block(
        state="skipped", reply="사람이 바꿨다", v=render.vhash("done", "이미 렌더에 반영된 값")
    )
    assert conflict.classify(t, md) == "apply-md"


def test_touched_by_md_is_never_a_cli_change():
    # touched_by == "md" 는 이전 sync 가 남긴 것이다. 충돌의 상대가 아니다 —
    # 게이트는 반드시 touched_by == "cli" 다.
    t = thread(state="done", reply="이전 sync 가 넣은 값")
    t.local.touched_by, t.local.touched_at = "md", IGNORED_TOUCHED_AT
    md = block(state="skipped", reply="또 고쳤다", v=render.vhash("done", "이전 sync 가 넣은 값"))
    assert conflict.classify(t, md) == "apply-md"


def test_missing_header_keeps_json_state_in_md_values():
    t = thread(state="done", reply="본문")
    md = mdparse.Block(
        thread_id=t.id, v=render.vhash("done", "본문"), line=10, state=None, reply="본문"
    )
    assert conflict.md_values(t, md) == ("done", "본문")
    assert conflict.classify(t, md) == "keep-json"


def test_unknown_anchor_id_becomes_a_warning():
    review_threads = [thread(id="a1b2c3d4e5f6")]
    parsed = mdparse.Parsed(blocks=[block(thread_id="ffffffffffff")])

    class _R:
        threads = review_threads

    applied, conflicts, warnings = conflict.plan_sync(_R(), parsed)
    assert (applied, conflicts) == ([], [])
    assert len(warnings) == 1 and "ffffffffffff" in warnings[0].message


def test_identical_values_are_not_a_conflict_even_with_a_stale_v():
    # 사람과 AI 가 같은 결론에 도달했다 (md 의 v 는 그 전 렌더 기준이라 낡았다).
    # 같은 두 쪽을 나란히 띄우는 충돌 화면은 고를 것을 주지 못한다.
    t = thread(state="done", reply="같은 결론")
    t.local.touched_by, t.local.touched_at = "cli", IGNORED_TOUCHED_AT
    md = block(state="done", reply="같은 결론", v=render.vhash("todo", ""))
    assert conflict.classify(t, md) == "keep-json"


def test_identical_values_without_a_v_token_are_not_a_conflict():
    t = thread(state="done", reply="같은 결론")
    t.local.touched_by, t.local.touched_at = "cli", IGNORED_TOUCHED_AT
    md = mdparse.Block(thread_id=t.id, v=None, line=10, state="done", reply="같은 결론")
    assert conflict.classify(t, md) == "keep-json"


def test_a_single_character_difference_is_still_a_conflict():
    # 값 동일 단축이 판정 표 4행을 삼키지 않는지 고정한다 (§5.2 재검토).
    t = thread(state="done", reply="같은 결론")
    t.local.touched_by, t.local.touched_at = "cli", IGNORED_TOUCHED_AT
    md = block(state="done", reply="같은 결론!", v=render.vhash("todo", ""))
    assert conflict.classify(t, md) == "conflict"
