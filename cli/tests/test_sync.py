"""`mrq sync`. docs/spec/cli.md §5, docs/spec/data-model.md §5.

md 편집 테스트는 전부 `edit_block()`을 거친다 — 앵커 ID로 블록을 찾아 그 블록
**안에서만** 체크박스/답글을 바꾼다. 이웃 앵커 문자열에 기대면(예: 다음 블록의
앵커 id로 `replace` 대상을 찾는 것) 렌더 순서가 조금만 바뀌어도 엉뚱한 스레드를
건드리게 된다.
"""

import copy
import json
import re

import pytest

from mrq import model, store, surface
from mrq.__main__ import main

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"

_ANCHOR_RE = re.compile(r"^<!-- mrq:([0-9a-f]{8,})(?: v:[0-9a-f]{6})? -->$")
_STATE_CHAR = {"todo": " ", "done": "x", "replied": "~", "skipped": "-"}


@pytest.fixture
def synced(git_repo, commit, checkout, monkeypatch):
    """review.json + review.md 가 모두 있고 렌더가 최신인 상태."""
    commit({"src/api/client.py": "x\n", "src/api/session.py": "y\n"})
    checkout("feat/retry")  # 샘플의 source_branch (testing.md §5 의 브랜치 가드)
    monkeypatch.chdir(git_repo)
    review = model.loads(SAMPLE.read_text(encoding="utf-8"))
    with store.review_lock(git_repo, review.iid):
        surface.write(git_repo, review, include_resolved=True)
    store.write_current(git_repo, review.iid)
    return git_repo


def _md(root):
    return store.review_md_path(root, 1234)


def _json(root) -> model.Review:
    return model.loads(store.review_json_path(root, 1234).read_text(encoding="utf-8"))


def _anchor_index(lines: list[str], thread_id: str) -> int:
    prefix = f"<!-- mrq:{thread_id} "
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    raise AssertionError(f"앵커 {thread_id} 를 찾지 못했습니다")


def _block_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        if _ANCHOR_RE.match(lines[index]):
            return index
    return len(lines)


def edit_block(text: str, thread_id: str, *, state: str | None = None, reply: str | None = None):
    """`thread_id` 자신의 앵커로 블록을 찾아 그 안에서만 체크박스·답글을 바꾼다.

    렌더 순서(`render.order`)가 바뀌어도 테스트가 깨지지 않도록, 다음 블록의
    앵커 문자열 같은 이웃 단서를 쓰지 않는다.
    """
    lines = text.split("\n")
    start = _anchor_index(lines, thread_id)
    end = _block_end(lines, start)
    if state is not None:
        header_index = start + 1
        lines[header_index] = re.sub(
            r"^## \[.\]", f"## [{_STATE_CHAR[state]}]", lines[header_index]
        )
    if reply is not None:
        for cursor in range(start, end):
            if lines[cursor] == "### reply":
                body_start = cursor + 2  # "### reply" 다음의 고정 빈 줄 다음
                body_end = end
                while body_end > body_start and lines[body_end - 1] == "":
                    body_end -= 1
                lines[body_start:body_end] = reply.split("\n") if reply else []
                break
        else:
            raise AssertionError(f"{thread_id} 블록에 '### reply' 가 없습니다")
    return "\n".join(lines)


def remove_block(text: str, thread_id: str) -> str:
    """블록 전체(자신의 앵커부터 다음 앵커 전까지)를 지운다."""
    lines = text.split("\n")
    start = _anchor_index(lines, thread_id)
    end = _block_end(lines, start)
    return "\n".join(lines[:start] + lines[end:])


def _without_file_comment(text: str) -> str:
    """렌더마다 `rendered=` 시각이 바뀌는 첫 줄을 뺀 나머지."""
    return text.split("\n", 1)[1]


def test_sync_applies_checkbox_and_reply(synced):
    text = edit_block(
        _md(synced).read_text(encoding="utf-8"),
        "a1b2c3d4e5f6",
        state="done",
        reply="확인했습니다.",
    )
    _md(synced).write_text(text, encoding="utf-8")

    assert main(["sync"]) == 0

    thread = next(t for t in _json(synced).threads if t.id == "a1b2c3d4e5f6")
    assert thread.local.state == "done"
    assert thread.local.reply == "확인했습니다."
    assert thread.local.touched_by == "md"
    assert thread.local.touched_at is not None


