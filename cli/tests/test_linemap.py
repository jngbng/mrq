import subprocess

from mrq import linemap

FIVE_LINES = "L1\nL2\nL3\nL4\nL5\n"


def test_insert_above_shifts_following_lines(git_repo, commit):
    sha = commit({"a.py": FIVE_LINES})
    (git_repo / "a.py").write_text("L1\nNEW1\nNEW2\nL2\nL3\nL4\nL5\n", encoding="utf-8")
    mapped = linemap.line_map(git_repo, sha, "a.py")
    assert mapped.map(1) == 1
    assert mapped.map(2) == 4
    assert mapped.map(5) == 7


def test_insert_below_leaves_earlier_lines_alone(git_repo, commit):
    sha = commit({"a.py": FIVE_LINES})
    (git_repo / "a.py").write_text("L1\nL2\nL3\nL4\nL5\nNEW\n", encoding="utf-8")
    mapped = linemap.line_map(git_repo, sha, "a.py")
    assert mapped.map(3) == 3


def test_deleted_line_has_no_mapping(git_repo, commit):
    sha = commit({"a.py": FIVE_LINES})
    (git_repo / "a.py").write_text("L1\nL2\nL4\nL5\n", encoding="utf-8")
    mapped = linemap.line_map(git_repo, sha, "a.py")
    assert mapped.map(3) is None
    assert mapped.map(4) == 3


def test_modified_line_has_no_mapping(git_repo, commit):
    # 내용이 바뀐 줄은 매핑이 없다. 문자열 탐색 fallback 으로 넘어간다.
    sha = commit({"a.py": FIVE_LINES})
    (git_repo / "a.py").write_text("L1\nL2\nCHANGED\nL4\nL5\n", encoding="utf-8")
    assert linemap.line_map(git_repo, sha, "a.py").map(3) is None


def test_multiple_hunks_accumulate(git_repo, commit):
    sha = commit({"a.py": "L1\nL2\nL3\nL4\nL5\nL6\nL7\nL8\n"})
    (git_repo / "a.py").write_text(
        "NEW0\nL1\nL2\nL3\nL4\nNEW1\nNEW2\nL5\nL6\nL7\nL8\n", encoding="utf-8"
    )
    mapped = linemap.line_map(git_repo, sha, "a.py")
    assert mapped.map(1) == 2
    assert mapped.map(5) == 8
    assert mapped.map(8) == 11


def test_unchanged_file_maps_identically(git_repo, commit):
    sha = commit({"a.py": FIVE_LINES})
    assert linemap.line_map(git_repo, sha, "a.py").map(3) == 3


def test_missing_path_returns_none(git_repo, commit):
    sha = commit({"a.py": FIVE_LINES})
    assert linemap.line_map(git_repo, sha, "없는파일.py") is None


def test_line_map_follows_rename(git_repo, commit):
    # rename 된 파일은 head_sha 시점엔 옛 이름으로만 존재한다. 존재 확인은
    # head_path 로 해야 하고, diff 는 양쪽 경로를 함께 넘겨야 git 이
    # "새 파일 추가"로 보고하지 않는다.
    sha = commit({"old.py": FIVE_LINES})
    (git_repo / "new").mkdir()
    subprocess.run(["git", "mv", "old.py", "new/old.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "mv"], cwd=git_repo, check=True)
    (git_repo / "new" / "old.py").write_text("NEW1\nNEW2\n" + FIVE_LINES, encoding="utf-8")

    mapped = linemap.line_map(git_repo, sha, "old.py", "new/old.py")
    assert mapped.map(3) == 5

    # head_path 대신 작업 트리 경로로 존재를 확인하면 head_sha 에 그 이름이
    # 없으므로 항상 None 이 된다 — 이것이 이번에 고친 결함의 재현이다.
    assert linemap.line_map(git_repo, sha, "new/old.py", "new/old.py") is None


def test_path_map_tracks_rename(git_repo, commit):
    # -M 은 git diff 가 볼 수 있는 변경만 추적한다. rename 이 최소한 스테이지
    # 되어 있어야 하므로 테스트도 git mv 후 커밋한다.
    sha = commit({"old/name.py": FIVE_LINES})
    (git_repo / "new").mkdir(exist_ok=True)
    subprocess.run(["git", "mv", "old/name.py", "new/name.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "mv"], cwd=git_repo, check=True)
    mapped = linemap.path_map(git_repo, sha)
    assert mapped.resolve("old/name.py") == "new/name.py"


def test_path_map_tracks_delete(git_repo, commit):
    sha = commit({"a.py": FIVE_LINES, "b.py": "x\n"})
    subprocess.run(["git", "rm", "-q", "a.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "rm"], cwd=git_repo, check=True)
    mapped = linemap.path_map(git_repo, sha)
    assert mapped.resolve("a.py") is None
    assert mapped.resolve("b.py") == "b.py"


def test_path_map_handles_hangul_paths(git_repo, commit):
    sha = commit({"한글/파일 이름.py": FIVE_LINES})
    subprocess.run(["git", "mv", "한글/파일 이름.py", "한글/새 이름.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "mv"], cwd=git_repo, check=True)
    mapped = linemap.path_map(git_repo, sha)
    assert mapped.resolve("한글/파일 이름.py") == "한글/새 이름.py"


def test_line_map_parses_single_line_hunk_without_count():
    # `@@ -3 +2,0 @@` 처럼 개수가 생략된 형태를 1 로 읽어야 한다.
    mapped = linemap.LineMap([(3, 1, 2, 0)])
    assert mapped.map(3) is None
    assert mapped.map(4) == 3
