import subprocess

from mrq import anchor as anchor_mod
from mrq import linemap, model, reanchor, store
from mrq.__main__ import main

PAD = "".join(f"pad{i}\n" for i in range(1, 21))
TARGET = "    resp = session.get(url)"
HEAD_CONTENT = f"def fetch(url):\n    session = make_session()\n{TARGET}\n    return resp.json()\n"


def make_thread(position: model.Position, anchor: model.Anchor | None) -> model.Thread:
    return model.Thread(
        id="t1",
        root_note_id=1,
        server=model.Server(True, False, True, "2026-10-05T00:00:00+09:00", 1),
        position=position,
        anchor=anchor,
        location=None,
        notes=[model.Note(1, "jdoe", "c", "u", "body", False, [])],
        local=model.Local(),
    )


def make_review(refs: model.DiffRefs, threads: list[model.Thread]) -> model.Review:
    return model.Review(
        schema_version=model.SCHEMA_VERSION,
        project="group/sub/project",
        iid=1234,
        title="t",
        web_url="https://gitlab.example.com/g/p/-/merge_requests/1234",
        mr_state="opened",
        source_branch="feat/retry",
        diff_refs=refs,
        me=model.Me(7, "bongya", True),
        capabilities=model.Capabilities(True),
        pulled_at="2026-10-11T09:12:00+09:00",
        rendered_at=None,
        threads=threads,
    )


def scenario(
    git_repo,
    commit,
    *,
    head: str,
    worktree: str | None,
    new_line: int = 3,
    path: str = "a.py",
    old_line: int | None = None,
    line_range=None,
):
    """head 커밋을 만들고 작업 트리를 바꾼 뒤 review 를 돌려준다."""
    sha = commit({path: head})
    target = git_repo / path
    if worktree is None:
        target.unlink()
    else:
        target.write_text(worktree, encoding="utf-8")
    refs = model.DiffRefs(base_sha=sha, start_sha=sha, head_sha=sha)
    position = model.Position(
        position_type="text",
        old_path=path,
        new_path=path if old_line is None else path,
        old_line=old_line,
        new_line=None if old_line is not None else new_line,
        line_range=line_range,
    )
    thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
    return make_review(refs, [thread]), thread


# 1. 앵커 줄 위에 줄 삽입
def test_insert_above_shifts_location(git_repo, commit):
    review, thread = scenario(
        git_repo, commit, head=HEAD_CONTENT, worktree="NEW1\nNEW2\n" + HEAD_CONTENT
    )
    stats = reanchor.reanchor_all(git_repo, review)
    assert (thread.location.line, thread.location.confidence) == (5, "exact")
    assert thread.location.method == "git-diff"
    assert stats.as_dict() == {"exact": 1, "fuzzy": 0, "stale": 0}


# 2. 앵커 줄 아래에 줄 삽입
def test_insert_below_keeps_location(git_repo, commit):
    review, thread = scenario(
        git_repo, commit, head=HEAD_CONTENT, worktree=HEAD_CONTENT + "TRAILER\n"
    )
    reanchor.reanchor_all(git_repo, review)
    assert (thread.location.line, thread.location.confidence) == (3, "exact")
    # 줄이 변하지 않았으므로 git 매핑(항등 함수)이 실제로 쓰였는지까지 확인해야
    # 한다 — 문자열 탐색도 "우연히" 같은 줄(3)을 찾을 수 있어 line/confidence
    # 만으로는 주 전략이 동작했는지 구분하지 못한다.
    assert thread.location.method == "git-diff"


# 3. 앵커 줄 내용 수정
def test_modified_anchor_line_is_stale(git_repo, commit):
    review, thread = scenario(
        git_repo,
        commit,
        head=HEAD_CONTENT,
        worktree=HEAD_CONTENT.replace(TARGET, "    resp = urlopen(url)"),
    )
    reanchor.reanchor_all(git_repo, review)
    assert thread.location.confidence == "stale"
    assert thread.location.method == "none"


# 4. 인덴트만 변경
def test_indent_only_change_is_fuzzy(git_repo, commit):
    review, thread = scenario(
        git_repo,
        commit,
        head=HEAD_CONTENT,
        worktree=HEAD_CONTENT.replace(TARGET, "        resp = session.get(url)"),
    )
    reanchor.reanchor_all(git_repo, review)
    assert thread.location.confidence == "fuzzy"
    assert thread.location.method == "anchor-search"
    assert thread.location.line == 3


