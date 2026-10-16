# 실측 체크리스트 — `plugin_emacs`

배치 ERT 가 못 잡는 것만 모았다: **실제 설정과의 상호작용**, 키 바인딩 충돌,
그리고 사람이 메시지를 실제로 **알아채는지**.

87개 ERT 와 적합성 테이블 17건은 이미 통과한다. 여기 있는 것은 그것들이 구조적으로
답할 수 없는 질문들이다.

대상: `gitlab.com/jngbng/mr-helper` MR `!1` (코멘트 15개).

---

## 준비

### `mrq` 를 PATH 에 올린다

CLI 는 `cli/.venv` 안에만 있다. 그 console script 는 **절대 경로 shebang** 이라
venv 를 활성화하지 않아도 어디서든 돌고, **editable 설치**라 코드를 고치면 바로
반영된다. `~/.local/bin` 은 이미 PATH 에 있으므로 심링크 하나면 된다:

```sh
ln -sf ~/workspace/mrq/cli/.venv/bin/mrq ~/.local/bin/mrq
which mrq && mrq --version
```

되돌리려면 `rm ~/.local/bin/mrq`. (venv 가 없으면 먼저
`cd cli && uv sync && uv pip install -e .`)

**Emacs 도 찾는지 확인한다** — `M-: (executable-find "mrq")`. GUI 런처로 띄운
Emacs 는 로그인 셸의 PATH 를 못 받는 경우가 있다. `nil` 이 나오면 둘 중 하나:

```elisp
;; 절대 경로를 박는다 (repo-layout.md §5 의 defcustom 이 이것을 위해 있다)
(setq mrq-executable "~/workspace/mrq/cli/.venv/bin/mrq")
;; 또는 exec-path 에 더한다
(add-to-list 'exec-path (expand-file-name "~/.local/bin"))
```

### 고친 것을 Emacs 재시작 없이 반영하는 법

```
M-x mrq-reload
```

**한 파일만 읽으면 안 된다.** 다른 파일에 새로 생긴 변수가 void 로 남아
백엔드가 죽는다 — 실제로 `mrq-flymake.el` 만 읽어 `mrq-message-width` 가
void 가 됐고, 진단이 전부 사라졌다. 이제 그런 경우 `*mrq*` 와 에코 영역에
이유가 뜬다.

키맵은 빈 채로 `defvar` 하고 `define-key` 를 최상위에서 부르므로 재로드가 그냥
반영된다. `eval-buffer` 도 된다.

**`defun`/`defvar` 를 하나만 고쳤다면 `C-M-x`(`eval-defun`)** 가 가장 빠르다 —
`eval-defun` 은 `defvar` 도 강제로 다시 평가한다(`eval-buffer` 는 안 한다).

반영이 안 되는 것 같으면 그 심볼을 직접 확인한다:

```
M-: (lookup-key mrq-command-map (kbd "n"))    ; → flymake-goto-next-error
C-h k C-c m n
```

플러그인 구조 자체(모듈 추가, `define-minor-mode` 변경)를 바꿨다면 재시작이
깔끔하다. `unload-feature` 는 마이너 모드와 훅이 얽혀 있어 권하지 않는다.

### 플러그인을 물린다

```elisp
;; ~/.emacs.d/modules_jbseo/init-mrq.el
(use-package mrq
  :load-path "~/workspace/mrq/plugin_emacs"
  :commands (mrq-setup mrq-mode)
  :hook (prog-mode . mrq-setup))
```

`mrq-setup` 은 `.mrq/current` 를 못 찾으면 조용히 빠지므로 `prog-mode-hook` 에
걸어도 안전하다. `markdown-mode` 는 당신 설정의 것을 쓴다 (`.elpa` 격리는 테스트
전용이다).

```sh
cd ~/workspace/mr-helper && mrq pull
```

---

## 기본 왕복

- [x] 소스 파일을 열면 코멘트가 `:note` 진단으로 뜬다
- [x] `C-c m n` / `C-c m p` 가 코멘트 사이를 돈다
      (`flymake-goto-next-error`/`-prev-error`. flymake 는 이 둘에 기본 바인딩을
      주지 않고 `M-g n`(`next-error`)으로도 안 된다 — 소스 버퍼에서
      `next-error-function` 을 설정하지 않는다. 당신 Exordium 설정은 `M-g` 를
      `goto-line` 에 묶어 접두사 자체를 없앴다: `init-look-and-feel.el:281`)
