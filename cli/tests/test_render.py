from pathlib import Path

from mrq import model, render

GOLDEN = Path(__file__).parent / "golden" / "rendered.md"
SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"


def _sample() -> model.Review:
    return model.loads(SAMPLE.read_text(encoding="utf-8"))


def thread(
    *,
    id="a1b2c3d4e5f6",
    state="todo",
    reply="",
    path="src/api/client.py",
    line=102,
    confidence="exact",
    resolved=False,
    repliable=True,
    author="jdoe",
    created_at="2026-10-05T14:02:00+09:00",
    anchor=None,
    position="text",
):
    location = (
        None
        if path is None
        else model.Location(
            path=path, line=line, line_end=None, confidence=confidence, method="git-diff"
        )
    )
    return model.Thread(
        id=id,
        root_note_id=5566,
        server=model.Server(
            resolvable=True,
            resolved=resolved,
            repliable=repliable,
            updated_at="2026-10-05T15:30:00+09:00",
            note_count=1,
        ),
        position=None
        if position is None
        else model.Position(
            position_type=position,
            old_path=path,
            new_path=path,
            old_line=None,
            new_line=88,
            line_range=None,
        ),
        anchor=anchor,
        location=location,
        notes=[
            model.Note(
                id=5566,
                author=author,
                created_at=created_at,
                updated_at=created_at,
                body="타임아웃 설정이 빠졌습니다.",
                mine=False,
            )
        ],
        local=model.Local(state=state, reply=reply),
    )


def test_normalize_reply_unifies_line_endings():
    assert render.normalize_reply("a\r\nb\r\n") == "a\nb"


def test_normalize_reply_strips_outer_blank_lines_only():
    assert render.normalize_reply("\n\n  본문  \n\n\n") == "  본문  "


def test_normalize_reply_preserves_inner_bytes():
    text = "줄1\n\n\t들여쓰기  \n```\ncode\n```"
    assert render.normalize_reply(text) == text


def test_vhash_is_six_hex_chars():
    value = render.vhash("done", "확인했습니다")
    assert len(value) == 6
    assert all(c in "0123456789abcdef" for c in value)


def test_vhash_ignores_outer_whitespace_but_not_state():
    assert render.vhash("done", "x") == render.vhash("done", "\n\nx\n\n")
    assert render.vhash("done", "x") != render.vhash("replied", "x")


def test_vhash_matches_spec_formula():
    import hashlib

    expected = hashlib.sha256("done\n확인했습니다".encode()).hexdigest()[:6]
    assert render.vhash("done", "  \n확인했습니다\n") == expected


def test_visible_hides_server_resolved_by_default():
    threads = [thread(id="aaaa1111", resolved=True), thread(id="bbbb2222")]
    assert [t.id for t in render.visible(threads, include_resolved=False)] == ["bbbb2222"]
    assert len(render.visible(threads, include_resolved=True)) == 2


def test_visible_keeps_resolved_thread_with_unsent_reply():
    # 동료가 내 스레드를 먼저 resolve 했을 때 전송 안 한 답글이 사라지면 안 된다.
    threads = [thread(id="aaaa1111", resolved=True, reply="아직 안 보낸 답글")]
    assert len(render.visible(threads, include_resolved=False)) == 1


def test_visible_keeps_resolved_thread_with_nondefault_state():
    threads = [thread(id="aaaa1111", resolved=True, state="skipped")]
    assert len(render.visible(threads, include_resolved=False)) == 1


def test_header_line_states_and_badges():
    assert render.header_line(thread()) == "## [ ] src/api/client.py:102 — @jdoe"
    assert render.header_line(thread(state="done")).startswith("## [x] ")
    assert render.header_line(thread(state="replied")).startswith("## [~] ")
    assert render.header_line(thread(state="skipped")).startswith("## [-] ")
    assert render.header_line(thread(confidence="fuzzy")).endswith("— @jdoe  `fuzzy`")
    assert render.header_line(thread(repliable=False)).endswith("— @jdoe  `no-reply`")


def test_header_line_stale_points_at_line_one():
    # location.line 은 stale 에서 None 이다. 헤더에서 점프하는 것은 사용자의
    # 명시적 행동이므로 1 행을 허용한다 (review-md.md §3).
    header = render.header_line(thread(confidence="stale", line=None))
    assert header == "## [ ] src/api/client.py:1 — @jdoe  `stale`"


def test_header_line_general_has_no_location_badge():
    # location 이 null 인 것은 "위치를 못 찾음" 이 아니라 "위치가 없음" 이다.
    header = render.header_line(thread(path=None, position=None, author="kim"))
    assert header == "## [ ] (general) — @kim"


def test_header_line_general_still_warns_about_no_reply():
    header = render.header_line(thread(path=None, position=None, author="kim", repliable=False))
    assert header == "## [ ] (general) — @kim  `no-reply`"


def test_header_shows_server_missing_badge():
    review = _sample()
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.server.missing = True

    assert "`server-missing`" in render.header_line(target)


def test_general_header_also_shows_server_missing():
    # 위치가 아니라 서버 속성을 보는 배지이므로 (general) 헤더에도 붙는다
    # (review-md.md §3).
    review = _sample()
    target = next(t for t in review.threads if t.id == "7a0b1c2d3e4f")
    target.server.missing = True
    line = render.header_line(target)

    assert "(general)" in line
    assert "`server-missing`" in line


