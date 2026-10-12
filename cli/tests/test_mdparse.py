from mrq import mdparse

HEAD = (
    "<!-- mrq:file schema=1 iid=1234 head=abc1234 rendered=2026-10-11T09:12:01+09:00 -->\n"
    "\n# !1234 제목\n\n"
)


def test_parses_file_meta():
    parsed = mdparse.parse(HEAD)
    assert parsed.meta.schema == 1
    assert parsed.meta.iid == 1234
    assert parsed.meta.head == "abc1234"
    assert parsed.meta.rendered == "2026-10-11T09:12:01+09:00"
    assert parsed.errors == []


def test_parses_state_and_reply():
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n"
        "## [x] src/api/client.py:102 — @jdoe\n"
        "\n> **@jdoe** 2026-10-05 14:02\n> 본문\n\n"
        "### reply\n\n확인했습니다.\n\n"
    )
    parsed = mdparse.parse(text)
    assert len(parsed.blocks) == 1
    block = parsed.blocks[0]
    assert (block.thread_id, block.v, block.state) == ("a1b2c3d4e5f6", "9f2e3a", "done")
    assert block.reply == "확인했습니다."
    assert parsed.errors == [] and parsed.warnings == []


def test_reply_preserves_tables_and_horizontal_rules():
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\n뒤 문단\n\n"
    )
    assert (
        mdparse.parse(text).blocks[0].reply == "| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\n뒤 문단"
    )


def test_anchor_inside_code_fence_does_not_split_the_block():
    # AI 가 설명을 위해 앵커 문법을 인용한다. 추적하지 않으면 블록이 둘로 쪼개진다.
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n문법은 이렇습니다:\n\n"
        "```\n<!-- mrq:ffffffffffff v:000000 -->\n## [x] 가짜 헤더\n```\n\n끝.\n\n"
    )
    parsed = mdparse.parse(text)
    assert len(parsed.blocks) == 1
    assert "<!-- mrq:ffffffffffff v:000000 -->" in parsed.blocks[0].reply
    assert parsed.blocks[0].reply.endswith("끝.")
    # 회귀 가드 — 인용된 앵커가 "손상된 앵커"로 오인되어 에러가 나면 안 된다.
    assert parsed.errors == []
    assert parsed.warnings == []


def test_reply_containing_the_reply_marker_itself():
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n`### reply` 아래에 쓰라는 말이군요.\n\n### reply\n\n두 번째는 본문입니다.\n\n"
    )
    # 블록 안 **첫** `### reply` 다음 줄부터 블록 끝까지가 reply 다 (§6 규칙 5).
    reply = mdparse.parse(text).blocks[0].reply
    assert reply.startswith("`### reply` 아래에")
    assert reply.endswith("두 번째는 본문입니다.")


def test_tilde_fence_is_tracked_too():
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n~~~\n<!-- mrq:ffffffffffff v:000000 -->\n~~~\n\n"
    )
    assert len(mdparse.parse(text).blocks) == 1


def test_nested_fence_closes_only_with_equal_or_longer_marker():
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n````markdown\n```\n<!-- mrq:ffffffffffff v:000000 -->\n```\n````\n\n"
    )
    parsed = mdparse.parse(text)
    assert len(parsed.blocks) == 1
    # 회귀 가드 — 중첩 펜스 자체가 에러를 만들면 안 된다.
    assert parsed.errors == []
    assert parsed.warnings == []


def test_reply_marker_inside_fence_is_not_the_reply_start():
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "```\n### reply\n```\n\n### reply\n\n진짜 본문\n\n"
    )
    assert mdparse.parse(text).blocks[0].reply == "진짜 본문"