- [x] `C-c m r` → `review.md` 의 해당 `### reply` 로 간다
- [x] 답글을 쓰고 저장 → `sync` 가 돌고 **커서와 화면이 그 자리에 남는다**
  - (고침 1) 재렌더가 그 블록을 생략하면 버퍼 맨 처음으로 튕겼다
  - (고침 2) **화면이 맨 위로 튀었다** — `window-start` 186행 → 1행. point 는
    맞는데 화면만 튀어서 긴 파일에서는 자리를 잃는 것과 같았다. 원인은 복원이
    `point-min` 을 거쳐 가는 것이었고(`revert-buffer` 자체가 아니다 — 그래서
    `revert-buffer-quick` 은 증상이 없었다), 이제 화면 위치도 함께 복원한다
  - (고침 3) **화면 흔들림** — `markdown-mode` 가 전부 다시 칠하는 것. 원인이
    둘이었다. (a) 머리글의 `rendered=<시각>` 이 매 렌더마다 1 행을 바꿔 파일이
    **언제나** 달라졌다 — 읽는 코드가 하나도 없었는데도. 뺐고, 이제 렌더는
    바이트까지 안정이라 **아무것도 안 바뀌면 CLI 가 md 를 아예 쓰지 않는다.**
    (b) 바뀐 경우에도 `revert-buffer` 가 버퍼를 통째로 갈아 끼웠다 —
    `revert-buffer-with-fine-grain`(최소 편집)으로 바꿨다.
    "`rendered=` 를 꼭 업데이트해야 하나" 는 **아니오** 가 답이었다
  - (고침 4) 그러고 나니 **매 저장마다 화면이 한 줄씩 아래로 밀렸다.**
    화면 위치 복원이 `count-lines` 를 썼는데, 그것은 끝 위치가 줄 시작이
    **아니면** 1 을 더한다 — 커서가 줄 중간일 때만 나서 열 0 으로 짜 둔 기존
    테스트가 놓쳤다. 줄 번호 차로 바꿨다
- [x] 저장 후 열린 소스 버퍼의 진단이 **자동으로** 갱신된다 (file-notify)
- [x] `C-c m t` 로 체크박스를 돌리고 저장 → 상태가 반영된다
      (키가 `C-c C-t` 에서 바뀌었다. "상태가 reply 에서 너무 멀다" 는 의견은
      `review.md` 문법 변경이라 아직 논의 중 — 아래 "열린 질문")
- [x] review.md 에서 `C-c m r` → 소스의 **첫 비공백**에 커서가 선다
      (진단 밑줄이 시작하는 자리와 같다. `review.json` 에는 열 정보가 없다)
- [ ] 진단 메시지가 **프레임 너비까지** 보이고, 여러 줄 본문도 접혀서 이어진다.
      노트가 여럿이면 `(답글 N)` 이 붙는다. 더 좁게/넓게는 `mrq-message-width`
- [x] **왕복이 한 창 안에서 닫힌다** — 소스에서 `C-c m r` → 같은 창에 review.md,
      거기서 `C-c m r` → 같은 창에 소스 (`RET` 은 이제 markdown 의 줄바꿈이다)
  - (고침) 들여쓰기 **앞**(0열)에서 `C-c m r` 이 "여기에 MR 코멘트가 없습니다"
    를 냈다. 진단 영역이 첫 비공백에서 시작하는데(`flymake-diag-region`) 소스는
    들여쓰기가 있는 것이 보통이다. 반대 방향은 줄 맨 앞으로 보내므로 쌍이 안
    맞았다 — 이제 point 에 없으면 **그 줄 전체**에서 찾는다
- [x] `C-c m f`(pull) 가 동작하고 버퍼가 갱신된다 (reanchor 는 소스 버퍼로 옮겼다)
  - (고침) **전송이 끝나고 서버도 resolve 된 스레드가 기본 보기에서 사라진다.**
    `render.visible` 이 `local.state != todo` 까지 보고 있어서, push 가 끝나
    보낼 게 하나도 없는데도 계속 보였다. 판정을 `local.reply` 하나로 좁혔다 —
    `push` 가 성공해야 그것을 비우기 때문이다. `--all` 로 되살린다.
    지우지 않고 **감추는** 쪽을 골랐다: 되살릴 수 있고 `clean` 의 보수성을
    건드리지 않는다 (`review-md.md` §5, `cli.md` §7, `editor.md` §3.1)
- [x] `C-c m p` 가 status 요약을 보여주고 확인을 받는다

## 진단에 무엇이 뜨는가

- [ ] `[~]`(답글만)가 소스 버퍼에 **뜬다** — `push` 가 resolve 하지 않으므로
      서버에서 계속 열려 있는 대화다