def test_order_puts_general_first_then_path_line():
    threads = [
        thread(id="cccc3333", path="src/b.py", line=10),
        thread(id="aaaa1111", path=None, position=None, created_at="2026-10-05T10:00:00+09:00"),
        thread(id="bbbb2222", path="src/a.py", line=200),
        thread(id="dddd4444", path="src/a.py", line=5),
    ]
    assert [t.id for t in render.order(threads)] == [
        "aaaa1111",
        "dddd4444",
        "bbbb2222",
        "cccc3333",
    ]


def test_order_is_deterministic_for_same_path_and_line():
    # 같은 줄에 두 명이 코멘트하면 흔히 발생한다. 입력 순서가 바뀌어도 같은
    # 순서가 나와야 재렌더 diff 가 최소가 된다.
    a = thread(id="aaaa1111", path="src/a.py", line=7)
    b = thread(id="bbbb2222", path="src/a.py", line=7)
    assert [t.id for t in render.order([a, b])] == [t.id for t in render.order([b, a])]


def test_order_sorts_general_threads_by_created_at():
    late = thread(id="aaaa1111", path=None, position=None, created_at="2026-10-05T18:00:00+09:00")
    early = thread(id="bbbb2222", path=None, position=None, created_at="2026-10-05T09:00:00+09:00")
    assert [t.id for t in render.order([late, early])] == ["bbbb2222", "aaaa1111"]


def test_render_matches_golden():
    assert render.render(_sample()) == GOLDEN.read_text(encoding="utf-8")


def test_render_ends_with_exactly_one_newline():
    text = render.render(_sample())
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_render_file_comment_carries_schema_iid_head():
    first = render.render(_sample()).splitlines()[0]
    assert first.startswith("<!-- mrq:file schema=1 iid=1234 head=abc1234 rendered=")
    assert first.endswith("-->")


def test_render_hides_plain_resolved_thread_but_keeps_one_with_reply():
    text = render.render(_sample())
    assert "d4e5f6a1b2c3" in text  # 전송 전 답글이 있다
    assert "e5f6a1b2c3d4" not in text  # 그냥 resolve 된 것
    assert "e5f6a1b2c3d4" in render.render(_sample(), include_resolved=True)


def test_render_uses_diff_fence_when_hunk_exists():
    text = render.render(_sample())
    assert "```diff\n@@" in text


def test_render_uses_language_fence_from_path_when_no_hunk():
    text = render.render(_sample())
    assert "```python\ndef build(cfg):\n    timeout = None\n" in text


def test_quotes_prefix_every_line_including_blanks():
    text = render.render(_sample())
    block = text.split("<!-- mrq:b2c3d4e5f6a1")[1]
    assert (
        "> 코드 블록을 포함한 지적입니다.\n>\n> ```python\n> Session(timeout=10)\n"
        "> ```\n>\n> 확인 부탁합니다." in block
    )


def test_quotes_separate_notes_with_a_bare_marker():
    located = _sample()
    threads = [t for t in located.threads if t.id == "a1b2c3d4e5f6"]
    threads[0].notes.append(
        model.Note(
            id=5567,
            author="kim",
            created_at="2026-10-05T15:30:00+09:00",
            updated_at="2026-10-05T15:30:00+09:00",
            body="상위에서 설정하고 있지 않나요?",
            mine=True,
        )
    )
    text = render.render(located)
    assert (
        "> 타임아웃 설정이 빠졌습니다. 기본값이면 무한 대기할 수 있어요.\n"
        ">\n> **@kim** 2026-10-05 15:30\n" in text
    )


def test_render_omits_code_block_when_anchor_is_null():
    text = render.render(_sample())
    general = text.split("<!-- mrq:7a0b1c2d3e4f")[1].split("<!-- mrq:")[0]
    assert "```" not in general
    assert "(general)" in general


def test_render_lengthens_fence_when_context_contains_backticks():
    review = _sample()
    target = next(t for t in review.threads if t.id == "b2c3d4e5f6a1")
    target.anchor = model.Anchor(
        line="```python", context_before=["설명"], context_after=["```"], hunk=None
    )
    text = render.render(review)
    assert "````" in text


# R7 — GitLab 은 created_at 을 UTC 로 준다 (MR !1 실측: "2026-10-12T23:07:20.443Z").
# 기록된 오프셋 그대로 출력하면 08:07 KST 에 단 코멘트가 전날 23:07 로 보이고,
# 우리가 만든 pulled/synced 는 로컬이라 한 화면에 9시간 어긋난 두 시각이 섞인다.
def test_stamp_converts_utc_to_local_timezone():
    assert render.stamp("2026-10-12T23:07:20.443Z") == "2026-10-13 08:07"


def test_stamp_converts_numeric_offset_to_local_timezone():
    assert render.stamp("2026-10-05T05:02:11+00:00") == "2026-10-05 14:02"


def test_stamp_leaves_naive_value_alone():
    # 타임존 정보가 없으면 추측하지 않는다.
    assert render.stamp("2026-10-05T14:02:11") == "2026-10-05 14:02"
