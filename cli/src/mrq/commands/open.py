"""`mrq open`. docs/spec/cli.md §12.

GitLab UI 에서 확인해야 하는 경우(이미지 코멘트, 개별 노트, 리뷰어와의 긴 논의)
가 있으므로 왕복 비용을 줄이는 용도다. **네트워크를 쓰지 않는다** — `web_url` 과
`root_note_id` 는 둘 다 `review.json` 에 있다.
"""

from __future__ import annotations

import webbrowser

from mrq import model, store
from mrq import threads as thread_select
from mrq.errors import UsageError


def run(args) -> int:
    root = store.repo_root()
    # `.mrq/.gitignore` 보장은 `doctor` 를 제외한 모든 명령의 시작 규칙이다
    # (data-model.md §1 MUST). `--mr` 분기는 `store.open_review` 를 타지 않으므로
    # 여기서 직접 보장한다 — 안 그러면 `--mr` 로 연 적밖에 없는 저장소의
    # `.mrq/` 가 git 에 그대로 잡힌다.
    store.ensure_mrq_gitignore(root)
    if args.mr is not None:
        path = store.review_json_path(root, args.mr)
        if not path.is_file():
            raise UsageError(f"!{args.mr} 의 리뷰 상태가 없습니다. `mrq pull --mr {args.mr}`.")
    else:
        path = store.open_review(on_branch_change="warn").path

    review = model.loads(path.read_text(encoding="utf-8"))
    url = review.web_url
    if args.thread is not None:
        thread = thread_select.resolve_ref(review, args.thread)
        url = f"{url}#note_{thread.root_note_id}"

    if not webbrowser.open(url):
        raise UsageError(f"브라우저를 열 수 없습니다. 직접 여세요 — {url}")
    print(url)
    return 0
