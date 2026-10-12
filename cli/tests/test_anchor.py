import subprocess

from mrq import anchor, model

REFS = model.DiffRefs(base_sha="BASE", start_sha="START", head_sha="HEAD")
TEN_LINES = "".join(f"L{i}\n" for i in range(1, 11))


def text_position(**overrides) -> model.Position:
    base = {
        "position_type": "text",
        "old_path": "a.py",
        "new_path": "a.py",
        "old_line": None,
        "new_line": 5,
        "line_range": None,
    }
    return model.Position(**{**base, **overrides})


def refs_for(git_repo, start_sha: str, head_sha: str) -> model.DiffRefs:
    return model.DiffRefs(base_sha=start_sha, start_sha=start_sha, head_sha=head_sha)


def test_read_lines_strips_trailing_newline_artifact(git_repo, commit):
    sha = commit({"a.py": "L1\nL2\n"})
    assert anchor.read_lines(git_repo, sha, "a.py") == ["L1", "L2"]


def test_read_lines_without_trailing_newline(git_repo, commit):
    sha = commit({"a.py": "L1\nL2"})
    assert anchor.read_lines(git_repo, sha, "a.py") == ["L1", "L2"]


def test_read_lines_returns_lf_terminated_lines(git_repo, commit):
    # text=True 모드의 universal newlines 때문에 CRLF 는 이미 LF 가 되어 있다.
    # 이 테스트는 replace 호출을 검증하지 않는다.
    sha = commit({"a.py": "L1\r\nL2\r\n"})
    assert anchor.read_lines(git_repo, sha, "a.py") == ["L1", "L2"]


def test_read_lines_rejects_non_utf8(git_repo):
    (git_repo / "bin.dat").write_bytes(b"\xff\xfe\x00binary")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "bin"], cwd=git_repo, check=True)
    assert anchor.read_lines(git_repo, "HEAD", "bin.dat") is None


def test_read_lines_missing_path(git_repo, commit):
    sha = commit({"a.py": "L1\n"})
    assert anchor.read_lines(git_repo, sha, "없는파일.py") is None


def test_extract_takes_three_context_lines_each_side(git_repo, commit):
    sha = commit({"a.py": TEN_LINES})
    result = anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=5))
    assert result.line == "L5"
    assert result.context_before == ["L2", "L3", "L4"]
    assert result.context_after == ["L6", "L7", "L8"]


def test_extract_at_file_start_has_no_context_before(git_repo, commit):
    # index 0 에서는 context_before 가 빈 리스트다.
    sha = commit({"a.py": TEN_LINES})
    result = anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=1))
    assert result.line == "L1"
    assert result.context_before == []
    assert result.context_after == ["L2", "L3", "L4"]


def test_extract_near_file_start_keeps_partial_context(git_repo, commit):
    # max(0, ...) 가 없으면 음수 인덱스가 빈 슬라이스를 만들어 context 를 잃는다.
    sha = commit({"a.py": TEN_LINES})
    result2 = anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=2))
    assert result2.line == "L2"
    assert result2.context_before == ["L1"]
    result3 = anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=3))
    assert result3.line == "L3"
    assert result3.context_before == ["L1", "L2"]


def test_extract_at_file_end(git_repo, commit):
    sha = commit({"a.py": TEN_LINES})
    result = anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=10))
    assert result.line == "L10"
    assert result.context_after == []


def test_extract_in_single_line_file(git_repo, commit):
    sha = commit({"a.py": "only\n"})
    result = anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=1))
    assert (result.line, result.context_before, result.context_after) == ("only", [], [])


def test_extract_returns_none_when_line_exceeds_file(git_repo, commit):
    # GitLab 이 낡은 position 을 그대로 주는 경우가 있다. 한 스레드 때문에
    # pull 전체가 IndexError 로 죽으면 15 개를 다 못 받는다.
    sha = commit({"a.py": TEN_LINES})
    assert (
        anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=999)) is None
    )


def test_extract_returns_none_for_non_positive_line(git_repo, commit):
    sha = commit({"a.py": TEN_LINES})
    assert anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=0)) is None


def test_extract_returns_none_for_image_position(git_repo, commit):
    sha = commit({"a.py": TEN_LINES})
    position = text_position(position_type="image")
    assert anchor.extract(git_repo, refs_for(git_repo, sha, sha), position) is None


def test_extract_returns_none_for_missing_position(git_repo, commit):
    commit({"a.py": TEN_LINES})
    assert anchor.extract(git_repo, REFS, None) is None


def test_extract_old_side_reads_from_start_sha(git_repo, commit):
    start = commit({"a.py": "OLD1\nOLD2\nOLD3\n"})
    head = commit({"a.py": "NEW1\n"})
    position = text_position(new_line=None, old_line=2)
    result = anchor.extract(git_repo, model.DiffRefs(start, start, head), position)
    assert result.line == "OLD2"


def test_hunk_contains_header_and_target_line(git_repo, commit):
    start = commit({"a.py": "L1\nL2\nL3\n"})
    head = commit({"a.py": "L1\nL2\nINSERTED\nL3\n"})
    position = text_position(new_line=3)
    result = anchor.extract(git_repo, model.DiffRefs(start, start, head), position)
    assert result.hunk.startswith("@@ ")
    assert "+INSERTED" in result.hunk


def test_hunk_is_none_when_file_unchanged(git_repo, commit):
    sha = commit({"a.py": TEN_LINES})
    result = anchor.extract(git_repo, refs_for(git_repo, sha, sha), text_position(new_line=5))
    assert result.hunk is None
    # hunk 가 없어도 anchor 자체는 유효하다. 렌더러가 context 로 폴백한다.
    assert result.line == "L5"


def test_hunk_for_renamed_file_is_compact(git_repo, commit):
    # rename 된 파일에 줄을 추가하면 hunk 는 추가 부분만 담고 파일 전체를
    # "새 파일"로 보고하지 않는다. -M 과 양쪽 경로가 모두 필요하다.
    start = commit({"a.py": "L1\nL2\nL3\nL4\nL5\nL6\nL7\nL8\n"})
    # 파일을 새 디렉터리로 이동하고 한 줄 삽입
    (git_repo / "subdir").mkdir()
    subprocess.run(["git", "mv", "a.py", "subdir/b.py"], cwd=git_repo, check=True)
    (git_repo / "subdir" / "b.py").write_text(
        "L1\nL2\nL3\nADDED\nL4\nL5\nL6\nL7\nL8\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "move and edit"], cwd=git_repo, check=True)
    # diff.renames 가 꺼진 사용자에게도 -M 과 동일하게 동작해야 한다. 최신
    # git 은 기본값이 true 라 -M 을 빼도 이 설정 없이는 테스트가 조용히
    # 통과한다 (reanchoring.md §3).
    subprocess.run(["git", "config", "diff.renames", "false"], cwd=git_repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    position = model.Position(
        position_type="text",
        old_path="a.py",
        new_path="subdir/b.py",
        old_line=None,
        new_line=4,  # ADDED line
        line_range=None,
    )
    result = anchor.extract(git_repo, model.DiffRefs(start, start, head), position)
    assert result is not None
    assert result.hunk is not None
    # ADDED 줄이 포함되어야 한다
    assert "+ADDED" in result.hunk
    # hunk 에 원본 파일 전체가 + 로 들어오면 "+L1" 이 있다
    assert "+L1" not in result.hunk
    # "새 파일" 헤더면 @@ -0,0 이다
    assert "@@ -0,0" not in result.hunk