def test_unterminated_fence_is_an_error_at_the_opening_line():
    # 코드 리뷰 CRITICAL 1 재현: A 의 답글이 펜스를 열고 닫지 않으면, 닫히지
    # 않은 펜스가 이후 B 의 앵커까지 통째로 삼킨다. 예전엔 조용히 통과했다 —
    # 이제는 에러가 나야 한다.
    #
    # B 는 생산 모양 그대로 ```diff 블록을 들고 있다. 그 블록의 **닫는** 줄이
    # A 가 열어 둔 펜스의 적법한 닫는 줄이므로, 펜스는 파일 끝이 아니라 B 의
    # 중간에서 닫힌다 — 미닫힘 검사로는 잡히지 않고 B 의 앵커만 사라진다.
    # 그 경우를 `skipped_anchors` 가 기록하고 `commands/sync` 가 판정한다.
    text = HEAD + (
        "<!-- mrq:aaaaaaaaaaaa v:abc123 -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n```python\n설명이 이어집니다\n\n"
        "<!-- mrq:bbbbbbbbbbbb v:def456 -->\n## [ ] src/api/client.py:102 — @park\n\n"
        "```diff\n@@ -1 +1 @@\n-a\n+b\n```\n\n"
        "> **@park** 2026-10-05 10:00\n> 인용\n\n### reply\n\n미전송 답글\n\n"
    )
    lines = text.split("\n")

    parsed = mdparse.parse(text)
    # 펜스가 B 의 ```diff 닫는 줄에서 닫혔으므로 "파일 끝까지 안 닫혔다" 에러는
    # 나지 않는다. 대신 삼켜진 앵커가 기록돼야 한다 — 이것이 없으면 B 의 편집이
    # 조용히 사라지고 A 의 답글이 B 의 마크업을 흡수한다.
    assert parsed.errors == []
    assert [(s.thread_id, s.line) for s in parsed.skipped_anchors] == [
        ("bbbbbbbbbbbb", lines.index("<!-- mrq:bbbbbbbbbbbb v:def456 -->") + 1)
    ]
    assert len(parsed.blocks) == 1 and parsed.blocks[0].thread_id == "aaaaaaaaaaaa"


def test_unterminated_fence_to_end_of_file_is_an_error_at_the_opening_line():
    # 같은 결함의 "파일 끝까지 닫히지 않는" 변형 — 뒤따르는 스레드에 코드
    # 블록이 없을 때다. 여는 줄로 보고해야 한다(§7 MUST).
    text = HEAD + (
        "<!-- mrq:aaaaaaaaaaaa v:abc123 -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n```python\n설명이 이어집니다\n\n"
        "<!-- mrq:bbbbbbbbbbbb v:def456 -->\n## [ ] (general) — @park\n\n"
        "> **@park** 2026-10-05 10:00\n> 인용\n\n### reply\n\n미전송 답글\n\n"
    )
    lines = text.split("\n")
    fence_line_index = next(i for i, line in enumerate(lines) if line.startswith("```python"))

    parsed = mdparse.parse(text)
    assert len(parsed.errors) == 1
    assert parsed.errors[0].line == fence_line_index + 1
    assert "닫히지" in parsed.errors[0].message
    # 여기서도 삼켜진 앵커는 함께 기록된다 — sync 가 그 id 로 무엇이 사라졌는지
    # 말해 줄 수 있어야 한다.
    assert [s.thread_id for s in parsed.skipped_anchors] == ["bbbbbbbbbbbb"]


def test_quoted_anchor_inside_a_closed_fence_is_recorded_as_skipped_only():
    # 인용(§6 규칙 1 이 허용)과 삼킴을 파서는 구별하지 않는다 — 사실만 남긴다.
    # 둘을 가르는 신호(그 id 가 review.json 에 있는가)는 sync 가 안다.
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n```\n<!-- mrq:ffffffffffff v:000000 -->\n```\n\n"
    )
    parsed = mdparse.parse(text)
    assert parsed.errors == []
    assert [s.thread_id for s in parsed.skipped_anchors] == ["ffffffffffff"]
    assert len(parsed.blocks) == 1


