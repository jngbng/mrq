# 0007. `.mrq/.gitignore`로 가린다 (`.git/info/exclude` 대체)

날짜: 2026-10-12 · 상태: 채택 ([0005](0005-storage-location.md)의 exclude 등록을 대체)

## 배경

[0005](0005-storage-location.md)는 리뷰 상태를 작업 트리의 `.mrq/`에 두기로 하고,
git에서 가리는 수단으로 `.git/info/exclude`에 `/.mrq/` 한 줄을 등록했다.

그 선택은 두 가지를 끌고 왔다. 매 명령 시작에 `.git/` 아래에 **쓰기**를 해야 하고,
exclude 파일의 위치가 `--git-dir`이 아니라 `--git-common-dir`이라는 함정을
구현·스펙·테스트·CLAUDE.md에 각각 박아 둬야 했다. 전자는 0005 자신의 근거와
어긋난다 — `.git/`을 거부하는 샌드박스와 에이전트 하네스를 피하려고 상태를 작업
트리로 옮겼는데, 도구는 여전히 `.git/`에 쓴다.

## 결정

`.mrq/`를 만들 때 그 안에 `.gitignore`를 같이 쓴다. 내용은 주석 한 줄과 `*`.

```
.mrq/.gitignore    # mrq 가 관리하는 리뷰 상태. 커밋하지 않는다.
                   *
```

`*`가 `.gitignore` 자신까지 매치하므로 `.mrq/` 전체가 git에서 사라진다. 리포 루트의
`.gitignore`는 여전히 건드리지 않는다. `.git/info/exclude`에는 쓰지 않는다.

## 근거

git 가시성은 두 방식이 동등하다. 실제 저장소에서 확인한 것:

| | `.mrq/.gitignore` | `.git/info/exclude` |
|---|---|---|
| `git status --porcelain -uall` | 빈 출력 | 빈 출력 |
| `git add -A` | 스테이징 안 됨 | 스테이징 안 됨 |
| 루트 `.gitignore`의 `!*.json`으로 역부활 | 안 됨 (깊은 쪽이 이긴다) | 안 됨 |
| `rg --files` | `.mrq/` 안 보임 | `.mrq/` 안 보임 |
| `git clean -fd` / `-fdx` | 생존 / 삭제 | 생존 / 삭제 |

동등하므로 운영 비용이 결정한다.

- **`.git/` 쓰기 권한이 필요 없다.** 0005가 상태를 작업 트리로 옮긴 이유와 일관된다
- **`--git-common-dir` 함정이 소멸한다.** `.mrq/`가 worktree마다 독립이므로
  `.gitignore`도 그 worktree 안에 생긴다. clone 단위 설정과 worktree 단위 상태가
  어긋날 자리가 없다
- **ignore 규칙이 상태와 같은 디렉터리에 산다.** `.mrq/`를 지웠다 복원해도 일관되고,
  디렉터리를 복사해도 따라간다

대가는 사람이 보지 않는 파일 하나가 `.mrq/` 안에 늘어나는 것이다.

## 수용한 위험

0005의 `git clean -fdx` 위험은 그대로다. 두 방식 모두 `.mrq/`를 ignored로 만들므로
`-x` 없는 `git clean -fd`는 살려두고 `-fdx`는 지운다.

**기각: 둘 다 쓰기.** exclude 등록을 남겨 두면 `--git-common-dir` 함정과 worktree
분기를 그대로 안고 가야 해서 얻는 것이 없다.

## 결과

- `store.ensure_git_exclude` → `store.ensure_mrq_gitignore`. 호출 지점은 그대로
  `open_review`이며 "모든 명령의 시작에서 보장"이라는 계약은 바뀌지 않는다
- `gitcmd.git_common_dir`을 삭제한다. 유일한 호출자가 사라졌다
- 마이그레이션은 하지 않는다. 기존 사용자의 exclude에 남은 `/.mrq/` 한 줄은 무해하다
- 계약은 파일 내용이 아니라 git의 실제 동작이다. `git status --porcelain -uall`이
  비어 있고 `git add -A` 후 `git ls-files`에 `.mrq`가 없음을 테스트가 단정한다