- [ ] `[x]` 를 표시만 하고 push 안 한 것도 뜬다 (아직 보낼 것이 남았다)
- [ ] `[-]`(건너뜀)은 **안 뜬다** — 내가 닫은 것이다. 단 이유를 적어 뒀으면
      (미전송 답글) 뜬다
- [ ] push + pull 뒤 resolve 된 것은 안 뜬다
- [ ] `mrq-show-handled` 를 켜면 전부 뜬다
  - (고침) 예전 규칙은 `state == todo` 만 봐서 `[~]`·`[x]` 미전송이 사라졌다.
    "남은 것" 은 `todo` 가 아니라 **닫히지 않은 것**이다 (`editor.md` §3.1)

## 소스 편집 → 저장 → 진단

예전에는 **저장하는 순간** 보정이 꺼져 진단이 낡은 줄로 돌아갔다. 가장 흔한
고장이라 따로 둔다.

- [x] 코멘트가 달린 소스 파일 위쪽에 몇 줄을 **추가**한다 (저장 전) →
      진단이 따라 내려온다
- [x] **저장한다** → 진단이 **그 자리에 남는다** (예전에는 원래 줄로 되돌아갔다)
- [x] 함수를 파일 안에서 멀리(200줄 밖) 옮기거나 파일을 rename 한다 →
      진단이 틀어진다. `C-c m R`(reanchor) 로 다시 잡힌다
- [x] `C-c m R` 을 **소스 버퍼에서** 부를 수 있다 (review.md 로 갈 필요가 없다)

## 열린 질문 — `review.md` 에서 상태가 reply 에서 멀다

실측에서 나온 의견: 체크박스가 블록 **머리**(`## [ ] path:line`)에 있고 답글은
노트·diff 를 지나 한참 아래 `### reply` 라, 답글을 쓰는 동안 상태가 안 보인다.

`C-c m t` 는 reply 영역에서 눌러도 동작한다(블록 머리를 거슬러 찾는다) —
문제는 **보이지 않는 것**이다. 고치려면 `review-md.md` 의 문법을 바꿔야 하고
렌더러·파서·`v:` 해시가 함께 움직인다. 따로 논의한다.

### 추가 안건 — 앵커 주석의 자리 (미결)

지금은 앵커가 헤더 **위**라, md 로 보면 메타데이터 주석이 **위쪽 아이템의 body**
로 잡혀 섹션 폴딩이 이상해진다. 헤더 **다음**이 `markdown-mode` 와 더 맞는다.

막는 것: `review-md.md` §2 가 앵커를 위에 둔 이유는 블록 경계와 reply 의 끝이
**같은 토큰 하나**로 정의되기 때문이다. 아래로 내리면 "끝에서 헤더처럼 보이는
줄을 떼어내는" 보정이 필요하고, 그 보정은 답글이 `## ` 로 끝날 때 깨진다.

검토하고 **버린 안**: 헤더 줄 끝에 붙이기(`## [ ] a.py:1 — @x <!-- mrq:... -->`).
경계 문제는 풀리지만 `markdown-mode` 가 주석도 하이라이팅해 보기 나쁘다.

남은 길: 아래로 내리고 파서가 블록 끝을 "다음 **앵커**" 가 아닌 다른 토큰으로
잡게 하거나, 폴딩 쪽을 `mrq-mode` 에서 손보거나. 1번(가시성)을 끝냈으니 다음에
다룬다.

## 당신 설정과의 상호작용 — ERT 가 못 보는 부분

- [x] **다른 flymake 백엔드와 공존한다.** 파이썬/elisp 버퍼에서 기존 린터 진단과
      섞여 뜨고, 어느 쪽도 사라지지 않는다. (`M-x flymake-show-buffer-diagnostics`
      로 둘 다 보이는지 확인)
- [x] **키 바인딩이 충돌하지 않는다.** `C-h k C-c m r` / `C-c m n` 이 각각
      `mrq-reply-at-point` / `flymake-goto-next-error` 를 가리킨다. Exordium 의
      기존 `C-c m` 바인딩과 겹치지 않는다
- [x] `M-n`/`M-p` 처럼 더 짧은 키를 쓰고 싶으면:
      `(define-key mrq-minor-mode-map (kbd "M-n") #'flymake-goto-next-error)`
- [x] **`review.md` 에서 markdown-mode 가 온전하다** — `C-c C-s C`(GFM 코드블록),
      `C-c C-s t`(표), `C-c C-s b`(굵게), `C-c C-t h`(제목), `RET`(줄바꿈).
      mrq 는 `C-c m` 아래로 전부 옮겼고 `C-c C-*` 를 하나도 안 쓴다