def test_missing_file_comment_is_an_error_at_line_one():
    # `cli.md` §5 의 iid 검증은 MUST 다. 주석이 없으면 iid·schema 를 검사할
    # 길이 없으므로 "검사 생략" 이 아니라 에러여야 한다.
    text = (
        "# 제목만 남긴 문서\n\n"
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [x] (general) — @kim\n\n### reply\n\n본문\n"
    )
    parsed = mdparse.parse(text)
    assert len(parsed.errors) == 1
    assert parsed.errors[0].line == 1
    assert "mrq:file" in parsed.errors[0].message


def test_mrq_prose_in_a_reply_is_not_a_damaged_anchor():
    # `<!-- mrq:TODO 참고 -->` 는 사람이 답글에 쓸 수 있는 평범한 산문이다.
    # 이것을 exit 2 로 만들면 그 한 줄 때문에 다른 모든 스레드의 편집이
    # 반영되지 못한다.
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [x] (general) — @kim\n\n"
        "### reply\n\n<!-- mrq:TODO 참고 -->\n\n본문\n"
    )
    parsed = mdparse.parse(text)
    assert parsed.errors == []
    assert parsed.blocks[0].state == "done"
    # 내부는 바이트 보존이다 — 산문이 답글에 그대로 남아야 한다.
    assert "<!-- mrq:TODO 참고 -->" in parsed.blocks[0].reply


def test_near_miss_anchor_with_five_hex_v_token_is_an_error():
    # 코드 리뷰 CRITICAL 2 재현: B 의 v 토큰이 6자가 아니라 5자라 ANCHOR_RE 에
    # 걸리지 않는다. 예전엔 그냥 A 의 답글 본문처럼 조용히 삼켜졌다.
    text = HEAD + (
        "<!-- mrq:aaaaaaaaaaaa v:abc123 -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n확인\n\n"
        "<!-- mrq:bbbbbbbbbbbb v:abcde -->\n## [ ] (general) — @park\n\n"
        "> **@park** 2026-10-05 10:00\n> 인용\n\n### reply\n\n미전송 답글\n\n"
    )
    lines = text.split("\n")
    bad_index = next(i for i, line in enumerate(lines) if "v:abcde" in line)
    expected_line = bad_index + 1

    parsed = mdparse.parse(text)
    assert len(parsed.errors) == 1
    assert parsed.errors[0].line == expected_line
    assert "bbbbbbbbbbbb" in parsed.errors[0].message


def test_near_miss_anchor_with_uppercase_hex_id_is_an_error():
    # 같은 결함, 대문자 hex 변형. ANCHOR_RE 는 소문자만 받는다.
    text = HEAD + (
        "<!-- mrq:aaaaaaaaaaaa v:abc123 -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n확인\n\n"
        "<!-- mrq:BBBBBBBBBBBB v:111111 -->\n## [ ] (general) — @park\n\n"
        "### reply\n\n미전송 답글\n\n"
    )
    lines = text.split("\n")
    bad_index = next(i for i, line in enumerate(lines) if "BBBBBBBBBBBB" in line)
    expected_line = bad_index + 1

    parsed = mdparse.parse(text)
    assert len(parsed.errors) == 1
    assert parsed.errors[0].line == expected_line
    assert "BBBBBBBBBBBB" in parsed.errors[0].message


def test_closing_fence_with_info_string_does_not_close_the_fence():
    # IMPORTANT 3 재현: CommonMark 는 닫는 펜스 마커 뒤에 공백만 허용한다.
    # ```python 처럼 정보 문자열이 붙은 줄은 열 때만 쓸 수 있고 닫을 수 없다 —
    # 안 그러면 인용 안의 평범한 내부 줄이 펜스를 조기에 닫아버린다.
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n```\n문서 예시:\n```python\n"
        "<!-- mrq:ffffffffffff v:000000 -->\n## [x] 가짜 헤더\n```\n\n끝.\n\n"
    )
    parsed = mdparse.parse(text)
    assert len(parsed.blocks) == 1
    assert parsed.errors == []
    assert "<!-- mrq:ffffffffffff v:000000 -->" in parsed.blocks[0].reply
    assert parsed.blocks[0].reply.endswith("끝.")


