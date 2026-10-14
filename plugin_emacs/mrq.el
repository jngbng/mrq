;;; mrq.el --- GitLab MR 리뷰 코멘트를 버퍼에서 -*- lexical-binding: t -*-

;; Author: mrq contributors
;; Version: 0.1.0
;; Package-Requires: ((emacs "29.1") (markdown-mode "2.5"))
;; Keywords: tools, vc
;; URL: https://github.com/jngbng/mrq

;;; Commentary:
;;
;; `mrq' CLI 가 내려받은 MR 코멘트를 소스 버퍼의 flymake 진단으로 띄우고,
;; `review.md' 에서 답글을 쓰고, 저장하면 `mrq sync' 를 돌린다.
;;
;; 설정 예:
;;
;;   (use-package mrq
;;     :load-path "~/workspace/mrq/plugin_emacs"
;;     :hook (prog-mode . mrq-setup))
;;
;; `mrq-setup' 은 `.mrq/current' 를 못 찾으면 조용히 빠지므로 `prog-mode-hook'
;; 에 걸어도 안전하다.
;;
;; 이 파일은 진입점이다.  나머지는 `mrq-setup' 이 필요할 때 끌어온다 —
;; 로드 시점에 `markdown-mode' 까지 당겨오지 않기 위해서다.
;;
;; 왕복:  소스에서 `M-g n' 으로 코멘트를 돌고 -> `C-c m r' 로 `review.md' 의
;; 해당 `### reply' 로 점프 -> 답글을 쓰고 저장 -> `mrq sync' 가 돌고
;; `file-notify' 가 열린 버퍼의 진단을 갱신한다.

;;; Code:

(require 'flymake)
(require 'mrq-core)

;; `mrq-setup' 이 필요할 때 끌어오므로 컴파일 시점에는 없다.
(declare-function mrq-flymake-setup "mrq-flymake")
(declare-function mrq-reply-at-point "mrq-mode")

(defvar mrq-command-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "r") #'mrq-reply-at-point)
    (define-key map (kbd "n") #'flymake-goto-next-error)
    (define-key map (kbd "p") #'flymake-goto-prev-error)
    map)
  "소스 버퍼에서 `C-c m' 뒤에 오는 키들.

`n'/`p' 는 flymake 의 기존 명령에 **키만** 준다 (`editor.md' §3.1 이 새 명령을
만들지 말라고 한다).  그런데 flymake 는 그 둘에 기본 바인딩을 주지 않고
\(`flymake-mode-map' 에는 메뉴바와 fringe 뿐이다), 소스 버퍼에서
`next-error-function' 도 설정하지 않아 `M-g n' 으로도 닿지 않는다 — 키가
없으면 \"그 명령이 그대로 다음 코멘트 이동이 된다\" 는 문장이 닿지 않는다.

더 짧은 키를 원하면 사용자가 직접 준다:

  (define-key mrq-minor-mode-map (kbd \"M-n\") #\='flymake-goto-next-error)")

(defvar mrq-minor-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c m") mrq-command-map)
    map)
  "`mrq-minor-mode' 의 키맵.")

;;;###autoload
(define-minor-mode mrq-minor-mode
  "소스 버퍼에서 MR 코멘트를 다루는 키들.

마이너 모드로 두는 이유는 `local-set-key' 가 현재 로컬 맵을 **그 자리에서**
고치기 때문이다 — 그 맵이 곧 메이저 모드 맵이라, `prog-mode-hook' 에서 한 번
부르면 그 세션의 모든 같은 모드 버퍼(리뷰와 무관한 다른 프로젝트 포함)가
오염된다."
  :lighter " mrq"
  :keymap mrq-minor-mode-map)

;;;###autoload
(defun mrq-setup ()
  "이 버퍼에 mrq 를 켠다.  리뷰가 없는 리포면 아무것도 하지 않는다.

`prog-mode-hook' 에 걸어도 안전하다 — `.mrq/current' 가 없으면 조용히 빠진다."
  (interactive)
  (when (mrq-core-review-dir (buffer-file-name))
    (require 'mrq-flymake)
    (require 'mrq-mode)
    (mrq-flymake-setup)
    (mrq-minor-mode 1)))

(provide 'mrq)
;;; mrq.el ends here
