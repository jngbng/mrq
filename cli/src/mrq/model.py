"""`review.json` 데이터 클래스와 스키마 검증.

docs/spec/data-model.md. 좌표계를 position(서버) / anchor(head_sha) /
location(작업 트리) 세 블록으로 분리한다 (§4.1).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from mrq import SCHEMA_VERSION
from mrq.errors import CorruptStateError, SchemaVersionError, UsageError


@dataclass
class Note:
    id: int
    author: str
    created_at: str
    updated_at: str
    body: str
    mine: bool
    suggestions: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> Note:
        return cls(**data)


@dataclass
class Server:
    """GitLab discussion 객체에는 이 필드들이 없다. notes 에서 계산한다 (§4.2)."""

    resolvable: bool
    resolved: bool
    repliable: bool
    updated_at: str
    note_count: int


@dataclass
class Position:
    """GitLab 응답을 변형 없이 보관한다. push 가 그대로 되돌려 보낸다."""

    position_type: str
    old_path: str | None = None
    new_path: str | None = None
    old_line: int | None = None
    new_line: int | None = None
    line_range: dict | None = None


@dataclass
class Anchor:
    line: str
    context_before: list[str]
    context_after: list[str]
    hunk: str | None = None


@dataclass
class Location:
    """작업 트리 좌표. 에디터는 이것만 읽는다."""

    path: str | None
    line: int | None
    line_end: int | None
    confidence: str  # exact | fuzzy | stale
    method: str  # git-diff | anchor-search | context-anchor | none


@dataclass
class Local:
    state: str = "todo"  # todo | done | replied | skipped
    reply: str = ""
    touched_at: str | None = None
    touched_by: str | None = None  # md | cli | push
    pushed_hash: str | None = None
    push_error: dict | None = None


@dataclass
class Thread:
    id: str
    root_note_id: int
    server: Server
    position: Position | None
    anchor: Anchor | None
    location: Location | None
    notes: list[Note]
    local: Local

    @classmethod
    def from_dict(cls, data: dict) -> Thread:
        return cls(
            id=data["id"],
            root_note_id=data["root_note_id"],
            server=Server(**data["server"]),
            position=Position(**data["position"]) if data.get("position") else None,
            anchor=Anchor(**data["anchor"]) if data.get("anchor") else None,
            location=Location(**data["location"]) if data.get("location") else None,
            notes=[Note.from_dict(n) for n in data["notes"]],
            local=Local(**data["local"]),
        )


@dataclass
class Me:
    id: int
    username: str
    can_resolve: bool


@dataclass
class Capabilities:
    draft_notes: bool


@dataclass
class DiffRefs:
    base_sha: str
    start_sha: str
    head_sha: str


@dataclass
class Review:
    schema_version: int
    project: str
    iid: int
    title: str
    web_url: str
    mr_state: str
    source_branch: str
    diff_refs: DiffRefs
    me: Me
    capabilities: Capabilities
    pulled_at: str
    rendered_at: str | None
    threads: list[Thread]

    @classmethod
    def from_dict(cls, data: dict) -> Review:
        return cls(
            schema_version=data["schema_version"],
            project=data["project"],
            iid=data["iid"],
            title=data["title"],
            web_url=data["web_url"],
            mr_state=data["mr_state"],
            source_branch=data["source_branch"],
            diff_refs=DiffRefs(**data["diff_refs"]),
            me=Me(**data["me"]),
            capabilities=Capabilities(**data["capabilities"]),
            pulled_at=data["pulled_at"],
            rendered_at=data.get("rendered_at"),
            threads=[Thread.from_dict(t) for t in data["threads"]],
        )


def schema_path() -> Path:
    """리포 루트의 `schema/review.schema.json` 을 찾는다.

    이 파일이 세 구현의 정본이다 (docs/spec/repo-layout.md §4.2). 개발 설치
    (`pip install -e cli/`) 에서는 `__file__` 에서 위로 올라가 찾는다. 비편집
    wheel 패키징은 배포가 필요해지는 시점의 과제다 (범위 밖).
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "schema" / "review.schema.json"
        if candidate.is_file():
            return candidate
    raise UsageError("schema/review.schema.json 을 찾을 수 없습니다.")


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads(schema_path().read_text(encoding="utf-8"))