def test_mrq_file_comment_inside_reply_at_column_zero_does_not_error_or_overwrite_meta():
    # Minor 4 + Critical 2 의 예외 재현: 리플레이가 mrq:file 주석을 그대로
    # 인용해도 (렌더러 자신이 만드는 줄이고, 라운드트립 프로퍼티 테스트가
    # 조각으로 인용한다) 에러가 나면 안 되고, 파일 메타를 덮어써도 안 된다.
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n설정 예시:\n\n"
        "<!-- mrq:file schema=1 iid=9999 head=deadbee rendered=2099-01-01T00:00:00+09:00 -->"
        "\n\n본문\n\n"
    )
    parsed = mdparse.parse(text)
    assert parsed.errors == []
    assert parsed.warnings == []
    assert parsed.meta.iid == 1234
    assert parsed.meta.head == "abc1234"


def test_mrq_file_comment_inside_reply_does_not_overwrite_meta_when_header_omits_schema():
    # Minor 4 의 정확한 재현: 헤더에 schema= 가 없으면 예전 sentinel
    # (`parsed.meta.schema is None`) 이 계속 참으로 남아, 리플레이 안의
    # mrq:file 인용이 iid/head/rendered 를 덮어썼다 — 리뷰어 재현:
    # FileMeta(schema=9, iid=999, head='deadbee', rendered='2099'). 다음
    # 과제의 sync 가 head/iid 로 이 md 가 이 MR 것인지 판단하므로 치명적이다.
    head_without_schema = (
        "<!-- mrq:file iid=1234 head=abc1234 rendered=2026-10-11T09:12:01+09:00 -->\n"
        "\n# !1234 제목\n\n"
    )
    text = head_without_schema + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n설정 예시:\n\n"
        "<!-- mrq:file schema=9 iid=999 head=deadbee rendered=2099-01-01T00:00:00+09:00 -->"
        "\n\n본문\n\n"
    )
    parsed = mdparse.parse(text)
    assert parsed.errors == []
    assert parsed.meta.schema is None
    assert parsed.meta.iid == 1234
    assert parsed.meta.head == "abc1234"


def test_mrq_help_comment_inside_reply_at_column_zero_does_not_error():
    # 같은 예외의 mrq:help 쪽. 한 줄짜리 변형으로 명시적으로 검증한다.
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n인용:\n\n<!-- mrq:help 요약 -->\n\n본문\n\n"
    )
    parsed = mdparse.parse(text)
    assert parsed.errors == []


def test_valid_anchor_quoted_unfenced_inside_reply_starts_a_new_block():
    # 회귀 가드: 펜스 밖에서 진짜 앵커 문법을 그대로 쓰면 의도적으로 새 블록
    # 경계가 된다 — 이것이 review-md.md §2 가 "인용하려면 펜스로 감싸라" 고
    # 요구하는 이유다. 에러가 나면 안 된다.
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n"
        "### reply\n\n인용 예시입니다:\n\n"
        "<!-- mrq:ffffffffffff v:000000 -->\n## [ ] (general) — @park\n\n### reply\n\n\n"
    )
    parsed = mdparse.parse(text)
    assert parsed.errors == []
    assert len(parsed.blocks) == 2


def test_missing_header_warning_clamps_line_to_file_length_when_anchor_is_last_line():
    # Minor 6 재현: 헤더 없는 앵커가 파일의 마지막 줄이면 index+2 가 EOF
    # 너머를 가리킨다. compilation 버퍼가 점프할 수 있도록 실제 마지막 줄로
    # 자른다(§7 MUST).
    text = HEAD + "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->"
    lines = text.split("\n")

    parsed = mdparse.parse(text)
    # 헤더도 ### reply 도 없으므로 경고가 둘이지만, 둘 다 실제 파일 길이를
    # 넘지 않는 줄 번호를 가져야 한다 — 그래야 점프 가능하다.
    assert len(parsed.warnings) == 2
    assert all(w.line == len(lines) for w in parsed.warnings)