def test_sync_rerenders_md_with_new_v_hash(synced):
    before = edit_block(_md(synced).read_text(encoding="utf-8"), "7a0b1c2d3e4f", state="done")
    _md(synced).write_text(before, encoding="utf-8")

    assert main(["sync"]) == 0
    after = _md(synced).read_text(encoding="utf-8")
    assert "## [x] (general)" in after

    # 재렌더가 v 를 갱신했으므로 곧바로 다시 sync 해도 아무 변화가 없다.
    # 첫 줄(`rendered=`)은 매 렌더마다 바뀌므로 그 다음부터만 비교한다.
    assert main(["sync"]) == 0
    assert _without_file_comment(_md(synced).read_text(encoding="utf-8")) == _without_file_comment(
        after
    )


def test_sync_is_a_noop_on_untouched_file(synced):
    # `location` 은 비교하지 않는다 — sync 는 매번 재앵커링하므로(cli.md §5 4단계)
    # 이 픽스처의 가짜 git 저장소(`x\n`/`y\n`) 내용으로는 위치가 바뀔 수 있다.
    # "손대지 않았다" 의 실제 불변식은 `local.*` 가 그대로인 것이다.
    before = [t.local for t in _json(synced).threads]
    assert main(["sync"]) == 0
    after = [t.local for t in _json(synced).threads]
    assert all(t.touched_by is None for t in after)
    assert before == after


def test_sync_parse_error_writes_nothing_and_exits_2(synced, capsys):
    before = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    text = _md(synced).read_text(encoding="utf-8")
    lines = text.split("\n")
    header_index = _anchor_index(lines, "7a0b1c2d3e4f") + 1
    lines[header_index] = lines[header_index].replace("## [ ]", "## [?]", 1)
    _md(synced).write_text("\n".join(lines), encoding="utf-8")

    assert main(["sync"]) == 2

    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before
    assert "review.md:" in capsys.readouterr().err


