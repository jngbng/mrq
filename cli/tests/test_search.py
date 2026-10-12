from mrq import model, search


def anchor_for(line: str, before=(), after=()) -> model.Anchor:
    return model.Anchor(
        line=line, context_before=list(before), context_after=list(after), hunk=None
    )


def test_exact_match_at_expected_line():
    lines = ["def f():", "    x = 1", "    return x"]
    assert search.find(lines, anchor_for("    x = 1"), 2) == (2, "exact")


def test_exact_match_shifted_within_window():
    lines = ["pad", "pad", "def f():", "    x = 1"]
    assert search.find(lines, anchor_for("    x = 1"), 2) == (4, "exact")


def test_indent_only_change_is_fuzzy():
    lines = ["def f():", "        x = 1"]
    assert search.find(lines, anchor_for("    x = 1"), 2) == (2, "fuzzy")


def test_duplicates_in_window_resolved_by_context():
    lines = ["def a():", "    x = 1", "", "def b():", "    x = 1", "    return x"]
    found = search.find(
        lines, anchor_for("    x = 1", before=["def b():"], after=["    return x"]), 2
    )
    assert found == (5, "fuzzy")


def test_duplicates_with_equal_nonzero_context_return_none():
    # 두 후보의 context 점수가 2 로 같다. 근거가 없으므로 고르지 않는다 —
    # 엉뚱한 줄에 붙이는 것보다 stale 이 낫다.
    lines = ["A", "    x = 1", "B", "pad", "A", "    x = 1", "B"]
    anchor = anchor_for("    x = 1", before=["A"], after=["B"])
    assert search.find(lines, anchor, 2) is None


def test_duplicates_with_no_context_match_return_none():
    lines = ["    x = 1", "pad", "    x = 1"]
    assert search.find(lines, anchor_for("    x = 1", before=["없는 줄"]), 1) is None


def test_block_moved_far_is_found_by_whole_file_uniqueness():
    # 창(±50) 밖으로 옮겨진 블록. 유일하면 채택한다.
    lines = ["pad"] * 200 + ["    resp = session.get(url)"]
    found = search.find(lines, anchor_for("    resp = session.get(url)"), 1)
    assert found == (201, "fuzzy")


def test_far_away_but_not_unique_returns_none():
    # 유일성 가드가 없으면 `}` 같은 줄에 붙어 즉시 신뢰를 잃는다.
    lines = ["pad"] * 200 + ["}", "pad", "}"]
    assert search.find(lines, anchor_for("}"), 1) is None


def test_blank_anchor_line_does_not_guess():
    # 빈 줄에 달린 코멘트. 파일 전체의 빈 줄 중 하나를 집으면 안 된다.
    lines = ["a", "", "b", "", "c", ""]
    assert search.find(lines, anchor_for(""), 2) is None


def test_whitespace_only_anchor_unique_in_window_is_exact():
    # 빈 줄과 동일하게 취급한다: 공백뿐인 앵커도 창 내에서 유일하면 정확히 반환한다.
    lines = ["a", "    ", "b", "\t", "c"]
    assert search.find(lines, anchor_for("    "), 2) == (2, "exact")


def test_blank_anchor_line_with_unique_context_is_still_refused():
    # 공백뿐인 앵커는 창 안에서 유일하지 않으면 포기한다.
    lines = ["a", "", "b", ""]
    assert search.find(lines, anchor_for("", before=["a"], after=["b"]), 2) is None


def test_blank_anchor_unique_in_window_is_exact():
    lines = ["a", "", "b", "c"]
    assert search.find(lines, anchor_for(""), 2) == (2, "exact")


def test_no_match_returns_none():
    assert search.find(["a", "b"], anchor_for("없는 줄"), 1) is None


def test_empty_file_returns_none():
    assert search.find([], anchor_for("x"), 1) is None


def test_start_line_none_searches_from_file_start():
    lines = ["pad"] * 10 + ["target"]
    assert search.find(lines, anchor_for("target"), None) == (11, "exact")
