"""review-md.md §8 — 라운드트립 property.

hypothesis 로 "AI 가 쓸 법한 답글" 을 생성한다. 표, 중첩 펜스, 수평선, 앵커 문법
인용, `## ` 로 시작하는 줄, CRLF, 탭, 이모지, 매우 긴 한 줄, 앞뒤 공백.
"""

import copy

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mrq import mdparse, model, render
from mrq.commands import sync as sync_command

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"

FRAGMENTS = [
    "| 설정 | 이전 | 이후 |\n|---|---|---|\n| timeout | 없음 | 10s |",
    "---",
    "## 헤더처럼 보이는 줄",
    "### reply",
    # 바로 아래 column-0 앵커(ffffffffffff)는 의도적으로 뺐다: 펜스 밖에 있으면
    # 파서가 §6 규칙 2 에 따라 새 블록 시작으로 인식해 앞 블록의 reply 가 거기서
    # 잘린다 — 파서 버그가 아니라 생성 데이터가 property 의 전제(단일 블록 reply)를
    # 깨는 경우라 FRAGMENTS 에서 제외한다. 펜스로 인용한 형태(아래)는 유지한다.
    "<!-- mrq:file schema=1 iid=9999 head=deadbee rendered=x -->",
    "```\n<!-- mrq:ffffffffffff v:000000 -->\n```",
    "````markdown\n```python\nprint('중첩')\n```\n````",
    "~~~\n~~~",
    "\tタブ\t사이\t",
    "이모지 🎉 와 한글",
    "x" * 500,
    "  앞뒤 공백  ",
    "줄1\r\n줄2",
    "",
    "> 인용처럼 보이는 줄",
    "- [ ] 체크박스처럼 보이는 줄",
]


# 닫히지 않은 펜스는 라운드트립 property 의 전제를 깰 수밖에 없다 — 블록 경계가
# 펜스 추적(§6 규칙 1)에 달려 있으므로 열린 펜스는 뒤따르는 스레드의 앵커를
# 삼키거나(다음 블록의 ```diff 닫는 줄이 펜스를 닫는다) 파일 끝까지 이어진다.
# 그래서 `render(parse(render(j))) == render(j)` 를 요구하는 대신 "조용히 지나가지
# 않는다"를 요구한다 — 에러이거나, `commands.sync` 가 에러로 올리는 삼킨 앵커다.
UNBALANCED_FENCE_FRAGMENTS = [
    "```",
    "```python\nprint('열기만 하고 닫지 않는다')",
]


def _review() -> model.Review:
    return model.loads(SAMPLE.read_text(encoding="utf-8"))


def _apply(review: model.Review, parsed: mdparse.Parsed) -> None:
    """파싱된 블록을 review 에 적용한다.

    `review.json` 에 없는 앵커 ID 는 경고로 무시한다(§7) — 생성된 답글이 우연히
    앵커처럼 보이는 줄을 포함해도(예: 펜스 밖으로 새 블록을 만드는 경우) 모르는
    thread_id 에 대해 KeyError 를 내지 않는다.
    """
    by_id = {t.id: t for t in review.threads}
    for block in parsed.blocks:
        thread = by_id.get(block.thread_id)
        if thread is None:
            continue
        if block.state is not None:
            thread.local.state = block.state
        if block.reply is not None:
            thread.local.reply = block.reply


replies = st.lists(
    st.one_of(st.sampled_from(FRAGMENTS), st.text(max_size=40)), min_size=0, max_size=6
).map("\n\n".join)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(reply=replies, state=st.sampled_from(["todo", "done", "replied", "skipped"]))
def test_render_parse_render_is_byte_stable(reply, state):
    review = _review()
    review.threads[1].local.reply = reply
    review.threads[1].local.state = state

    first = render.render(review, include_resolved=True)
    parsed = mdparse.parse(first)
    assert parsed.errors == [], parsed.errors

    second_input = copy.deepcopy(review)
    _apply(second_input, parsed)
    assert render.render(second_input, include_resolved=True) == first


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(reply=replies)
def test_reply_survives_the_round_trip(reply):
    review = _review()
    review.threads[1].local.reply = reply

    parsed = mdparse.parse(render.render(review, include_resolved=True))
    block = next(b for b in parsed.blocks if b.thread_id == review.threads[1].id)
    assert block.reply == render.normalize_reply(reply)


@settings(max_examples=200, deadline=None)
@given(reply=replies)
def test_v_hash_matches_after_round_trip(reply):
    # 사람이 손대지 않은 파일을 sync 해도 "편집됨" 으로 잡히면 안 된다.
    review = _review()
    review.threads[1].local.reply = reply
    review.threads[1].local.state = "replied"

    parsed = mdparse.parse(render.render(review, include_resolved=True))
    block = next(b for b in parsed.blocks if b.thread_id == review.threads[1].id)
    assert block.v == render.vhash(block.state, block.reply)


@settings(max_examples=200, deadline=None)
@given(reply=replies)
def test_crlf_saved_file_round_trips(reply):
    review = _review()
    review.threads[1].local.reply = reply

    first = render.render(review, include_resolved=True)
    parsed = mdparse.parse(first.replace("\n", "\r\n"))
    assert parsed.errors == []

    applied = copy.deepcopy(review)
    _apply(applied, parsed)
    assert render.render(applied, include_resolved=True) == first


def test_normalize_reply_is_idempotent_on_every_fragment():
    for fragment in FRAGMENTS + UNBALANCED_FENCE_FRAGMENTS:
        once = render.normalize_reply(fragment)
        assert render.normalize_reply(once) == once


@pytest.mark.parametrize("fragment", UNBALANCED_FENCE_FRAGMENTS)
@pytest.mark.parametrize("position", [0, -1])
def test_unbalanced_fence_in_a_reply_is_reported_not_silently_swallowed(fragment, position):
    """§7 의 에러 두 줄(미닫힘 펜스 · 삼킨 앵커)을 라운드트립 쪽에서 고정한다.

    `position=0` 은 뒤에 ```diff 블록을 가진 스레드가 따라오는 생산 모양이다 —
    그 블록의 닫는 줄이 펜스를 닫으므로 미닫힘 검사로는 잡히지 않고 앵커만
    사라진다. `position=-1` 은 펜스가 파일 끝까지 이어지는 변형이다.
    """
    review = _review()
    target = render.order(render.visible(review.threads, include_resolved=True))[position]
    target.local.reply = fragment

    parsed = mdparse.parse(render.render(review, include_resolved=True))
    # 판정은 생산 코드 그대로 쓴다 — 테스트가 규칙을 복사하면 둘이 갈라진다.
    escalated = sync_command._swallowed_anchor_errors(review, parsed)

    assert parsed.errors or escalated, "닫히지 않은 펜스가 조용히 지나갔다"
    if position == 0:
        # 삼킨 쪽: 사라진 앵커가 정확히 지목돼야 한다.
        assert [m.line for m in escalated] and all(m.line > 0 for m in escalated)