def test_sync_json_error_payload_is_pure_json(synced, capsys):
    text = _md(synced).read_text(encoding="utf-8")
    lines = text.split("\n")
    header_index = _anchor_index(lines, "7a0b1c2d3e4f") + 1
    lines[header_index] = lines[header_index].replace("## [ ]", "## [?]", 1)
    _md(synced).write_text("\n".join(lines), encoding="utf-8")

    assert main(["sync", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"][0]["line"] > 0


@pytest.fixture
def conflicted(synced):
    """AI 가 렌더 후 CLI 로 고쳤고, 사람이 md 에서 같은 스레드를 다르게 고친 상태.

    세 충돌 테스트(exit 3 자체, --prefer md, --prefer json)가 이 픽스처를
    공유한다 — 테스트 함수를 서로 호출하는 대신 상태 구성만 재사용한다.
    """
    # "렌더 후 json 변경"은 이제 시각이 아니라 `v` 핑거프린트로 판정한다
    # (docs/decisions/0008-conflict-signal-v-hash-not-timestamp.md) — 여기서
    # `touched_at` 값 자체는 판정에 쓰이지 않으므로 아무 시각이나 넣어도 된다.
    review = _json(synced)
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "replied"
    target.local.reply = "AI: 상위에서 설정 중입니다."
    target.local.touched_by = "cli"
    target.local.touched_at = surface.now()
    store.atomic_write_text(store.review_json_path(synced, 1234), model.dumps(review))

    text = edit_block(_md(synced).read_text(encoding="utf-8"), "a1b2c3d4e5f6", state="done")
    _md(synced).write_text(text, encoding="utf-8")
    return synced


def test_sync_conflict_writes_nothing_and_exits_3(conflicted, capsys):
    before = store.review_json_path(conflicted, 1234).read_text(encoding="utf-8")
    assert main(["sync", "--json"]) == 3
    assert store.review_json_path(conflicted, 1234).read_text(encoding="utf-8") == before

    payload = json.loads(capsys.readouterr().out)
    assert payload["conflicts"][0]["thread"] == "a1b2c3d4e5f6"
    assert payload["conflicts"][0]["md"]["state"] == "done"
    assert payload["conflicts"][0]["json"]["state"] == "replied"


def test_sync_prefer_md_resolves_the_conflict(conflicted):
    assert main(["sync", "--prefer", "md"]) == 0
    assert next(t for t in _json(conflicted).threads if t.id == "a1b2c3d4e5f6").local.state == (
        "done"
    )


def test_sync_prefer_json_keeps_the_cli_value(conflicted):
    assert main(["sync", "--prefer", "json"]) == 0
    thread = next(t for t in _json(conflicted).threads if t.id == "a1b2c3d4e5f6")
    assert thread.local.state == "replied"
    assert thread.local.reply == "AI: 상위에서 설정 중입니다."


def test_sync_detects_conflict_from_a_real_reply_then_stale_buffer_save(synced, capsys):
    """Critical 1 회귀 테스트 — `cli.md` §10 이 정한 순서 그대로 `mrq reply` 를
    시뮬레이션한 뒤, 사람이 그 재렌더를 보지 못한 채 **이전** 버퍼를 저장한다.

    `touched_at`/`rendered_at` 시각 비교로는 이 충돌을 절대 잡을 수 없다
    (§10 이 `touched_at` 기록 → 재렌더 순서를 강제하므로 정상 경로에서는 항상
    `touched_at <= rendered_at` 다). 이 테스트는 옛 `conflict.classify`(시각
    비교)에서는 실패하고 새 구현(`v` 핑거프린트 비교)에서만 통과해야 한다 —
    실제로 두 방향 모두 확인했다(보고서 참고).
    """
    # 사람이 지금 열어 둔 버퍼 — AI 가 손대기 전의 렌더 그대로다.
    stale_buffer = edit_block(_md(synced).read_text(encoding="utf-8"), "a1b2c3d4e5f6", state="done")

    # `mrq reply` 시뮬레이션: `touched_at` 을 먼저 기록하고(§10), 그 다음
    # `surface.write` 가 md 를 재렌더하며 `rendered_at` 을 갱신한다 — 순서가
    # 핵심이다. 역순이면 버그를 재현하지 못한다.
    review = _json(synced)
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "replied"
    target.local.reply = "AI: 상위에서 설정 중입니다."
    target.local.touched_by = "cli"
    target.local.touched_at = surface.now()
    with store.review_lock(synced, 1234):
        surface.write(synced, review, include_resolved=True)

    # 사람은 그 재렌더를 보지 못했다 — 자기 버퍼(낡은 렌더 기준)를 그대로 저장한다.
    _md(synced).write_text(stale_buffer, encoding="utf-8")

    before = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    assert main(["sync", "--json"]) == 3
    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before

    payload = json.loads(capsys.readouterr().out)
    conflict_entry = next(c for c in payload["conflicts"] if c["thread"] == "a1b2c3d4e5f6")
    assert conflict_entry["md"]["state"] == "done"
    assert conflict_entry["json"]["state"] == "replied"
    assert conflict_entry["json"]["reply"] == "AI: 상위에서 설정 중입니다."


@pytest.fixture
def with_ambiguous_prefix(synced):
    """`a1b2c3d4e5f6` 와 접두사(`a1b2`)가 겹치는 스레드를 하나 더 추가한다."""
    review = _json(synced)
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    clone = copy.deepcopy(target)
    clone.id = "a1b2ffffffff"
    clone.root_note_id = 999999
    review.threads.append(clone)
    store.atomic_write_text(store.review_json_path(synced, 1234), model.dumps(review))
    return synced


def test_sync_thread_ambiguous_prefix_exits_1_before_writing(with_ambiguous_prefix):
    # IMPORTANT 3 회귀 테스트 — 모호한 접두사가 사용자가 지정하지 않은 스레드에
    # `--prefer` 를 조용히 적용하면 안 된다.
    before_json = store.review_json_path(with_ambiguous_prefix, 1234).read_text(encoding="utf-8")
    before_md = _md(with_ambiguous_prefix).read_text(encoding="utf-8")

    assert main(["sync", "--prefer", "md", "--thread", "a1b2"]) == 1

    assert (
        store.review_json_path(with_ambiguous_prefix, 1234).read_text(encoding="utf-8")
        == before_json
    )
    assert _md(with_ambiguous_prefix).read_text(encoding="utf-8") == before_md


def test_sync_thread_unknown_prefix_exits_1(synced):
    before = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    assert main(["sync", "--prefer", "md", "--thread", "zzzzzzzzzzzz"]) == 1
    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before


def test_sync_thread_empty_string_exits_1(synced):
    before = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    assert main(["sync", "--prefer", "md", "--thread", ""]) == 1
    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before


def test_sync_refuses_review_md_of_another_mr(synced):
    _md(synced).write_text(
        _md(synced).read_text(encoding="utf-8").replace("iid=1234", "iid=9999", 1), encoding="utf-8"
    )
    before = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    assert main(["sync"]) == 1
    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before


def test_sync_refuses_newer_schema_in_md(synced):
    _md(synced).write_text(
        _md(synced).read_text(encoding="utf-8").replace("schema=1", "schema=99", 1),
        encoding="utf-8",
    )
    assert main(["sync"]) == 7


def test_sync_warns_on_stale_head_but_proceeds(synced, capsys):
    _md(synced).write_text(
        _md(synced).read_text(encoding="utf-8").replace("head=abc1234", "head=0000000", 1),
        encoding="utf-8",
    )
    assert main(["sync"]) == 0
    err = capsys.readouterr().err
    assert "0000000" in err  # review.md 가 들고 있던(낡은) head
    assert "abc1234" in err  # 실제 diff_refs.head_sha


def test_sync_without_md_guides_to_pull_render(synced):
    _md(synced).unlink()
    assert main(["sync"]) == 1


def test_sync_json_success_payload(synced, capsys):
    text = edit_block(_md(synced).read_text(encoding="utf-8"), "7a0b1c2d3e4f", state="done")
    _md(synced).write_text(text, encoding="utf-8")

    assert main(["sync", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["iid"] == 1234
    assert payload["applied"][0]["state"] == "done"
    # 이 픽스처의 git 저장소 내용(`x\n`/`y\n`)은 샘플의 anchor/hunk 와 무관하므로
    # 위치가 있던 6개 스레드(`(general)` 제외)는 모두 stale 로 재앵커링된다.
    assert payload["anchors"] == {"exact": 0, "fuzzy": 0, "stale": 6}
    assert isinstance(payload["warnings"], list)


def test_sync_leaves_threads_absent_from_md_untouched(synced):
    # review-md.md §7 — "json 에 있는데 md 에 없음" 은 조용히 통과한다.
    # --all 없이 렌더하면 resolve 된 스레드가 md 에 없는 것이 정상이다.
    review = _json(synced)
    target = next(t for t in review.threads if t.id == "e5f6a1b2c3d4")
    target.local.state = "skipped"
    store.atomic_write_text(store.review_json_path(synced, 1234), model.dumps(review))

    text = _md(synced).read_text(encoding="utf-8")
    assert "e5f6a1b2c3d4" in text
    _md(synced).write_text(remove_block(text, "e5f6a1b2c3d4"), encoding="utf-8")

    assert main(["sync"]) == 0

    after = next(t for t in _json(synced).threads if t.id == "e5f6a1b2c3d4")
    assert after.local.state == "skipped"  # 상태 유지
    assert after.local.touched_by is None  # 건드리지 않았다


def test_sync_of_crlf_saved_file_is_a_noop(synced):
    text = _md(synced).read_text(encoding="utf-8")
    _md(synced).write_text(text.replace("\n", "\r\n"), encoding="utf-8")
    assert main(["sync"]) == 0
    assert all(t.local.touched_by is None for t in _json(synced).threads)


# --- C1: 닫히지 않은 펜스가 다음 스레드의 블록을 삼키는 경로 ---------------
#
# 생산에서 텍스트 앵커 스레드는 모두 ```diff 블록을 렌더하므로, 앞 스레드의
# 답글이 열어 둔 펜스는 **다음 스레드의 diff 블록 닫는 줄**에서 닫힌다. 그
# 사이의 앵커와 헤더는 이미 건너뛴 뒤다 — 사람의 `[x]` 가 버려지고 앞 스레드의
# `local.reply` 가 그 마크업을 흡수한다. 둘 다 조용한 손실이다.


def _swallow_setup(root) -> str:
    """`d4e5f6a1b2c3` 의 답글이 펜스를 열어 두고, 사람이 `a1b2c3d4e5f6` 를 체크한 md."""
    text = _md(root).read_text(encoding="utf-8")
    text = edit_block(text, "a1b2c3d4e5f6", state="done")
    return edit_block(text, "d4e5f6a1b2c3", reply="예시:\n\n```")


def test_sync_refuses_md_whose_unclosed_fence_swallowed_another_thread(synced, capsys):
    before_json = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    before_reply = next(t for t in _json(synced).threads if t.id == "d4e5f6a1b2c3").local.reply
    _md(synced).write_text(_swallow_setup(synced), encoding="utf-8")

    assert main(["sync"]) == 2

    # 아무것도 쓰지 않았다 — 특히 손실이 **일어나지 않았다**:
    after = _json(synced)
    swallower = next(t for t in after.threads if t.id == "d4e5f6a1b2c3")
    swallowed = next(t for t in after.threads if t.id == "a1b2c3d4e5f6")
    assert swallower.local.reply == before_reply
    assert "<!-- mrq:a1b2c3d4e5f6" not in swallower.local.reply  # 마크업 흡수 없음
    assert swallowed.local.state == "todo"  # 사람의 [x] 가 "조용히 통과" 되지 않았다
    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before_json

    err = capsys.readouterr().err
    assert "a1b2c3d4e5f6" in err and "펜스" in err
    assert "review.md:" in err


def test_sync_swallowed_anchor_error_payload_names_the_lost_thread(synced, capsys):
    _md(synced).write_text(_swallow_setup(synced), encoding="utf-8")
    assert main(["sync", "--json"]) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)  # stdout 은 순수 JSON 이어야 한다
    assert any("a1b2c3d4e5f6" in e["message"] for e in payload["errors"])
    assert all(e["line"] > 0 for e in payload["errors"])
    # T8 — 에러도 경고와 같은 규칙을 쓴다: --json 이어도 stderr 로 함께 나온다.
    assert "a1b2c3d4e5f6" in captured.err


def test_sync_applies_both_edits_once_the_fence_is_closed(synced):
    # 같은 편집을 펜스만 닫아서 다시 돌리면 둘 다 반영돼야 한다 — 가드가
    # "펜스가 들어간 답글" 전체를 막아버리는 것이 아님을 고정한다.
    text = _md(synced).read_text(encoding="utf-8")
    text = edit_block(text, "a1b2c3d4e5f6", state="done")
    text = edit_block(text, "d4e5f6a1b2c3", reply="예시:\n\n```\n<!-- 인용 -->\n```")
    _md(synced).write_text(text, encoding="utf-8")

    assert main(["sync"]) == 0

    after = _json(synced)
    assert next(t for t in after.threads if t.id == "a1b2c3d4e5f6").local.state == "done"
    assert next(t for t in after.threads if t.id == "d4e5f6a1b2c3").local.reply == (
        "예시:\n\n```\n<!-- 인용 -->\n```"
    )


def test_sync_allows_an_anchor_quoted_in_a_closed_fence(synced):
    # 판정의 반대편: 펜스 안에 인용된 앵커가 review.json 에 **없는** id 면
    # §6 규칙 1 이 허용하는 평범한 인용이다. 에러가 되면 안 된다.
    text = edit_block(
        _md(synced).read_text(encoding="utf-8"),
        "d4e5f6a1b2c3",
        reply="문법은 이렇습니다:\n\n```\n<!-- mrq:ffffffffffff v:000000 -->\n```",
    )
    _md(synced).write_text(text, encoding="utf-8")

    assert main(["sync"]) == 0
    assert "mrq:ffffffffffff" in (
        next(t for t in _json(synced).threads if t.id == "d4e5f6a1b2c3").local.reply
    )


# --- T3 / T6 ---------------------------------------------------------------


def test_sync_refuses_md_without_the_mrq_file_comment(synced, capsys):
    before = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    text = _md(synced).read_text(encoding="utf-8")
    _md(synced).write_text(_without_file_comment(text), encoding="utf-8")

    assert main(["sync"]) == 2
    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before
    assert "mrq:file" in capsys.readouterr().err


def test_sync_accepts_mrq_prose_in_a_reply_and_still_applies_other_threads(synced):
    text = edit_block(
        _md(synced).read_text(encoding="utf-8"),
        "d4e5f6a1b2c3",
        reply="<!-- mrq:TODO 참고 -->\n\n나중에 보겠습니다.",
    )
    text = edit_block(text, "a1b2c3d4e5f6", state="done")
    _md(synced).write_text(text, encoding="utf-8")

    assert main(["sync"]) == 0

    after = _json(synced)
    assert next(t for t in after.threads if t.id == "a1b2c3d4e5f6").local.state == "done"
    assert "<!-- mrq:TODO 참고 -->" in (
        next(t for t in after.threads if t.id == "d4e5f6a1b2c3").local.reply
    )


# --- T7 --------------------------------------------------------------------


def test_sync_is_not_a_conflict_when_both_sides_wrote_the_same_value(synced):
    # 사람과 AI 가 같은 결론에 도달하면 보여줄 차이가 없다 — 같은 두 쪽을
    # 나란히 띄우는 충돌 화면은 사용자에게 고를 것을 주지 못한다.
    review = _json(synced)
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "done"
    target.local.reply = "확인했습니다."
    target.local.touched_by = "cli"
    target.local.touched_at = surface.now()
    store.atomic_write_text(store.review_json_path(synced, 1234), model.dumps(review))

    # md 는 AI 가 쓰기 **전** 렌더 기준(v 가 낡았다)인데 사람이 똑같은 값을 적었다.
    text = edit_block(
        _md(synced).read_text(encoding="utf-8"),
        "a1b2c3d4e5f6",
        state="done",
        reply="확인했습니다.",
    )
    _md(synced).write_text(text, encoding="utf-8")

    assert main(["sync"]) == 0
    after = next(t for t in _json(synced).threads if t.id == "a1b2c3d4e5f6")
    assert (after.local.state, after.local.reply) == ("done", "확인했습니다.")


# --- I2: 브랜치가 바뀐 뒤의 쓰기 ------------------------------------------


def test_sync_warns_when_a_reply_sits_in_todo(synced, capsys):
    # a1b2c3d4e5f6 은 기본이 `[ ]`(todo) 이고 reply 가 비어 있다. 체크박스는
    # 그대로 두고 답글만 쓴다 — push 는 todo 에 아무것도 하지 않는다(§4.7).
    text = edit_block(_md(synced).read_text(encoding="utf-8"), "a1b2c3d4e5f6", reply="초안입니다")
    _md(synced).write_text(text, encoding="utf-8")

    assert main(["sync"]) == 0

    captured = capsys.readouterr()
    assert "전송되지 않습니다" in captured.err
    assert "a1b2c3d4" in captured.err
    # 경고는 알리기만 한다 — 상태를 바꾸지 않는다(MUST NOT).
    target = next(t for t in _json(synced).threads if t.id == "a1b2c3d4e5f6")
    assert target.local.state == "todo"
    assert target.local.reply == "초안입니다"


def test_sync_refuses_to_write_after_the_checkout_moved(synced, checkout, capsys):
    before = store.review_json_path(synced, 1234).read_text(encoding="utf-8")
    text = edit_block(_md(synced).read_text(encoding="utf-8"), "a1b2c3d4e5f6", state="done")
    _md(synced).write_text(text, encoding="utf-8")

    checkout("feat/other")  # 사람이 다른 브랜치로 옮겨갔다

    assert main(["sync"]) == 1
    assert store.review_json_path(synced, 1234).read_text(encoding="utf-8") == before
    err = capsys.readouterr().err
    assert "feat/other" in err and "feat/retry" in err and "mrq pull" in err