# 5. 앵커 줄 삭제
def test_deleted_anchor_line_is_stale(git_repo, commit):
    review, thread = scenario(
        git_repo, commit, head=HEAD_CONTENT, worktree=HEAD_CONTENT.replace(TARGET + "\n", "")
    )
    reanchor.reanchor_all(git_repo, review)
    assert thread.location.confidence == "stale"
    assert thread.location.method == "none"


# 6. 블록을 파일 내 먼 곳으로 이동
def test_block_moved_far_is_found_by_whole_file_uniqueness(git_repo, commit):
    # 단순 prepend 는 git 이 완벽히 매핑하므로 2c 경로를 거치지 않는다. 블록을
    # 파일 끝에서 앞으로 옮겨 git 이 delete+add 로 보고하게 만들고, 창(±50)
    # 밖으로 보내야 전체 유일성 탐색이 실제로 쓰인다.
    review, thread = scenario(
        git_repo,
        commit,
        head=HEAD_CONTENT + PAD * 5,
        worktree=PAD * 5 + HEAD_CONTENT,
    )
    reanchor.reanchor_all(git_repo, review)
    assert thread.location.confidence == "fuzzy"
    assert thread.location.method == "anchor-search"
    assert thread.location.line == 100 + 3


# 7. 파일 rename
def test_renamed_file_follows_new_path(git_repo, commit):
    sha = commit({"old/client.py": HEAD_CONTENT})
    (git_repo / "new").mkdir()
    subprocess.run(["git", "mv", "old/client.py", "new/client.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "mv"], cwd=git_repo, check=True)
    refs = model.DiffRefs(sha, sha, sha)
    position = model.Position("text", "old/client.py", "old/client.py", None, 3, None)
    thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
    reanchor.reanchor_all(git_repo, make_review(refs, [thread]))
    assert thread.location.path == "new/client.py"
    assert (thread.location.line, thread.location.confidence) == (3, "exact")
    # 내용이 같아도 anchor-search 로 "우연히" exact 가 나올 수 있다 — 주 전략인
    # git 매핑이 실제로 쓰였는지까지 확인해야 이 테스트가 의미가 있다.
    assert thread.location.method == "git-diff"


# 8. 파일 삭제
def test_deleted_file_is_stale(git_repo, commit):
    sha = commit({"a.py": HEAD_CONTENT, "keep.py": "x\n"})
    subprocess.run(["git", "rm", "-q", "a.py"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "rm"], cwd=git_repo, check=True)
    refs = model.DiffRefs(sha, sha, sha)
    position = model.Position("text", "a.py", "a.py", None, 3, None)
    thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
    reanchor.reanchor_all(git_repo, make_review(refs, [thread]))
    assert thread.location.confidence == "stale"


# 9. 동일 내용 줄이 창 안에 여럿
DUPLICATED = f"def a():\n{TARGET}\n    return 1\n\ndef b():\n{TARGET}\n    return 2\n"


def test_duplicate_lines_resolved_by_git_mapping(git_repo, commit):
    review, thread = scenario(
        git_repo, commit, head=DUPLICATED, worktree="INSERTED\n" + DUPLICATED, new_line=6
    )
    reanchor.reanchor_all(git_repo, review)
    assert (thread.location.line, thread.location.method) == (7, "git-diff")
    assert thread.location.confidence == "exact"


def test_duplicate_lines_resolved_by_context_when_git_unavailable(git_repo, commit):
    # git 매핑이 없으면 context 점수가 둘을 가른다. 첫 후보를 집으면 안 된다.
    review, thread = scenario(
        git_repo, commit, head=DUPLICATED, worktree="INSERTED\n" + DUPLICATED, new_line=6
    )
    reanchor.reanchor_all(git_repo, review, have_git=False)
    assert thread.location.line == 7
    assert thread.location.confidence == "fuzzy"


# 10. 멀티라인 line_range
def test_multiline_range_maps_both_ends(git_repo, commit):
    line_range = {
        "start": {"line_code": "x_3_3", "type": "new", "old_line": None, "new_line": 3},
        "end": {"line_code": "x_4_4", "type": "new", "old_line": None, "new_line": 4},
    }
    review, thread = scenario(
        git_repo,
        commit,
        head=HEAD_CONTENT,
        worktree="NEW\n" + HEAD_CONTENT,
        new_line=3,
        line_range=line_range,
    )
    reanchor.reanchor_all(git_repo, review)
    assert (thread.location.line, thread.location.line_end) == (4, 5)
    assert thread.location.confidence == "exact"
    assert thread.location.method == "git-diff"


# 11. old-side(삭제된 줄) 코멘트
def test_old_side_comment_uses_context_anchor(git_repo, commit):
    start = commit({"a.py": "def f():\n    legacy()\n    keep()\n"})
    head = commit({"a.py": "def f():\n    keep()\n"})
    (git_repo / "a.py").write_text("HEADER\ndef f():\n    keep()\n", encoding="utf-8")
    refs = model.DiffRefs(start, start, head)
    position = model.Position("text", "a.py", "a.py", 2, None, None)
    thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
    reanchor.reanchor_all(git_repo, make_review(refs, [thread]))
    assert thread.location.method == "context-anchor"
    assert thread.location.confidence == "fuzzy"
    # context_before 의 마지막 줄("def f():")을 찾아 그 아래에 붙인다.
    assert thread.location.line == 3


def test_old_side_search_uses_old_line_hint_for_long_file(git_repo, commit):
    # old-side 탐색이 position.old_line 을 창의 중심으로 쓰지 않으면 창이
    # 줄 0 에 고정돼 ±50(1~51) 밖의 context 줄은 전체 유일성 탐색에만 의존한다.
    # "KEEP" 을 두 곳(500, 797)에 둬 전체 유일성 탐색은 실패하게 만들고,
    # 올바른 창(747~847 근처)에는 797 하나만 들어오게 해 힌트가 있을 때만
    # 풀리게 한다.
    lines = [f"L{i}" for i in range(1, 1001)]
    lines[499] = "KEEP"  # 1-index 500, 창 밖의 또 다른 "KEEP" — 전체 유일성을 깬다
    lines[796] = "KEEP"  # 1-index 797, 삭제될 798 줄의 context_before 마지막 줄
    lines[797] = "TARGET_DELETED"  # 1-index 798, old_line
    start = commit({"a.py": "\n".join(lines) + "\n"})
    head_lines = lines[:797] + lines[798:]
    head = commit({"a.py": "\n".join(head_lines) + "\n"})

    refs = model.DiffRefs(start, start, head)
    position = model.Position("text", "a.py", "a.py", 798, None, None)
    thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
    reanchor.reanchor_all(git_repo, make_review(refs, [thread]))
    assert thread.location.method == "context-anchor"
    assert thread.location.line == 798
    assert thread.location.confidence == "fuzzy"

    # 힌트 없이(None) 호출하면 창이 파일 앞머리에 고정되어 두 "KEEP" 모두
    # 창 밖에 있고, 전체 유일성 탐색은 둘 다 걸려 모호해져 stale(None)이 된다 —
    # 이것이 FIX 4 이전의 실제 동작이다.
    worktree_lines = reanchor._read_worktree(git_repo / "a.py")
    assert reanchor._locate_old_side(thread, worktree_lines, None) is None


# 12. head_sha 를 확보할 수 없을 때
def test_degrades_to_anchor_search_without_git(git_repo, commit):
    review, thread = scenario(
        git_repo, commit, head=HEAD_CONTENT, worktree="NEW1\nNEW2\n" + HEAD_CONTENT
    )
    reanchor.reanchor_all(git_repo, review, have_git=False)
    assert thread.location.line == 5
    assert thread.location.method == "anchor-search"


def test_non_text_position_gets_null_location(git_repo, commit):
    sha = commit({"a.py": HEAD_CONTENT})
    refs = model.DiffRefs(sha, sha, sha)
    position = model.Position("image", "s.png", "s.png", None, None, None)
    thread = make_thread(position, None)
    stats = reanchor.reanchor_all(git_repo, make_review(refs, [thread]))
    assert thread.location is None
    # 위치가 없는 것은 "찾지 못함"이 아니므로 통계에서 제외한다.
    assert stats.as_dict() == {"exact": 0, "fuzzy": 0, "stale": 0}


def test_missing_position_gets_null_location(git_repo, commit):
    sha = commit({"a.py": HEAD_CONTENT})
    refs = model.DiffRefs(sha, sha, sha)
    thread = make_thread(None, None)
    reanchor.reanchor_all(git_repo, make_review(refs, [thread]))
    assert thread.location is None


def test_two_threads_on_same_line_both_get_locations(git_repo, commit):
    # 중복 제거하거나 한쪽을 버리면 코멘트가 사라진다.
    sha = commit({"a.py": HEAD_CONTENT})
    refs = model.DiffRefs(sha, sha, sha)
    position = model.Position("text", "a.py", "a.py", None, 3, None)
    anchor = anchor_mod.extract(git_repo, refs, position)
    first, second = make_thread(position, anchor), make_thread(position, anchor)
    second.id = "t2"
    stats = reanchor.reanchor_all(git_repo, make_review(refs, [first, second]))
    assert first.location.line == second.location.line == 3
    assert stats.as_dict() == {"exact": 2, "fuzzy": 0, "stale": 0}


def test_anchor_extraction_failure_is_stale_not_null(git_repo, commit):
    # 텍스트 위치를 가진 코멘트인데 찾지 못한 것이므로 품질 지표에 드러나야 한다.
    sha = commit({"a.py": HEAD_CONTENT})
    refs = model.DiffRefs(sha, sha, sha)
    position = model.Position("text", "a.py", "a.py", None, 999, None)
    thread = make_thread(position, None)
    stats = reanchor.reanchor_all(git_repo, make_review(refs, [thread]))
    assert thread.location.confidence == "stale"
    assert stats.stale == 1


def test_path_map_is_computed_once_regardless_of_thread_count(git_repo, commit, monkeypatch):
    # 성능 요구(코멘트 50개 pull 10초)를 받치는 구조적 보장이다. 스레드마다
    # git diff --name-status 를 돌리면 N+1 이 된다.
    sha = commit({f"m{i}.py": f"a\nb\ntarget{i}\n" for i in range(1, 11)})
    refs = model.DiffRefs(sha, sha, sha)
    threads = []
    for index in range(1, 11):
        position = model.Position("text", f"m{index}.py", f"m{index}.py", None, 3, None)
        thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
        thread.id = f"t{index}"
        threads.append(thread)

    calls = []
    original = reanchor.linemap.path_map
    monkeypatch.setattr(
        reanchor.linemap,
        "path_map",
        lambda root, head: (calls.append(head), original(root, head))[1],
    )
    reanchor.reanchor_all(git_repo, make_review(refs, threads))
    assert len(calls) == 1


def test_line_map_is_cached_per_path(git_repo, commit, monkeypatch):
    # 같은 파일에 스레드가 여럿이면 git diff -U0 은 한 번만 돌아야 한다.
    sha = commit({"a.py": "L1\nL2\nL3\nL4\n"})
    refs = model.DiffRefs(sha, sha, sha)
    threads = []
    for index, line_no in enumerate((2, 3, 4), start=1):
        position = model.Position("text", "a.py", "a.py", None, line_no, None)
        thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
        thread.id = f"t{index}"
        threads.append(thread)

    calls = []
    original = reanchor.linemap.line_map
    monkeypatch.setattr(
        reanchor.linemap,
        "line_map",
        lambda root, head, head_path, current_path: (
            calls.append((head_path, current_path)),
            original(root, head, head_path, current_path),
        )[1],
    )
    reanchor.reanchor_all(git_repo, make_review(refs, threads))
    assert calls == [("a.py", "a.py")]


def test_ensure_commits_returns_false_without_remote(git_repo, commit):
    commit({"a.py": "x\n"})
    refs = model.DiffRefs("0" * 40, "0" * 40, "1" * 40)
    assert reanchor.ensure_commits(git_repo, 1234, "feat/retry", refs) is False


def test_ensure_commits_true_when_present(git_repo, commit):
    sha = commit({"a.py": "x\n"})
    assert reanchor.ensure_commits(git_repo, 1234, "main", model.DiffRefs(sha, sha, sha)) is True


def test_ensure_commits_allow_fetch_false_skips_fetch(git_repo, commit, monkeypatch):
    # reanchor 는 네트워크를 쓰지 않기로 되어 있다 (docs/spec/cli.md §6). 커밋이
    # 없을 때도 allow_fetch=False 면 fetch 를 호출하지 않아야 한다.
    commit({"a.py": "x\n"})
    refs = model.DiffRefs("0" * 40, "0" * 40, "1" * 40)
    calls: list[str] = []
    monkeypatch.setattr(reanchor.gitcmd, "fetch", lambda root, refspec: calls.append(refspec))

    result = reanchor.ensure_commits(git_repo, 1234, "feat/retry", refs, allow_fetch=False)
    assert result is False
    assert calls == []

    # allow_fetch 의 기본값(True)은 pull 의 동작을 그대로 고정한다.
    result = reanchor.ensure_commits(git_repo, 1234, "feat/retry", refs)
    assert result is False
    assert calls != []


def test_inverted_range_end_is_dropped(git_repo, commit, monkeypatch):
    # start 와 end 는 서로 다른 메커니즘(git 매핑 vs 문자열 탐색)으로 구해지므로
    # 순서가 보장되지 않는다. anchor.line 을 일부러 틀리게 만들어 start 쪽
    # git-diff 매핑의 내용 검증을 실패시키고 문자열 탐색(가짜로 105 를 돌려줌)
    # 으로 내려가게 한다. end 는 별도 경로(line_map)로 매핑되므로 영향받지 않고
    # 정상적으로 5 가 나와 역전(line_end=5 < line=105)이 재현된다.
    line_range = {
        "start": {"line_code": "x_3_3", "type": "new", "old_line": None, "new_line": 3},
        "end": {"line_code": "x_4_4", "type": "new", "old_line": None, "new_line": 4},
    }
    review, thread = scenario(
        git_repo,
        commit,
        head=HEAD_CONTENT,
        worktree="NEW\n" + HEAD_CONTENT,
        new_line=3,
        line_range=line_range,
    )
    thread.anchor.line = "이 줄은 매핑된 worktree 줄과 내용이 다르다"
    monkeypatch.setattr(reanchor.search, "find", lambda lines, anchor, start_line: (105, "fuzzy"))

    reanchor.reanchor_all(git_repo, review)
    assert thread.location.line == 105
    assert thread.location.line_end is None
    assert thread.location.confidence == "fuzzy"


def test_git_mapping_result_must_pass_content_check(git_repo, commit, monkeypatch):
    # 라인 맵이 그럴듯하지만 내용이 다른 줄을 돌려주는 경우. 실제 git 출력으로는
    # 재현할 수 없다 — 내용이 바뀐 줄은 hunk 안에 들어가 None 으로 매핑되기
    # 때문이다. 그래서 맵을 직접 주입한다. 이 가드가 없으면 우리 산술의 버그가
    # "확신에 찬 오답"(confidence=exact, 엉뚱한 줄)으로 사용자에게 나간다.
    review, thread = scenario(git_repo, commit, head=HEAD_CONTENT, worktree=HEAD_CONTENT)
    # 한 줄 아래로 밀어 보내는 맵. map(3) == 4 이고 4 번째 줄의 내용은 anchor 와 다르다.
    monkeypatch.setattr(
        reanchor.linemap,
        "line_map",
        lambda root, head_sha, head_path, current_path: linemap.LineMap([(1, 0, 1, 1)]),
    )
    reanchor.reanchor_all(git_repo, review)
    # 내용 검증이 실패해 문자열 탐색으로 내려가고, 거기서 올바른 줄을 찾는다.
    assert thread.location.line == 3
    assert thread.location.method == "anchor-search"


def test_reanchor_rerenders_md(git_repo, commit, review_json, checkout, monkeypatch):
    commit({"a.py": "x\n"})
    checkout("feat/retry")  # review.json 의 source_branch (cli.md §2 의 브랜치 가드)
    review_json(git_repo, iid=1234, source_branch="feat/retry")
    store.write_current(git_repo, 1234)
    monkeypatch.chdir(git_repo)

    assert main(["reanchor"]) == 0

    md = store.review_md_path(git_repo, 1234)
    assert md.is_file()
    assert md.read_text(encoding="utf-8").startswith("<!-- mrq:file ")


def test_reanchor_refuses_to_write_after_the_checkout_moved(
    git_repo, commit, review_json, checkout, monkeypatch, capsys
):
    """`reanchor` 도 쓰기 명령이다 (testing.md §5, cli.md §2).

    `location` 이 재계산 가능하다는 것은 위로가 되지 않는다 — 다른 브랜치의 작업
    트리로 계산한 위치와 `confidence` 가 그럴듯한 틀린 값으로 json 에 남고 md 와
    `status` 의 품질 수치에 그대로 나오며, 그것을 덮어쓸 다음 `pull` 을 강제하는
    장치가 없다. 에디터가 키 한 번으로 부르는 경로라 경고는 읽히지 않는다.
    """
    commit({"a.py": "x\n"})
    checkout("feat/retry")
    review_json(git_repo, iid=1234, source_branch="feat/retry")
    store.write_current(git_repo, 1234)
    monkeypatch.chdir(git_repo)
    before = store.review_json_path(git_repo, 1234).read_text(encoding="utf-8")

    checkout("feat/other")  # 사람이 다른 브랜치로 옮겨갔다

    assert main(["reanchor"]) == 1

    assert store.review_json_path(git_repo, 1234).read_text(encoding="utf-8") == before
    assert not store.review_md_path(git_repo, 1234).exists()  # md 재렌더도 없다
    err = capsys.readouterr().err
    assert "feat/other" in err and "feat/retry" in err and "mrq pull" in err
