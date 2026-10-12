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
from mrq.errors import SchemaVersionError, UsageError


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
    data = json.loads(text)
    check_version(data)
    validate(data)
    return Review.from_dict(data)
