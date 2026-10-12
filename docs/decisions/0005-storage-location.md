# 0005. 리뷰 상태를 `.mrq/`에 저장한다

날짜: 2026-10-11 · 상태: 채택 (초안의 `.git/mr-review/` 결정을 대체)

## 배경

초안은 `.git/mr-review/`에 저장했다. 근거는 `.gitignore`를 건드리지 않고, 커밋에 섞이지
않고, `git clean -fdx`에 날아가지 않는다는 것이었다.

[0001](0001-human-and-ai-are-peers.md)에서 AI를 1급 경로로 정한 뒤 이 전제가 약해졌다.

## 결정

리포지토리 루트(`git rev-parse --show-toplevel`)의 `.mrq/`에 저장한다.

```
.mrq/current -> <iid>/
.mrq/<iid>/{review.json, review.md, lock}
```

`mrq`가 `.mrq/`를 git에서 가린다. 리포 루트의 `.gitignore`는 건드리지 않는다. 가리는
수단은 [0007](0007-mrq-gitignore.md)에서 `.mrq/.gitignore`로 바뀌었다.

## 근거

- **AI와 도구가 `.git/`을 못 보거나 안 본다.** 많은 에이전트 하네스와 샌드박스가
  `.git/`을 거부 목록에 넣는다. 주 작업자 중 하나에게 건네는 1차 파일이 `.git/` 안에
  있는 것은 구조적 마찰이다
- **worktree 의미론이 맞다.** 저장 경로의 기준이 `git rev-parse --show-toplevel`이므로
  worktree마다 독립된 리뷰 상태를 갖는다. worktree 둘이 각자 다른 브랜치·다른 MR인
  것이 정상이며, 반대로 worktree 전체가 `current` 포인터 하나를 공유하면 서로의
  상태를 덮어쓴다
- `.mrq/review.md`가 사람에게도 타이핑·기억·탭 완성 면에서 낫다

## 수용한 위험

**`git clean -fd`가 `.mrq/`를 지운다.** ignored 상태면 `-x`가, 아직 가려지기 전이면
untracked라서 `-fd`가 지운다. 잃는 것은 전송하지 않은 답글과 `pushed_hash` 기록이며,
후자가 사라지면 재push 시 **이미 올린 답글이 중복 전송된다.**

사용자가 `git clean -fdx`를 습관적으로 쓰지 않고 쓸 때는 의식적으로 쓴다고 판단해
이 위험을 수용했다. 단순한 구조가 주는 이득은 매일 돌아오고 위험은 드물게 사용자가
통제하는 순간에만 있다.

검토했으나 택하지 않은 하이브리드: 정본 json은 `.git/mr-review/`에, 편집면 md는
`.mrq/`에 두는 안. `review.md`가 진짜로 파생 상태라서 성립하지만 위치가 둘로 늘어난다.

## 결과

- 초안의 "리뷰 메타데이터를 작업 트리에 만들지 말 것" 규칙을 폐기한다
- `.mrq/`가 날아갔을 때 `mrq pull --render`로 md를 복원할 수 있어야 한다
- Windows의 심링크 처리는 future work