- [x] 답글을 쓰다가 저장하지 않은 채 `C-c m s` → **작성 중인 답글이 남는가**
      (저장되고 sync 가 돈다). `C-c m f`/`C-c m p` 는 거부해야 한다
- [ ] 큰 파일(수천 줄)에서 편집 중 체감 지연이 없다 — 보정은 버퍼를 통째로
      문자열 벡터로 만든다. (미확인: `mr-helper` 의 파일이 작다. 다른 리포에서
      `mrq pull` 을 한 번 돌려 보는 쪽이 빠르다)

## 관찰 항목 — 잠정 결정의 재평가

`editor.md` §3.4 는 **위치 없는 경고**를 에코 영역과 `*mrq*` 로만 보내기로 했고
그 선택을 "잠정" 으로 표시했다 (`mrq-design.md` §6). 지금 그 경고가 알리는 것은
**"답글을 썼는데 전송되지 않는다"** 이고, 놓치면 답글이 그대로 남는다.

- [x] 답글을 쓰고 체크박스를 `[ ]` 로 **둔 채** 저장한다
- [x] 그 경고를 **알아챘는가?** → **알아차리기 힘들다** (잠정 결정이 틀렸음이 확인됨)
- [ ] 결론: **`review.md` 안에 경고를 렌더한다.** 후속 작업으로 둔다 —
      렌더러·파서가 함께 움직이고 `v:` 해시 범위를 정해야 한다
  - (고침) `*mrq*` 에서 `RET` 이 "No error here" 만 냈다. 그 버퍼가 `mrq` 항목
    (`review.md` 의 `## [x] path:line` **헤더**용)을 쓰고 있어서 로그 줄
    `review.md:142: ...` 를 아예 못 잡았다. `mrq-log` 항목을 따로 뒀다.
    위치 없는 경고는 접두사가 없어 안 잡힌다 — 가짜 위치 금지는 그대로다

## 충돌 UI — 만들기 쉽지만 쓰기 전까지 모르는 것

터미널에서 `mrq reply <id> -m "AI 쪽"` 을 돌린 뒤 같은 스레드를 `review.md` 에서
다르게 고치면 충돌이 만들어진다. 둘 이상 만들어야 의미가 있다.

- [x] 저장 → `*mrq conflicts*` 가 뜨고 양쪽 값이 보인다
- [x] `m`/`j` 로 섞어 고르고 `C-c C-c` → 한 번에 해소된다
- [x] 하나를 안 고르고 `C-c C-c` → 거부하고 그 스레드로 커서가 간다
- [x] **양쪽 값만 보고 고를 수 있었는가?** 답글이 길면 첫 줄만 보여주는데
      그걸로 판단이 되는지
- [x] **충돌 둘 이상을 만들기가 어렵다** — 결함이 아니라 관찰. 내가 `review.md` 를
      편집하는 중에 AI 가 밖에서 `mrq reply` 를 돌리면 Emacs 가 즉시 "파일이
      외부에서 바뀌었다" 고 알리고, 그때 덮어쓰기 저장을 하면 이른 시점에 `sync`
      가 돌아 충돌 창이 좁아진다. Emacs 에서는 충돌이 드물게 난다는 뜻이고,
      충돌 UI 가 무가치하다는 뜻은 아니다 (터미널/AI 단독 경로에서는 난다)

## 리뷰에서 고친 것들 — 재확인

- [x] 리뷰와 무관한 다른 프로젝트의 `.py` 버퍼에서 `C-c m` 이 mrq 에 **안** 묶여
      있다 (`C-h k C-c m`). 마이너 모드로 바꾼 것의 확인
- [x] `C-c m p` 의 확인 프롬프트에 `replies N · resolves N · skipped N` 이 보인다
- [ ] `.mrq/<iid>/` 를 지웠다가 다시 `pull` 한 뒤에도 진단이 자동 갱신된다
      (watch 재등록). **`mrq clean` 이 아니라 `rm -rf .mrq/1` 로 해야 한다** —
      `clean` 은 merged/closed MR 만 대상이고 `!1` 은 열려 있다 (`cli.md` §11).
      체크리스트가 틀렸다
- [x] 충돌을 해소하면 `review.md` 버퍼가 **즉시** 새 내용으로 바뀐다

## 문제가 있으면

`*mrq*` 버퍼와 `*Messages*` 를 함께 붙여 주면 된다.
`M-x toggle-debug-on-error` 뒤 재현하면 백트레이스가 남는다.
`M-x flymake-show-buffer-diagnostics` 가 진단의 출처를 보여준다.