def validate(data: dict) -> None:
    jsonschema.validate(data, _schema())


def check_version(data: dict) -> None:
    version = data.get("schema_version")
    if version == SCHEMA_VERSION:
        return
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"review.json 의 schema_version 이 {version} 입니다 "
            f"(이 mrq 는 {SCHEMA_VERSION}). mrq 를 업그레이드하세요."
        )
    raise SchemaVersionError(
        f"review.json 의 schema_version {version} 을 다룰 수 없습니다. `mrq pull` 로 다시 받으세요."
    )


def dumps(review: Review) -> str:
    """검증한 뒤 직렬화한다. 모든 쓰기 경로가 이 함수를 지난다."""
    data: dict[str, Any] = asdict(review)
    validate(data)
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def loads(text: str) -> Review:
    """정본 json 을 읽는다. 손상 입력은 CorruptStateError(exit 1) 로 바꾼다.

    `dumps` 는 감싸지 않는다 — 쓰기 직전 검증 실패는 사용자 데이터가 아니라
    우리 버그이고, 트레이스백이 맞는 보고 형태다.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"review.json 을 JSON 으로 읽을 수 없습니다 ({exc}). `mrq pull` 로 다시 받으세요."
        ) from exc
    check_version(data)
    try:
        validate(data)
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "(최상위)"
        raise CorruptStateError(
            f"review.json 이 스키마에 맞지 않습니다 — {where}: {exc.message}. "
            "`mrq pull` 로 다시 받으세요."
        ) from exc
    return Review.from_dict(data)


_LOCAL_STATES = {"todo", "done", "replied", "skipped"}


def peek_source_branch(text: str) -> str | None:
    """검증 없이 `source_branch` 하나만 읽는다.

    MR 탐지가 스키마 유효성에 묶일 이유가 없다. 손상된 json 때문에 `pull` 이
    시작도 못 하면 사용자의 탈출구가 `rm -rf .mrq/` 뿐이다.
    """
    return _peek_str(text, "source_branch")


def peek_rendered_at(text: str) -> str | None:
    """검증 없이 `rendered_at` 하나만 읽는다.

    `pull` 이 `--no-render` 로 돌 때 이어받을 값이다 — md 가 디스크에 그대로
    있는데 값만 잃으면 `status` 가 `synced -` 를 찍는다.
    """
    return _peek_str(text, "rendered_at")


def _peek_str(text: str, key: str) -> str | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def read_previous(text: str) -> tuple[dict[str, tuple[Local, Anchor | None]], list[str]]:
    """`pull` 이 보존해야 할 `local.*` 와 `anchor` 를 최선 노력으로 건져낸다.

    data-model.md §2 — 상위 버전은 거부하고(exit 7, 새 파일로 덮지 않는다),
    하위 버전·스키마 위반·JSON 손상은 경고와 함께 건질 수 있는 것만 건진다.
    `pull` 이 파일을 교체하기 전에 터지면 전송하지 않은 답글이 복구 불가가 된다.
    """
    warnings: list[str] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, [f"기존 review.json 을 읽을 수 없습니다 ({exc}). 로컬 상태 없이 새로 받습니다."]
    if not isinstance(data, dict):
        return {}, ["기존 review.json 이 객체가 아닙니다. 로컬 상태 없이 새로 받습니다."]

    version = data.get("schema_version")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"review.json 의 schema_version 이 {version} 입니다 "
            f"(이 mrq 는 {SCHEMA_VERSION}). mrq 를 업그레이드하세요."
        )
    if version != SCHEMA_VERSION:
        warnings.append(
            f"기존 review.json 의 schema_version 이 {version} 입니다. "
            "답글과 상태만 건져내 새 형식으로 다시 씁니다."
        )
    else:
        try:
            validate(data)
        except jsonschema.ValidationError as exc:
            warnings.append(
                f"기존 review.json 이 스키마에 맞지 않습니다 ({exc.message}). "
                "답글과 상태만 건져냅니다."
            )
        else:
            review = Review.from_dict(data)
            return {t.id: (t.local, t.anchor) for t in review.threads}, warnings

    return _salvage(data, warnings), warnings


def _salvage(data: dict, warnings: list[str]) -> dict[str, tuple[Local, Anchor | None]]:
    """검증을 통과하지 못한 dict 에서 스레드별 local/anchor 를 필드 단위로 건진다.

    `read_previous` 는 이 결과를 그대로 `pull` 이 새로 받은 리뷰에 섞어 넣고
    `model.dumps` 로 다시 쓴다. `dumps` 의 검증 실패는 의도적으로 감싸지 않으므로
    여기서 만드는 `Local` 은 반드시 스키마를 통과해야 한다 — 아니면 트레이스백으로
    터지는, 이 과제가 없애려는 바로 그 실패 양상이 재발한다.
    """
    out: dict[str, tuple[Local, Anchor | None]] = {}
    threads = data.get("threads")
    if not isinstance(threads, list):
        warnings.append("기존 review.json 에 threads 배열이 없습니다.")
        return out
    local_schema = _schema()["$defs"]["thread"]["properties"]["local"]
    push_error_schema = local_schema["properties"]["push_error"]
    for raw in threads:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            continue
        thread_id = raw["id"]
        local_raw = raw.get("local") if isinstance(raw.get("local"), dict) else {}

        state = local_raw.get("state")
        state = state if state in _LOCAL_STATES else "todo"
        reply = local_raw.get("reply")
        reply = reply if isinstance(reply, str) else ""
        touched_at = local_raw.get("touched_at")
        touched_at = touched_at if isinstance(touched_at, str) else None
        touched_by = local_raw.get("touched_by")
        touched_by = touched_by if touched_by in {"md", "cli", "push"} else None
        pushed_hash = local_raw.get("pushed_hash")
        pushed_hash = pushed_hash if isinstance(pushed_hash, str) else None
        push_error = local_raw.get("push_error")
        push_error = push_error if isinstance(push_error, dict) else None
        if push_error is not None:
            try:
                jsonschema.validate(push_error, push_error_schema)
            except jsonschema.ValidationError:
                warnings.append(f"스레드 {thread_id} 의 push_error 가 스키마에 맞지 않아 버립니다.")
                push_error = None

        local = Local(
            state=state,
            reply=reply,
            touched_at=touched_at,
            touched_by=touched_by,
            pushed_hash=pushed_hash,
            push_error=push_error,
        )
        try:
            jsonschema.validate(asdict(local), local_schema)
        except jsonschema.ValidationError:
            # 필드별 가드를 뚫는 조합이 남아 있을 수 있다 — 개별 필드를 더
            # 솎아내는 대신 안전하게 답글과 상태만 남긴다.
            warnings.append(
                f"스레드 {thread_id} 의 local 이 스키마에 맞지 않아 답글과 상태만 남깁니다."
            )
            local = Local(state=state, reply=reply)

        anchor_raw = raw.get("anchor")
        anchor = None
        if isinstance(anchor_raw, dict) and isinstance(anchor_raw.get("line"), str):
            before = anchor_raw.get("context_before")
            after = anchor_raw.get("context_after")
            hunk = anchor_raw.get("hunk")
            hunk = hunk if isinstance(hunk, str) else None
            anchor = Anchor(
                line=anchor_raw["line"],
                context_before=[s for s in before if isinstance(s, str)]
                if isinstance(before, list)
                else [],
                context_after=[s for s in after if isinstance(s, str)]
                if isinstance(after, list)
                else [],
                hunk=hunk,
            )
        out[thread_id] = (local, anchor)
    return out
