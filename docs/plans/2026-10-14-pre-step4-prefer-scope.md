# 계획 4 전 과제 — `sync --prefer` 스코프 문법

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mrq sync` 가 충돌을 **스레드마다 다른 방향으로** 해소할 수 있게 만든다.

**Architecture:** `--prefer` 를 `[ID=]md|json` 반복 플래그로 바꾸고 `--thread` 를 없앤다.
파싱(`prefer.parse`)과 리뷰 대조(`prefer.resolve`)를 새 순수 모듈로 분리하고,
`conflict.plan_sync` 는 완성된 `Resolution` 하나만 받는다. 해소 규칙은 **좁은 스코프가
순서와 무관하게 이긴다**.

**Tech Stack:** Python 3.12, `argparse`, pytest, ruff.

**Spec:** `docs/plans/2026-10-14-plugin-emacs-design.md` 1부 (§1.1 ~ §1.5)

## Global Constraints

- `cli.md` §2 — `--json` 일 때 **stdout 은 순수 JSON 객체 하나**. 경고·에러는 전부 stderr
- `data-model.md` §5.3 — 충돌이 **하나라도** 남으면 아무것도 쓰지 않고 **exit 3**
- `cli.md` §1 — `<thread>` 인자는 **유일한 접두사**를 허용한다. 여럿에 걸리면 exit 1 + 후보
- 접두사 해석은 `threads.resolve_ref` **한 곳**에만 둔다. `conflict.py` 는 완전한 id 만 받는다
- `push.py:80` 의 `mdsync.perform(root, iid, path)` 가 깨지면 안 된다 — 새 인자는
  키워드 전용이고 기본값을 가진다
- 테스트는 `cd cli && ./.venv/bin/python -m pytest`. 린트는 `./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .`

## Review Focus

스펙이 함의하지만 과제의 테스트가 저절로 덮지는 않는 입력들. 각 줄의 테스트를 담당
과제에 넣어 뒀다.

1. **망가진 `--prefer` 값** — `""`, `"="`, `"a1b2="`, `"=md"`, `"a1b2=xml"` 이 전부
   exit 1 과 사람이 읽을 수 있는 메시지로 끝나야 한다. argparse 의 `choices` 가
   사라지므로 이 검증은 전부 우리 코드다 → **Task 1**
2. **스코프 없는 항목이 셋 이상** — `--prefer md --prefer json --prefer md` 는
   마지막(`md`)이 이긴다. "같은 스코프 안에서는 뒤가 이긴다" 를 2회가 아니라
   3회로 확인한다 → **Task 1**
3. **`push` 의 내부 `sync`** — `push.py:80` 은 `--prefer` 를 주지 않는다. 시그니처
   변경 뒤에도 `push` 가 충돌을 만나면 exit 3 으로 끝나고 아무것도 보내지 않아야
   한다 → **Task 4**
4. **`--prefer` 를 줬는데 충돌이 0건** — 정상 종료(exit 0)이고, `ID=` 를 준 경우에만
   "충돌이 아닙니다" 경고가 난다. 스코프 없는 `--prefer md` 는 경고하지 않는다
   (충돌이 없을 때 쓰는 것이 이상하지 않다) → **Task 3**
5. **접두사가 `md`/`json` 과 겹치는 스레드** — 16진수 id 에서는 도달 불가지만
   가드가 실제로 동작해야 한다. 가짜 id 를 가진 `review.json` 으로 확인한다
   → **Task 2**

---

## File Structure

| 파일 | 책임 |
|---|---|
| `cli/src/mrq/prefer.py` | **새 파일.** `--prefer` 값의 파싱과 리뷰 대조. 순수 |
| `cli/src/mrq/conflict.py` | `plan_sync` 가 `Resolution` 을 받는다. 미사용 pick 경고 |
| `cli/src/mrq/mdsync.py` | `perform` 시그니처, exit 3 안내 메시지 |
| `cli/src/mrq/cli.py` | `--prefer` 를 `append` 로, `--thread` 삭제 |
| `cli/src/mrq/commands/sync.py` | 인자 전달 |
| `cli/src/mrq/threads.py` | 독스트링의 `sync --thread` 언급 |
| `cli/tests/test_prefer.py` | **새 파일.** Task 1·2 |
| `cli/tests/test_sync.py` | Task 3·4·5 |

---

## Task 1: `prefer.parse` — 값 하나의 문법

**Files:**
- Create: `cli/src/mrq/prefer.py`
- Test: `cli/tests/test_prefer.py`

**Interfaces:**
- Consumes: `mrq.errors.UsageError`
- Produces:
  - `prefer.Preference` — `frozen dataclass(ref: str | None, direction: str)`.
    `ref is None` 이 "스코프 없음(전체 기본값)"
  - `prefer.parse(values: Sequence[str]) -> list[Preference]`

- [ ] **Step 1: Write the failing test**

`cli/tests/test_prefer.py`:

```python
"""`--prefer [ID=]md|json` 의 파싱과 해소. docs/spec/cli.md §5."""

from __future__ import annotations

import pytest

from mrq import prefer
from mrq.errors import UsageError


def test_scopeless_value_is_a_default():
    assert prefer.parse(["md"]) == [prefer.Preference(None, "md")]


