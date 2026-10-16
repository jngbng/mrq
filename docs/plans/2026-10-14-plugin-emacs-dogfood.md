# 실측 체크리스트 — `plugin_emacs`

배치 ERT 가 못 잡는 것만 모았다: **실제 설정과의 상호작용**, 키 바인딩 충돌,
그리고 사람이 메시지를 실제로 **알아채는지**.

끝난 항목은 지웠다 — 고친 내용은 git 히스토리와 스펙에 남아 있다. 여기서 나온
후속 작업은 `residuals.md`.

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

## 남은 확인

- [ ] `mrq-show-handled` 를 켜면 전부 뜬다
- [ ] `.mrq/<iid>/` 를 지웠다가 다시 `pull` 한 뒤에도 진단이 자동 갱신된다
      (watch 재등록). **`mrq clean` 이 아니라 `rm -rf .mrq/1` 로 해야 한다** —
      `clean` 은 merged/closed MR 만 대상이고 `!1` 은 열려 있다 (`cli.md` §11)
- [ ] 큰 파일(수천 줄)에서 편집 중 체감 지연이 없다 — 보정은 버퍼를 통째로
      문자열 벡터로 만든다. `mr-helper` 의 파일이 작아 확인하지 못했다.
      다른 리포에서 `mrq pull` 을 한 번 돌려 보는 쪽이 빠르다

## 문제가 있으면

`*mrq*` 버퍼와 `*Messages*` 를 함께 붙여 주면 된다.
`M-x toggle-debug-on-error` 뒤 재현하면 백트레이스가 남는다.
`M-x flymake-show-buffer-diagnostics` 가 진단의 출처를 보여준다.
