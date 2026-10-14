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

(require 'mrq-core)

;; `mrq-setup' 이 필요할 때 끌어오므로 컴파일 시점에는 없다.
(declare-function mrq-flymake-setup "mrq-flymake")
(declare-function mrq-reply-at-point "mrq-mode")

(defvar mrq-command-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "r") #'mrq-reply-at-point)
    map)
  "소스 버퍼에서 `C-c m' 뒤에 오는 키들.")

;;;###autoload
(defun mrq-setup ()
  "이 버퍼에 mrq 를 켠다.  리뷰가 없는 리포면 아무것도 하지 않는다.

`prog-mode-hook' 에 걸어도 안전하다 — `.mrq/current' 가 없으면 조용히 빠진다."
  (interactive)
  (when (mrq-core-review-dir (buffer-file-name))
    (require 'mrq-flymake)
    (require 'mrq-mode)
    (mrq-flymake-setup)
    (local-set-key (kbd "C-c m") mrq-command-map)))

(provide 'mrq)
;;; mrq.el ends here
