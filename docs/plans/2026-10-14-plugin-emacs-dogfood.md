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
M-x load-library RET mrq RET          ; 고친 파일만
```

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
- [ ] `C-c m n` / `C-c m p` 가 코멘트 사이를 돈다
      (`flymake-goto-next-error`/`-prev-error`. flymake 는 이 둘에 기본 바인딩을
      주지 않고 `M-g n`(`next-error`)으로도 안 된다 — 소스 버퍼에서
      `next-error-function` 을 설정하지 않는다. 당신 Exordium 설정은 `M-g` 를
      `goto-line` 에 묶어 접두사 자체를 없앴다: `init-look-and-feel.el:281`)
- [ ] `C-c m r` → `review.md` 의 해당 `### reply` 로 간다
- [ ] 답글을 쓰고 저장 → `sync` 가 돌고 **커서가 그 스레드에 남는다**
- [ ] 저장 후 열린 소스 버퍼의 진단이 **자동으로** 갱신된다 (file-notify)
- [ ] `C-c C-t` 로 체크박스를 돌리고 저장 → 상태가 반영된다
- [ ] `RET` 로 목록에서 소스로, `C-c m r` 로 소스에서 목록으로 — 왕복이 닫힌다
- [ ] `C-c C-g`(pull) / `C-c C-r`(reanchor) 가 동작하고 버퍼가 갱신된다
- [ ] `C-c C-p` 가 status 요약을 보여주고 확인을 받는다

## 당신 설정과의 상호작용 — ERT 가 못 보는 부분

- [ ] **다른 flymake 백엔드와 공존한다.** 파이썬/elisp 버퍼에서 기존 린터 진단과
      섞여 뜨고, 어느 쪽도 사라지지 않는다. (`M-x flymake-show-buffer-diagnostics`
      로 둘 다 보이는지 확인)
- [ ] **키 바인딩이 충돌하지 않는다.** `C-h k C-c m r` / `C-c m n` 이 각각
      `mrq-reply-at-point` / `flymake-goto-next-error` 를 가리킨다. Exordium 의
      기존 `C-c m` 바인딩과 겹치지 않는다
- [ ] `M-n`/`M-p` 처럼 더 짧은 키를 쓰고 싶으면:
      `(define-key mrq-minor-mode-map (kbd "M-n") #'flymake-goto-next-error)`
- [ ] `review.md` 에서 평문 글자가 전부 그대로 입력된다 — 리뷰에서 `g`/`r` 이
      명령에 묶여 있던 것을 `C-c C-g`/`C-c C-r` 로 옮겼다. `C-c C-s`/`C-c C-p`/
      `C-c C-t` 가 markdown-mode 의 기존 바인딩과 겹치지 않는지도 확인
- [ ] 답글을 쓰다가 저장하지 않은 채 `C-c C-s` → **작성 중인 답글이 남는가**
      (저장되고 sync 가 돈다). `C-c C-r`/`C-c C-g` 는 거부해야 한다
- [ ] 큰 파일(수천 줄)에서 편집 중 체감 지연이 없다 — 보정은 버퍼를 통째로
      문자열 벡터로 만든다

## 관찰 항목 — 잠정 결정의 재평가

`editor.md` §3.4 는 **위치 없는 경고**를 에코 영역과 `*mrq*` 로만 보내기로 했고
그 선택을 "잠정" 으로 표시했다 (`mrq-design.md` §6). 지금 그 경고가 알리는 것은
**"답글을 썼는데 전송되지 않는다"** 이고, 놓치면 답글이 그대로 남는다.

- [ ] 답글을 쓰고 체크박스를 `[ ]` 로 **둔 채** 저장한다
- [ ] 그 경고를 **알아챘는가?** 에코 영역은 다른 메시지에 금방 덮인다
- [ ] 알아채지 못했다면 선택지: `*mrq*` 를 자동으로 띄운다 / 헤더라인에 남긴다 /
      `review.md` 안에 경고를 렌더한다. 고른 것을 `mrq-design.md` §6 에 적고
      `editor.md` §3.4 의 "잠정" 표시를 지운다

## 충돌 UI — 만들기 쉽지만 쓰기 전까지 모르는 것

터미널에서 `mrq reply <id> -m "AI 쪽"` 을 돌린 뒤 같은 스레드를 `review.md` 에서
다르게 고치면 충돌이 만들어진다. 둘 이상 만들어야 의미가 있다.

- [ ] 저장 → `*mrq conflicts*` 가 뜨고 양쪽 값이 보인다
- [ ] `m`/`j` 로 섞어 고르고 `C-c C-c` → 한 번에 해소된다
- [ ] 하나를 안 고르고 `C-c C-c` → 거부하고 그 스레드로 커서가 간다
- [ ] **양쪽 값만 보고 고를 수 있었는가?** 답글이 길면 첫 줄만 보여주는데
      그걸로 판단이 되는지

## 리뷰에서 고친 것들 — 재확인

- [ ] 리뷰와 무관한 다른 프로젝트의 `.py` 버퍼에서 `C-c m` 이 mrq 에 **안** 묶여
      있다 (`C-h k C-c m`). 마이너 모드로 바꾼 것의 확인
- [ ] `C-c C-p` 의 확인 프롬프트에 `replies N · resolves N · skipped N` 이 보인다
- [ ] `mrq clean` 으로 `.mrq/<iid>/` 를 지웠다가 다시 `pull` 한 뒤에도 진단이
      자동 갱신된다 (watch 재등록)
- [ ] 충돌을 해소하면 `review.md` 버퍼가 **즉시** 새 내용으로 바뀐다

## 문제가 있으면

`*mrq*` 버퍼와 `*Messages*` 를 함께 붙여 주면 된다.
`M-x toggle-debug-on-error` 뒤 재현하면 백트레이스가 남는다.
`M-x flymake-show-buffer-diagnostics` 가 진단의 출처를 보여준다.
