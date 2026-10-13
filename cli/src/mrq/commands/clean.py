"""`mrq clean`. docs/spec/cli.md §11."""

from __future__ import annotations

import shutil
import sys

from mrq import glab, model, prompt, store
from mrq.errors import MrqError
from mrq.mr import PROJECT


def run(args) -> int:
    root = store.repo_root()
    # 모든 명령의 시작에서 보장한다 (data-model.md §1 MUST). `doctor` 만
    # 예외다 — 진단이 상태를 만들면 "없음" 을 진단할 수 없다.
    store.ensure_mrq_gitignore(root)
    wanted = _wanted(args)
    current = store.read_current(root)
    targets = []

    for iid in sorted(_candidates(root)):
        try:
            data = glab.api(f"{PROJECT}/merge_requests/{iid}")
        except MrqError as exc:
            print(f"⚠ !{iid} 의 상태를 확인할 수 없습니다 ({exc}) — 건너뜁니다.", file=sys.stderr)
            continue
        state = (data or {}).get("state")
        if state not in wanted:
            continue
        targets.append((iid, state, _unsent(root, iid)))

    if not targets:
        # `clean`은 `current` 한 건이 아니라 `.mrq/` 전체의 저장된 MR 집합을
        # 대상으로 한다. 제거할 것이 없는 것은 참인 성공이다(cli.md §2).
        print("제거할 것이 없습니다.")
        return 0

    for iid, state, unsent in targets:
        suffix = f" — 미전송 작업 {unsent}건" if unsent else ""
        print(f"!{iid} ({state}){suffix}")
    if args.dry_run:
        return 0

    pending = sum(unsent for _, _, unsent in targets)
    if pending:
        prompt.confirm(
            f"미전송 작업이 {pending}건 남아 있습니다. 제거하면 답글을 복구할 수 없습니다.",
            force=args.force,
        )

    removed = 0
    for iid, _, unsent in targets:
        # json 을 바꾸는(지우는 것도 포함) 명령은 lock 을 배타적으로 잡아야
        # 한다(data-model.md §1 MUST). 스캔과 확인 사이에 `push`가 끝나거나
        # 에디터 `sync`가 새 답글을 써넣을 수 있으므로, lock 을 잡은 뒤
        # `_unsent`를 다시 확인한다 — 늘어났으면 스캔 때 보지 못한 작업이
        # 생긴 것이므로 지우지 않는다. flock 을 쥔 파일을 그 안에서
        # unlink 해도 POSIX 에서는 안전하다 — 커널이 fd 를 닫을 때 놓는다.
        with store.review_lock(root, iid):
            recheck = _unsent(root, iid)
            if recheck > unsent:
                print(
                    f"⚠ !{iid} 에 스캔 이후 새로운 미전송 작업이 생겨 건너뜁니다 "
                    f"({unsent}→{recheck}건). 다시 실행해 확인하세요.",
                    file=sys.stderr,
                )
                continue
            try:
                shutil.rmtree(store.review_dir(root, iid))
            except OSError as exc:
                print(f"⚠ !{iid} 를 제거하지 못했습니다 ({exc}) — 건너뜁니다.", file=sys.stderr)
                continue
        if iid == current:
            # 끊어진 심링크를 남기지 않는다(MUST).
            store.clear_current(root)
        removed += 1
    print(f"removed: {removed}개")
    return 0


def _candidates(root) -> list[int]:
    """`.mrq/` 에 저장된 iid 목록. `current` 별명과 비정상 항목은 걸러낸다."""
    candidates = []
    for directory in store.mrq_dir(root).glob("*/review.json"):
        entry = directory.parent
        if entry.is_symlink():
            # `.mrq/current` 는 `<iid>/` 를 가리키는 심링크라 glob 이 같은
            # 파일을 두 번째 이름으로도 내놓는다. 그 별명이다 — 조용히
            # 건너뛴다.
            continue
        name = entry.name
        if not name.isdigit():
            print(f"⚠ .mrq/{name}/ 은 iid 디렉터리가 아닙니다 — 건너뜁니다.", file=sys.stderr)
            continue
        iid = int(name)
        if str(iid) != name:
            # `01234` 처럼 표준 형식이 아닌 이름은 `store.review_dir(root,
            # iid)`가 다시 가리키는 디렉터리와 달라진다 — `int()` 로 왕복하면
            # 엉뚱한 디렉터리를 잠그고 지우게 된다. 건드리지 않는다.
            print(
                f"⚠ .mrq/{name}/ 의 이름이 iid 표준 형식이 아닙니다 — 건너뜁니다.",
                file=sys.stderr,
            )
            continue
        candidates.append(iid)
    return candidates


def _wanted(args) -> set[str]:
    """플래그가 없으면 merged 와 closed 둘 다 (§11)."""
    if not args.merged and not args.closed:
        return {"merged", "closed"}
    return {name for name, on in (("merged", args.merged), ("closed", args.closed)) if on}


def _unsent(root, iid: int) -> int:
    """전송하지 않은 작업이 있는 스레드 수.

    손상되거나 읽을 수 없는 review.json 은 "미전송 있음"(1)으로 센다 — 복구
    불가능한 답글이 그 안에 있을 수 있다(data-model.md §1). `model.loads`가
    던지는 `MrqError` 뿐 아니라 `read_text` 가 던질 수 있는 `OSError`·
    `UnicodeDecodeError` 도 잡는다 — 안 잡으면 `__main__.main`의
    `except MrqError`를 벗어난 트레이스백이 이 되돌릴 수 없는 명령에서
    사용자에게 그대로 보인다.
    """
    path = store.review_json_path(root, iid)
    try:
        review = model.loads(path.read_text(encoding="utf-8"))
    except (MrqError, OSError, UnicodeDecodeError) as exc:
        print(
            f"⚠ !{iid} 의 review.json 을 읽을 수 없습니다 ({exc}) — 미전송 작업이 있다고 "
            "가정합니다.",
            file=sys.stderr,
        )
        return 1
    return sum(
        1 for thread in review.threads if thread.local.reply.strip() or thread.local.state != "todo"
    )