def test_scoped_value_binds_to_a_thread_ref():
    assert prefer.parse(["a1b2=json"]) == [prefer.Preference("a1b2", "json")]


def test_mixed_values_keep_their_order():
    assert prefer.parse(["md", "f6e5=json"]) == [
        prefer.Preference(None, "md"),
        prefer.Preference("f6e5", "json"),
    ]


def test_no_values_is_empty():
    assert prefer.parse([]) == []
    assert prefer.parse(None) == []


@pytest.mark.parametrize(
    "value",
    ["", "=", "a1b2=", "=md", "a1b2=xml", "xml", "a1b2=md=json"],
)
def test_broken_values_are_usage_errors(value):
    with pytest.raises(UsageError):
        prefer.parse([value])


def test_error_message_names_the_bad_value_and_the_grammar():
    with pytest.raises(UsageError) as caught:
        prefer.parse(["a1b2=xml"])
    assert "a1b2=xml" in str(caught.value)
    assert "md" in str(caught.value) and "json" in str(caught.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && ./.venv/bin/python -m pytest tests/test_prefer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mrq.prefer'`

- [ ] **Step 3: Write minimal implementation**

`cli/src/mrq/prefer.py`:

```python
"""`sync --prefer [ID=]md|json` 의 파싱과 해소. docs/spec/cli.md §5.

플래그 하나에 스코프 접두사를 **선택적으로** 붙인다 (`RUST_LOG=debug` 대
`RUST_LOG=mycrate=trace` 와 같은 모양). 플래그를 둘로 나누지 않는 이유는
`--prefer md` 의 값이 "일괄" 이 아니라 **"id 를 타이핑하지 않아도 된다"** 이기
때문이다 — 충돌 하나짜리 경우에도 그쪽이 낫고, 터미널의 사람과 AI 에이전트가
쓰는 경로다.

해소 규칙: **좁은 스코프가 순서와 무관하게 이긴다. 같은 스코프 안에서는 뒤가
이긴다.** 위치 기반 fold 가 아니다 — fold 는 "앞의 개별 지정을 뒤의 전역 항목이
지운다" 는 모서리를 만드는데, `chmod`·`.gitignore`·CSS·`RUST_LOG` 가 전부
반대로 동작하므로 반대로 기대하는 사람이 생긴다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mrq.errors import UsageError

DIRECTIONS = ("md", "json")


@dataclass(frozen=True)
class Preference:
    """`--prefer` 한 개. `ref is None` 이면 스코프 없음(전체 기본값)."""

    ref: str | None
    direction: str


def parse(values: Sequence[str] | None) -> list[Preference]:
    """`--prefer` 값들을 `Preference` 리스트로. 문법 오류는 `UsageError`(exit 1).

    리뷰를 보지 않는다 — 접두사 해석과 불변식 가드는 `resolve` 의 몫이다.
    """
    out: list[Preference] = []
    for value in values or ():
        out.append(_one(value))
    return out


def _one(value: str) -> Preference:
    ref: str | None = None
    direction = value
    if "=" in value:
        ref, _, direction = value.partition("=")
        if not ref:
            raise _bad(value)
    if direction not in DIRECTIONS:
        raise _bad(value)
    return Preference(ref, direction)


def _bad(value: str) -> UsageError:
    return UsageError(
        f"--prefer {value!r} 를 해석할 수 없습니다. "
        "`--prefer md`, `--prefer json`, 또는 `--prefer <스레드>=md|json` 형태로 주세요."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && ./.venv/bin/python -m pytest tests/test_prefer.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Add the Review Focus #2 test (스코프 없는 항목 셋)**

이 과제는 파싱만 하므로 순서가 보존되는지만 확인한다. 실제 "뒤가 이긴다" 는
Task 2 의 `resolve` 가 결정한다.

`cli/tests/test_prefer.py` 에 추가:

```python
def test_three_scopeless_values_all_survive_parsing():
    # 어느 것이 이기는지는 resolve 의 몫이다. parse 는 버리지 않는다.
    assert prefer.parse(["md", "json", "md"]) == [
        prefer.Preference(None, "md"),
        prefer.Preference(None, "json"),
        prefer.Preference(None, "md"),
    ]
```

- [ ] **Step 6: Run and commit**

```bash
cd cli && ./.venv/bin/python -m pytest tests/test_prefer.py -v
./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
cd .. && git add cli/src/mrq/prefer.py cli/tests/test_prefer.py
git commit -m "prefer.parse — --prefer [ID=]md|json 의 문법"
```

---

## Task 2: `prefer.resolve` — 리뷰 대조와 불변식 가드

**Files:**
- Modify: `cli/src/mrq/prefer.py`
- Test: `cli/tests/test_prefer.py`

**Interfaces:**
- Consumes: `prefer.Preference`, `threads.resolve_ref(review, ref) -> model.Thread`
- Produces:
  - `prefer.Resolution` — `dataclass(default: str | None, picks: dict[str, str])`
    with `direction_for(thread_id: str) -> str | None`
  - `prefer.resolve(review, prefs: list[Preference]) -> Resolution`

- [ ] **Step 1: Write the failing test**

`cli/tests/test_prefer.py` 에 추가. `review_with_threads` 헬퍼는 기존
`tests/test_sync.py` 가 쓰는 픽스처 빌더를 재사용하지 말고 여기서 최소한으로
만든다 — 이 모듈은 `model.Review` 의 `threads[].id` 만 본다.

```python
from mrq import model


def _review(*ids: str) -> model.Review:
    """`prefer.resolve` 는 id 만 본다. 나머지 필드는 로더의 기본값으로 둔다."""
    source = {
        "schema_version": 1,
        "project": "g/p",
        "iid": 1,
        "title": "t",
        "web_url": "http://x/-/merge_requests/1",
        "mr_state": "opened",
        "source_branch": "b",
        "diff_refs": {"base_sha": "a", "start_sha": "b", "head_sha": "c"},
        "me": {"id": 1, "username": "me", "can_resolve": True},
        "capabilities": {"draft_notes": True},
        "pulled_at": "2026-10-14T00:00:00+09:00",
        "rendered_at": None,
        "threads": [
            {
                "id": tid,
                "root_note_id": 100 + i,
                "server": {
                    "resolvable": True,
                    "resolved": False,
                    "repliable": True,
                    "updated_at": "2026-10-05T06:30:00.000Z",
                    "note_count": 1,
                },
                "position": None,
                "anchor": None,
                "location": None,
                "notes": [
                    {
                        "id": 100 + i,
                        "author": "jdoe",
                        "created_at": "2026-10-05T05:02:11.000Z",
                        "updated_at": "2026-10-05T05:02:11.000Z",
                        "body": "b",
                        "mine": False,
                        "suggestions": [],
                    }
                ],
                "local": {
                    "state": "todo",
                    "reply": "",
                    "touched_at": None,
                    "touched_by": None,
                    "pushed_hash": None,
                    "push_error": None,
                },
            }
            for i, tid in enumerate(ids)
        ],
    }
    import json as _json

    return model.loads(_json.dumps(source))


def test_scopeless_sets_the_default():
    got = prefer.resolve(_review("aaa111", "bbb222"), prefer.parse(["md"]))
    assert got.default == "md"
    assert got.picks == {}
    assert got.direction_for("aaa111") == "md"


def test_scoped_beats_the_default_regardless_of_order():
    review = _review("aaa111", "bbb222")
    forward = prefer.resolve(review, prefer.parse(["md", "bbb=json"]))
    backward = prefer.resolve(review, prefer.parse(["bbb=json", "md"]))
    assert forward == backward
    assert forward.direction_for("aaa111") == "md"
    assert forward.direction_for("bbb222") == "json"


def test_last_wins_within_the_same_scope():
    review = _review("aaa111", "bbb222")
    got = prefer.resolve(review, prefer.parse(["md", "json", "md"]))
    assert got.default == "md"
    scoped = prefer.resolve(review, prefer.parse(["aaa=md", "aaa=json"]))
    assert scoped.picks == {"aaa111": "json"}


def test_no_preferences_resolves_to_nothing():
    got = prefer.resolve(_review("aaa111"), [])
    assert got.default is None
    assert got.picks == {}
    assert got.direction_for("aaa111") is None


def test_unknown_ref_is_a_usage_error():
    with pytest.raises(UsageError):
        prefer.resolve(_review("aaa111"), prefer.parse(["zzz=md"]))


def test_ambiguous_prefix_is_a_usage_error_listing_candidates():
    with pytest.raises(UsageError) as caught:
        prefer.resolve(_review("aaa111", "aaa222"), prefer.parse(["aaa=md"]))
    assert "aaa111" in str(caught.value) and "aaa222" in str(caught.value)


def test_scopeless_value_colliding_with_a_thread_prefix_is_refused():
    # discussion id 는 SHA1 16진수라 도달 불가다. 가정을 불변식으로 바꾼다 —
    # 깨지면 조용한 오동작이 아니라 에러가 난다.
    with pytest.raises(UsageError) as caught:
        prefer.resolve(_review("md0001"), prefer.parse(["md"]))
    assert "md0001" in str(caught.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && ./.venv/bin/python -m pytest tests/test_prefer.py -v`
Expected: FAIL — `AttributeError: module 'mrq.prefer' has no attribute 'resolve'`

- [ ] **Step 3: Write minimal implementation**

`cli/src/mrq/prefer.py` 에 추가 (상단 import 에 `from mrq import threads` 를 더한다 —
`threads` 는 `model`·`render`·`errors` 만 쓰므로 순환이 없다):

```python
@dataclass
class Resolution:
    """해소 방향. `picks` 의 키는 **완전한** thread id 다."""

    default: str | None = None
    picks: dict[str, str] = field(default_factory=dict)

    def direction_for(self, thread_id: str) -> str | None:
        return self.picks.get(thread_id, self.default)

    def __bool__(self) -> bool:
        return self.default is not None or bool(self.picks)


def resolve(review, prefs: list[Preference]) -> Resolution:
    """`Preference` 들을 리뷰에 대조해 `Resolution` 으로 접는다.

    좁은 스코프가 순서와 무관하게 이기므로 전역과 개별을 **따로** 접는다.
    접두사 해석은 `threads.resolve_ref` 에 맡긴다 (`cli.md` §1 MUST) — 모호한
    접두사가 지정하지 않은 스레드에 방향을 적용하는 사고를 막는 자리다.
    """
    out = Resolution()
    for pref in prefs:
        if pref.ref is None:
            _guard_collision(review, pref.direction)
            out.default = pref.direction
        else:
            out.picks[threads.resolve_ref(review, pref.ref).id] = pref.direction
    return out


def _guard_collision(review, direction: str) -> None:
    """스코프 없는 값이 실제 스레드 접두사와 겹치면 거부한다.

    discussion id 는 SHA1 16진수(`[0-9a-f]`)이고 `md` 의 `m`, `json` 의
    `j`·`s`·`o`·`n` 은 16진수가 아니므로 도달할 수 없다. 그래도 막아 두는 이유는
    이 사실이 깨졌을 때 **조용한 오동작**(사용자가 지목한 스레드 대신 전체에
    방향이 걸린다)이 아니라 에러가 나게 하기 위해서다.
    """
    hit = [t.id for t in review.threads if t.id.startswith(direction)]
    if hit:
        raise UsageError(
            f"--prefer {direction!r} 가 스레드 id {', '.join(hit)} 의 접두사와 겹칩니다. "
            f"전체에 적용하려면 다른 표기가 필요하고, 그 스레드만 지목하려면 "
            f"`--prefer {hit[0]}={direction}` 처럼 주세요."
        )
```

`from dataclasses import dataclass` 를 `from dataclasses import dataclass, field` 로
바꾼다.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cli && ./.venv/bin/python -m pytest tests/test_prefer.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
cd cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
cd .. && git add cli/src/mrq/prefer.py cli/tests/test_prefer.py
git commit -m "prefer.resolve — 좁은 스코프가 순서와 무관하게 이긴다"
```

---

## Task 3: `conflict.plan_sync` 가 `Resolution` 을 받는다

**Files:**
- Modify: `cli/src/mrq/conflict.py:79-123` (`plan_sync`), 그리고 `_targeted` 삭제
- Test: `cli/tests/test_sync.py`

**Interfaces:**
- Consumes: `prefer.Resolution`
- Produces: `conflict.plan_sync(review, parsed, *, resolution: prefer.Resolution | None = None)`
  — 반환 타입은 그대로 `tuple[list[Applied], list[Conflict], list[mdparse.Message]]`

- [ ] **Step 1: Write the failing test**

`cli/tests/test_sync.py` 의 `conflicted` 픽스처(173행) 옆에 **두 스레드가 동시에
충돌한** 픽스처를 더한다. `rendered.json` 의 스레드는 `7a0b1c2d3e4f`(general),
`a1b2c3d4e5f6`, `b2c3d4e5f6a1`, `c3d4e5f6a1b2`, `d4e5f6a1b2c3`, `e5f6a1b2c3d4`,
`f6a1b2c3d4e5` 일곱이다.

```python
@pytest.fixture
def two_conflicts(synced):
    """두 스레드가 동시에 충돌한 상태. 혼합 방향 해소의 대상이다.

    `conflicted` 와 같은 구성을 둘로 늘린 것이다 — AI 가 렌더 후 CLI 로 고쳤고
    사람이 md 에서 같은 스레드를 다르게 고쳤다.
    """
    review = _json(synced)
    for thread_id, reply in (
        ("a1b2c3d4e5f6", "AI: 상위에서 설정 중입니다."),
        ("b2c3d4e5f6a1", "AI: 세션 재사용이 맞습니다."),
    ):
        target = next(t for t in review.threads if t.id == thread_id)
        target.local.state = "replied"
        target.local.reply = reply
        target.local.touched_by = "cli"
        target.local.touched_at = surface.now()
    store.atomic_write_text(store.review_json_path(synced, 1234), model.dumps(review))

    text = _md(synced).read_text(encoding="utf-8")
    text = edit_block(text, "a1b2c3d4e5f6", state="done")
    text = edit_block(text, "b2c3d4e5f6a1", state="skipped")
    _md(synced).write_text(text, encoding="utf-8")
    return synced


def test_sync_scoped_prefer_leaves_the_other_conflict(two_conflicts, capsys):
    """부분 해소는 **여전히 전부 실패**다 (data-model.md §5.3).

    이것이 계획 4 의 충돌 UI 모양을 결정한다 — 키를 누를 때마다 sync 를 부르면
    첫 키부터 실패한다.
    """
    before = store.review_json_path(two_conflicts, 1234).read_text(encoding="utf-8")
    assert main(["sync", "--json", "--prefer", "a1b2=md"]) == 3
    assert store.review_json_path(two_conflicts, 1234).read_text(encoding="utf-8") == before
    payload = json.loads(capsys.readouterr().out)
    assert [c["thread"] for c in payload["conflicts"]] == ["b2c3d4e5f6a1"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--prefer", "a1b2=md", "--prefer", "b2c3=json"],
        ["--prefer", "b2c3=json", "--prefer", "a1b2=md"],
        ["--prefer", "md", "--prefer", "b2c3=json"],
        ["--prefer", "b2c3=json", "--prefer", "md"],
    ],
)
def test_sync_narrow_scope_wins_regardless_of_order(two_conflicts, flags):
    """좁은 스코프가 순서와 무관하게 이긴다.

    뒤의 두 경우가 위치 기반 fold 와 갈린다 — fold 였다면 세 번째는 b2c3 도
    md 가 되고 네 번째는 전부 md 가 된다.
    """
    assert main(["sync", *flags]) == 0
    review = _json(two_conflicts)
    assert next(t for t in review.threads if t.id == "a1b2c3d4e5f6").local.state == "done"
    assert next(t for t in review.threads if t.id == "b2c3d4e5f6a1").local.state == "replied"


def test_sync_pick_on_a_non_conflicting_thread_warns(conflicted, capsys):
    """Review Focus #4 — `ID=` 로 지목했는데 충돌이 아니면 경고한다.

    스코프 없는 `--prefer md` 는 경고하지 않는다 — 충돌이 없을 때 쓰는 것이
    이상하지 않다.
    """
    assert main(["sync", "--prefer", "md", "--prefer", "f6a1=json"]) == 0
    assert "충돌이 아닙니다" in capsys.readouterr().err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cli && ./.venv/bin/python -m pytest tests/test_sync.py -k "scoped or narrow or non_conflicting" -v`
Expected: FAIL — `--prefer` 가 아직 `choices=["md","json"]` 이라 `a1b2=md` 가 argparse
단계에서 exit 2 로 거부된다

- [ ] **Step 3: Write minimal implementation**

`cli/src/mrq/conflict.py`:

```python
def plan_sync(
    review,
    parsed: mdparse.Parsed,
    *,
    resolution: "prefer.Resolution | None" = None,
) -> tuple[list[Applied], list[Conflict], list[mdparse.Message]]:
    """무엇을 반영하고 무엇이 충돌인지 계산한다. 아무것도 변경하지 않는다.

    `resolution` 의 방향은 **충돌로 판정된 스레드에만** 적용된다. 지목했는데
    충돌이 아니면 경고한다 — 오타가 조용히 삼켜지는 것을 막는다.
    """
    by_id = {t.id: t for t in review.threads}
    applied: list[Applied] = []
    conflicts: list[Conflict] = []
    warnings: list[mdparse.Message] = []
    used_picks: set[str] = set()

    for block in parsed.blocks:
        thread = by_id.get(block.thread_id)
        if thread is None:
            warnings.append(
                mdparse.Message(
                    block.line, f"review.json 에 없는 앵커 ID {block.thread_id} — 무시합니다"
                )
            )
            continue
        decision = classify(thread, block)
        if decision == "conflict" and resolution is not None:
            direction = resolution.direction_for(thread.id)
            if direction is not None:
                if thread.id in resolution.picks:
                    used_picks.add(thread.id)
                decision = "apply-md" if direction == "md" else "keep-json"
        state, reply = md_values(thread, block)
        if decision == "apply-md":
            applied.append(
                Applied(
                    thread=thread.id,
                    state=state,
                    reply=reply,
                    reply_changed=reply != render.normalize_reply(thread.local.reply),
                )
            )
        elif decision == "conflict":
            conflicts.append(
                Conflict(
                    thread=thread.id,
                    md_state=state,
                    md_reply=reply,
                    json_state=thread.local.state,
                    json_reply=render.normalize_reply(thread.local.reply),
                )
            )

    if resolution is not None:
        for thread_id in resolution.picks:
            if thread_id not in used_picks:
                warnings.append(
                    mdparse.Message(
                        None,
                        f"{thread_id}: 충돌이 아닙니다 — `--prefer` 지정을 무시합니다",
                    )
                )
    warnings += _todo_with_reply_warnings(review, parsed, applied)
    return applied, conflicts, warnings
```

`_targeted` 함수를 **삭제**한다. 파일 상단에 `from mrq import mdparse, model, prefer, render`
를 더한다 — `prefer` 는 `errors`·`threads` 만 쓰고 `threads` 는 `model`·`render` 만
쓰므로 순환이 없다.

`"prefer.Resolution | None"` 의 따옴표는 뺀다 (`from __future__ import annotations`
가 이미 있다).

- [ ] **Step 4: Run test to verify it still fails on the CLI surface**

Run: `cd cli && ./.venv/bin/python -m pytest tests/test_sync.py -v`
Expected: 기존 `--prefer md` 테스트가 FAIL — `plan_sync` 가 `prefer=`/`only=` 를
더는 받지 않는다. Task 4 가 호출부를 고친다.

- [ ] **Step 5: Commit (테스트는 아직 빨갛다 — Task 4 와 함께 녹색이 된다)**

```bash
cd .. && git add cli/src/mrq/conflict.py
git commit -m "conflict.plan_sync 가 Resolution 하나를 받는다"
```

---

## Task 4: CLI 표면 교체 — `--thread` 삭제

**Files:**
- Modify: `cli/src/mrq/cli.py:32-37`
- Modify: `cli/src/mrq/mdsync.py:29-36` (`perform` 시그니처), `:80-81`, `:182`
- Modify: `cli/src/mrq/commands/sync.py:16-22`
- Modify: `cli/src/mrq/threads.py:4` (독스트링)
- Test: `cli/tests/test_sync.py`, `cli/tests/test_push.py`

**Interfaces:**
- Consumes: `prefer.parse`, `prefer.resolve`
- Produces: `mdsync.perform(root, iid, path, *, prefer_values: Sequence[str] | None = None)`
  — `push.py:80` 의 `mdsync.perform(root, iid, path)` 가 그대로 동작한다

- [ ] **Step 1: Write the failing test (Review Focus #3)**

`cli/tests/test_push.py` 에 추가:

`cli/tests/test_push.py` 에 추가한다. 이 파일에 이미 있는 충돌 셋업 픽스처를 쓰고,
없으면 `test_sync.py` 의 `conflicted` 와 같은 구성을 `test_push.py` 의 픽스처 위에
만든다. 가짜 `glab` 은 `conftest.py:72` 의 `glab` 픽스처이고 호출 기록은
`glab.calls()` 다.

```python
def test_push_still_refuses_on_conflict_after_prefer_rework(conflicted, glab):
    """`push` 는 `--prefer` 를 주지 않는다 (`push.py:80`).

    시그니처가 바뀐 뒤에도 내부 `sync` 가 충돌을 만나면 exit 3 이고 쓰기 요청이
    한 건도 나가지 않아야 한다 (`cli.md` §9).
    """
    assert main(["push"]) == 3
    assert [c for c in glab.calls() if c.get("method") not in (None, "GET")] == []
```

> **실행자 주의:** `glab.calls()` 의 각 항목 모양을 `conftest.py` 의 가짜 `glab`
> 스크립트(`cli/tests/bin/glab`)에서 확인하고, "쓰기 호출이 0건" 을 그 모양에 맞게
> 단언하라. `test_push.py` 에 이미 같은 단언을 하는 테스트가 있으면 그 표현을
> 그대로 베껴라 — 새 표현을 만들지 마라.

- [ ] **Step 2: Run to verify it fails**

Run: `cd cli && ./.venv/bin/python -m pytest tests/ -v`
Expected: Task 3 때문에 여러 테스트가 FAIL (`plan_sync() got an unexpected keyword argument 'prefer'`)

- [ ] **Step 3: Write the implementation**

`cli/src/mrq/cli.py` — `sync` 파서:

```python
    sync = sub.add_parser("sync", help="review.md 를 json 에 반영하고 재앵커링한다")
    sync.add_argument("--json", action="store_true")
    sync.add_argument(
        "--prefer",
        action="append",
        default=None,
        metavar="[ID=]md|json",
        help="충돌 해소 방향. 스코프 없이 주면 전체, `ID=` 를 붙이면 그 스레드만. "
        "반복 가능하며 좁은 스코프가 순서와 무관하게 이긴다",
    )
```

`--thread` 줄 셋을 **삭제**한다.

`cli/src/mrq/mdsync.py` — `perform`:

```python
def perform(
    root: Path,
    iid: int,
    path: Path,
    *,
    prefer_values: Sequence[str] | None = None,
) -> Outcome:
```

독스트링은 그대로 두고, 본문의 `only_ids`/`plan_sync` 두 줄을 바꾼다:

```python
    # 모호하거나 모르는 접두사는 여기서 exit 1 로 끝낸다 — plan_sync 에
    # 닿기 전이므로 아직 아무것도 쓰지 않았다. 접두사 해석은 threads.py
    # 하나로 모은다(`cli.md` §1 MUST) — conflict.py 는 완전한 id 만 받는다.
    resolution = prefer.resolve(review, prefer.parse(prefer_values))
    applied, conflicts, extra = conflict.plan_sync(review, parsed, resolution=resolution)
```

import 에 `from collections.abc import Sequence` 와 `prefer` 를 더하고,
`threads` 가 더는 쓰이지 않으면 import 에서 뺀다 (ruff 가 알려준다).

`mdsync.report_conflicts` 의 안내 메시지:

```python
        print(
            "`mrq sync --prefer md|json` 으로 전체를, "
            "`mrq sync --prefer <스레드>=md|json` 으로 스레드마다 해소하세요. "
            "일부만 지정하면 나머지 충돌이 남아 아무것도 쓰지 않습니다.",
            file=sys.stderr,
        )
```

`cli/src/mrq/commands/sync.py`:

```python
        outcome = mdsync.perform(root, iid, path, prefer_values=args.prefer)
```

`cli/src/mrq/threads.py` 독스트링 4~8행:

```
`<thread>` 인자(`reply`/`state`/`open --thread`)와 `sync --prefer <ID>=...` 의
스코프는 discussion id의 **유일한 접두사**를 허용해야 한다(MUST). 접두사가 여러
스레드에 걸리면 exit 1과 함께 후보를 보여준다. 이 판정을 한 곳에 모아 두는
이유는, 모호한 접두사가 사용자가 지정하지 않은 스레드에 해소 방향을 적용해 그
스레드의 CLI 값을 조용히 지우는 사고를 막기 위해서다.
```

- [ ] **Step 4: Run the whole suite**

Run: `cd cli && ./.venv/bin/python -m pytest -q`
Expected: PASS. 기존 `--prefer md` 테스트는 문법이 그대로라 손댈 필요가 없다.
`--thread` 를 쓰는 테스트가 있으면 `--prefer ID=방향` 으로 고친다.

- [ ] **Step 5: Commit**

```bash
cd cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
cd .. && git add cli/
git commit -m "sync --prefer 가 [ID=]md|json 을 받는다, --thread 삭제"
```

---

## Task 5: 통합 확인 — 아홉 케이스

**Files:**
- Modify: `cli/tests/test_sync.py`

**Interfaces:**
- Consumes: 앞 네 과제 전부
- Produces: 없음 (테스트만)

- [ ] **Step 1: 설계 §1.5 의 표를 테스트로 옮긴다**

Task 3 이 2·3·4·6번을, Task 2 가 7·8번을, Task 1 이 문법 오류를 이미 덮었다.
1번은 기존 `test_sync_prefer_md_resolves_the_conflict`(206행)가 그대로 덮는다.
남은 것은 5번(CLI 표면에서의 "뒤가 이긴다")과 9번이다.

```python
def test_sync_repeated_scopeless_prefer_takes_the_last(conflicted):
    # 같은 스코프 안에서는 뒤가 이긴다. json 이 먼저 와도 md 가 적용된다.
    assert main(["sync", "--prefer", "json", "--prefer", "md"]) == 0
    assert next(t for t in _json(conflicted).threads if t.id == "a1b2c3d4e5f6").local.state == (
        "done"
    )


def test_sync_conflict_message_shows_the_new_grammar(conflicted, capsys):
    assert main(["sync"]) == 3
    err = capsys.readouterr().err
    assert "--prefer <스레드>=md|json" in err
    assert "--thread" not in err
```

**기존 `--thread` 테스트 셋을 새 문법으로 고친다** (278·289·295행):

```python
    assert main(["sync", "--prefer", "a1b2=md"]) == 1        # 모호한 접두사
    assert main(["sync", "--prefer", "zzzzzzzzzzzz=md"]) == 1  # 모르는 접두사
    assert main(["sync", "--prefer", "=md"]) == 1              # 빈 스코프
```

세 테스트의 단언("아무것도 쓰지 않았다")은 그대로 둔다 — 그게 이 테스트들의
요점이고, `prefer.resolve` 가 `plan_sync` 보다 앞서 실행되므로 성질이 보존된다.

- [ ] **Step 2: Run**

Run: `cd cli && ./.venv/bin/python -m pytest tests/test_sync.py -v`
Expected: PASS

- [ ] **Step 3: 전체 스위트와 린트**

```bash
cd cli && ./.venv/bin/python -m pytest -q && ./.venv/bin/ruff format --check . && ./.venv/bin/ruff check .
```

- [ ] **Step 4: Commit**

```bash
cd .. && git add cli/tests/
git commit -m "sync --prefer 스코프 문법의 아홉 케이스"
```

---

## Task 6: 문서

**Files:**
- Modify: `docs/spec/cli.md` (§1 synopsis, §5)
- Modify: `docs/spec/data-model.md` (§5.3)
- Modify: `docs/spec/testing.md` (`--prefer` 표기 한 줄)
- Modify: `docs/decisions/0002-per-thread-conflict-detection.md` (해소 수단 한 줄)
- Create: `docs/decisions/0013-scoped-conflict-resolution.md`
- Modify: `docs/plans/README.md` (계획 4 전 과제 행)

**Interfaces:** 없음

- [ ] **Step 1: `cli.md` §1 synopsis**

```
mrq sync     [--json] [--prefer [ID=]md|json]...
```

- [ ] **Step 2: `cli.md` §5 에 해소 규칙 절 추가**

`### 충돌 해소 — `--prefer`` 를 `sync --json` 절 **앞에** 넣는다:

````markdown
### 충돌 해소 — `--prefer [ID=]md|json`

반복 가능하다. 스코프 없이 주면 충돌한 전체에, `ID=` 를 붙이면 그 스레드에만
적용된다. `ID` 는 유일한 접두사를 받는다(§1).

> **좁은 스코프가 순서와 무관하게 이긴다. 같은 스코프 안에서는 뒤가 이긴다.**

```sh
mrq sync --prefer md                          # 전부 md
mrq sync --prefer md --prefer f6e5=json       # 전부 md, f6e5 만 json
mrq sync --prefer f6e5=json --prefer md       # ← 위와 같은 결과
mrq sync --prefer md --prefer json            # 같은 스코프 반복 → json
mrq sync --prefer a1b2=md --prefer a1b2=json  # 같은 스코프 반복 → json
```

**일부만 지정하면 나머지 충돌이 남아 아무것도 쓰지 않는다**(§5.3 MUST). 부분
해소는 없다 — 에디터의 충돌 UI 가 모든 충돌에 방향이 정해진 뒤에만 `sync` 를
불러야 하는 이유다(`editor.md` §3.4).

`--prefer` 는 **충돌로 판정된 스레드에만** 적용된다. `ID=` 로 지목한 스레드가
충돌이 아니면 경고하고 동작은 바꾸지 않는다(MUST) — 오타가 조용히 삼켜지지
않게 한다.

스코프 없는 값이 실제 스레드 id 의 접두사와 겹치면 **exit 1** 이다. discussion
id 는 16진수라 도달할 수 없지만, 그 가정이 깨졌을 때 조용한 오동작 대신 에러가
나도록 가드를 둔다.
````

- [ ] **Step 3: `data-model.md` §5.3 마지막 불릿**

```markdown
- `mrq sync --prefer [ID=]md|json` 으로 해소한다. 스코프 없이 주면 충돌한 전체,
  `ID=` 를 붙이면 그 스레드만. 좁은 스코프가 순서와 무관하게 이긴다
  (`cli.md` §5). **일부만 지정하면 나머지 충돌이 남아 여전히 아무것도 쓰지 않는다**
```

- [ ] **Step 4: `decisions/0013-scoped-conflict-resolution.md`**

```markdown
# 0013. 충돌 해소도 스레드 단위로 섞을 수 있어야 한다

2026-10-14 · 계획 4 전 과제

## 맥락

[0002](0002-per-thread-conflict-detection.md)가 충돌 **판정**을 스레드 단위로
정했지만, 해소 수단은 `--prefer md|json [--thread ID]...` 로 **호출당 방향 하나**
였다. 계획 4 의 Emacs 충돌 버퍼(`editor.md` §3.4)를 설계하다 그것이 §3.4 와
모순인 것이 드러났다.

스레드 A 는 md, B 는 json 으로 고르면 어떤 순서로도 빠져나갈 수 없다 —
`data-model.md` §5.3 이 "충돌이 하나라도 남으면 아무것도 쓰지 않고 exit 3" 을
MUST 로 두기 때문이다.

## 버린 대안 셋

- **`mrq state`/`reply` 로 json 쪽을 먼저 확정한다** — 그 명령들이 `review.md` 를
  재렌더하므로(`cli.md` §10 MUST) md 쪽으로 고르려던 스레드의 편집이 지워진다
- **에디터가 md 블록을 json 값으로 직접 고쳐 쓴다** — 렌더러를 elisp 에 복제하는
  일이고 `editor.md` §1-1 의 근거를 정면으로 깬다
- **`--pick ID=dir` 을 별도 플래그로 추가한다** — `--prefer`+`--thread` 를 완전히
  흡수하지만 `--prefer` 단독은 흡수하지 못해 플래그가 둘로 남는다

## 선택

`--prefer` 에 **선택적 스코프 접두사**를 붙여 플래그 하나로 합친다.
`--thread` 는 삭제한다 — `--prefer` 없이는 의미가 없던, 혼자 서지 못하는
플래그였다.

```
mrq sync [--json] [--prefer [ID=]md|json]...
```

해소 규칙은 **좁은 스코프가 순서와 무관하게 이긴다**. 위치 기반 fold 도 검토했고
버렸다 — "앞의 개별 지정을 뒤의 전역 항목이 지운다" 는 모서리를 만드는데,
`chmod`·`.gitignore`·CSS·`RUST_LOG` 가 전부 반대로 동작하므로 반대로 기대하는
사람이 생긴다.

`--prefer md` 를 `--prefer all=md` 로 바꿔 문법을 완전히 균일하게 만드는 안도
검토했다. 유일한 이득이 synopsis 의 깔끔함인데 `[ID=]` 표기가 같은 것을 주면서
공통 경우를 길게 만들지 않는다 — 충돌 자체가 드물고 혼합 방향은 더 드물다.

## 결과

- 에디터의 충돌 버퍼가 **모든 충돌에 방향이 정해진 뒤 한 번의 `sync`** 를 부른다.
  키를 누를 때마다 부르면 첫 키부터 실패한다
- 부분 해소는 여전히 불가능하다. 0002 와 §5.3 의 all-or-nothing 은 그대로다
- 스코프 없는 값이 스레드 접두사와 겹치면 exit 1 — 16진수 id 에서는 도달 불가지만
  가정을 불변식으로 고정한다
```

- [ ] **Step 5: `decisions/0002` 와 `testing.md` 의 표기**

`0002` 의 "충돌 해소 수단이 필요하다 → `mrq sync --prefer md|json [--thread ID]`"
줄을 고친다:

```markdown
- 충돌 해소 수단이 필요하다 → `mrq sync --prefer [ID=]md|json`
  ([0013](0013-scoped-conflict-resolution.md)에서 문법을 바꿨다)
```

`testing.md:179` 의 `sync --prefer md|json` 을 `sync --prefer [ID=]md|json` 으로.

- [ ] **Step 6: `plans/README.md` 에 행 추가**

계획 3 행과 계획 4 행 사이:

```markdown
| — | — | **계획 4 전 과제** — `sync --prefer` 스코프 문법 | **완료** (2026-10-14) |
```

그리고 "## 계획 3 — 완료" 섹션 뒤에 짧은 절을 넣는다:

```markdown
## 계획 4 전 과제 — 완료

계획 4 를 설계하다 스펙 둘이 모순인 것을 발견해 먼저 해소했다 (브랜치
`jbseo/pre_step4`). `editor.md` §3.4 는 충돌 버퍼에서 스레드마다 방향을 고르라고
하는데, `cli.md` §5 의 `sync` 는 호출당 방향 하나이고 `data-model.md` §5.3 은
충돌이 하나라도 남으면 전부 실패시킨다 — 혼합 해소가 **어떤 순서로도** 불가능했다.

`--prefer` 를 `[ID=]md|json` 스코프 문법으로 바꾸고 `--thread` 를 없앴다.
좁은 스코프가 순서와 무관하게 이긴다. `docs/decisions/0013`.
```

- [ ] **Step 7: Commit**

```bash
git add docs/
git commit -m "문서 — sync --prefer 스코프 문법과 결정 0013"
```

---

## 완료 조건

- [ ] `cd cli && ./.venv/bin/python -m pytest -q` 전부 통과 (483 + 신규)
- [ ] `./.venv/bin/ruff format --check . && ./.venv/bin/ruff check .` 통과
- [ ] `grep -rn '\-\-thread' docs/spec/cli.md docs/spec/data-model.md` 가
      `open --thread` 만 남긴다
- [ ] `mrq sync --help` 가 새 문법을 보여준다