def _one(body: str) -> mdparse.Parsed:
    return mdparse.parse(HEAD + body)


def test_duplicate_anchor_id_is_an_error_with_line_number():
    body = (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [ ] (general) — @kim\n\n### reply\n\n\n"
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [x] (general) — @kim\n\n### reply\n\n\n"
    )
    # 두 번째 앵커 줄의 1-based 번호를 입력에서 직접 계산한다 (하드코딩 금지 —
    # 고정된 상수는 HEAD/body 가 바뀌면 조용히 썩는다).
    full_text = HEAD + body
    lines = full_text.split("\n")
    second_anchor_index = [
        i for i, line in enumerate(lines) if line.startswith("<!-- mrq:a1b2c3d4e5f6")
    ][1]
    expected_line = second_anchor_index + 1

    parsed = _one(body)
    assert len(parsed.errors) == 1
    assert parsed.errors[0].line == expected_line
    assert "a1b2c3d4e5f6" in parsed.errors[0].message


def test_unknown_checkbox_char_is_an_error():
    parsed = _one("<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [?] (general) — @kim\n\n### reply\n\n\n")
    assert len(parsed.errors) == 1
    assert "'?'" in parsed.errors[0].message


def test_missing_header_is_a_warning_and_state_stays_none():
    parsed = _one("<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n내가 헤더를 지웠다\n\n### reply\n\n본문\n")
    assert parsed.errors == []
    assert len(parsed.warnings) == 1
    assert parsed.blocks[0].state is None
    assert parsed.blocks[0].reply == "본문"


def test_missing_reply_section_is_a_warning_and_reply_stays_none():
    parsed = _one("<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [x] (general) — @kim\n\n본문만 있다\n")
    assert parsed.errors == []
    assert parsed.blocks[0].reply is None
    assert parsed.blocks[0].state == "done"


def test_missing_v_token_is_a_warning():
    parsed = _one("<!-- mrq:a1b2c3d4e5f6 -->\n## [x] (general) — @kim\n\n### reply\n\n본문\n")
    assert parsed.errors == []
    assert parsed.blocks[0].v is None
    assert any("v:" in w.message for w in parsed.warnings)


def test_content_outside_reply_is_ignored():
    parsed = _one(
        "사람이 끼워 넣은 메모\n\n<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n"
        "## [x] (general) — @kim\n\n> 인용을 고쳐 썼다\n\n### reply\n\n본문\n"
    )
    assert parsed.blocks[0].reply == "본문"
    assert parsed.blocks[0].state == "done"


def test_anchor_must_own_its_line():
    parsed = _one("텍스트 <!-- mrq:a1b2c3d4e5f6 v:9f2e3a --> 뒤에도 텍스트\n")
    assert parsed.blocks == []


def test_parses_every_block_of_the_golden_file():
    from mrq import model, render

    sample = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"
    review = model.loads(sample.read_text(encoding="utf-8"))
    text = render.render(review, include_resolved=True)

    parsed = mdparse.parse(text)
    assert parsed.errors == []
    assert parsed.warnings == []
    assert len(parsed.blocks) == len(review.threads)
    for block, thread in zip(parsed.blocks, render.order(review.threads), strict=True):
        assert block.thread_id == thread.id
        assert block.state == thread.local.state
        assert block.reply == render.normalize_reply(thread.local.reply)
        assert block.v == render.vhash(thread.local.state, thread.local.reply)


def test_crlf_input_parses_identically():
    text = HEAD + (
        "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n## [x] (general) — @kim\n\n### reply\n\n줄1\n줄2\n"
    )
    crlf = mdparse.parse(text.replace("\n", "\r\n"))
    assert crlf.blocks[0].reply == "줄1\n줄2"
    assert crlf.errors == [] and crlf.blocks[0].state == "done"
