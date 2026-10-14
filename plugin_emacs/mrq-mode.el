;;; mrq-mode.el --- review.md 목록 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.2.  `review.md' 의 메이저 모드다.
;;
;; 이 파일은 `review.md' 에서 **점을 옮기기 위한 검색**만 한다 — 상태나 답글을
;; 추출하지 않는다.  그 값을 읽는 경로는 `review.json' 하나이고 (`mrq-core'),
;; md -> json 변환은 `mrq sync' 하나다 (`editor.md' §1-1).
;;
;; `C-c C-t' 의 체크박스 순환도 **문자 치환**일 뿐이다.  의미는 `sync' 가 준다.

;;; Code:

(require 'cl-lib)
(require 'compile)
(require 'markdown-mode)
(require 'subr-x)
(require 'mrq-anchor)
(require 'mrq-cli)
(require 'mrq-core)

(defconst mrq-mode-header-re "^## \\[.\\] \\(.+?\\):\\([0-9]+\\)"
  "위치가 있는 스레드 헤더.  `review-md.md' §3.

`(general)' 헤더는 **의도적으로** 매치되지 않는다 — 위치를 못 찾은 것이
아니라 위치가 없는 코멘트이고, 가짜 위치로 점프시키면 안 된다.")

(defconst mrq-mode-anchor-re
  "^<!-- mrq:\\([0-9a-f]\\{8,\\}\\)\\(?: v:[0-9a-f]\\{6\\}\\)? -->$"
  "스레드 블록의 경계.  `review-md.md' §2 — 앵커는 헤더 **위**에 있다.")

(defconst mrq-mode--state-cycle '(?\s ?x ?~ ?-)
  "`C-c C-t' 의 순환 순서.  `review-md.md' §3 의 상태 문자.")

(defvar mrq-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'mrq-mode-visit)
    (define-key map (kbd "C-c C-t") #'mrq-mode-toggle-state)
    map)
  "`mrq-mode' 의 키맵.")

(add-to-list 'compilation-error-regexp-alist-alist
             (list 'mrq mrq-mode-header-re 1 2))

;;;###autoload
(define-derived-mode mrq-mode markdown-mode "MRQ"
  "`review.md' 를 다루는 메이저 모드.

`markdown-mode' 에서 파생하는 이유는 답글에 표·코드펜스·수평선이 평범하게
들어오기 때문이다 (`review-md.md' §1)."
  (setq-local compilation-error-regexp-alist '(mrq))
  (setq-local next-error-function #'mrq-mode-next-error))

;;;###autoload
(add-to-list 'auto-mode-alist '("/\\.mrq/[^/]+/review\\.md\\'" . mrq-mode))

(defun mrq-mode--repo-root ()
  "`review.md' 가 속한 리포 루트.

`default-directory' 를 쓰면 안 된다 — 헤더의 경로는 **리포 상대**이고 이
버퍼는 `.mrq/<iid>/' 에 있다."
  (or (mrq-core-root (buffer-file-name))
      (user-error "리포 루트를 찾을 수 없습니다 (.mrq/current 가 없습니다)")))

(defun mrq-mode--header-at-point ()
  "point 가 속한 블록의 헤더에서 (경로 . 줄).  위치 헤더가 아니면 nil."
  (save-excursion
    (beginning-of-line)
    (unless (looking-at mrq-mode-header-re)
      (when (re-search-backward mrq-mode-anchor-re nil t)
        (forward-line 1)))
    (when (looking-at mrq-mode-header-re)
      (cons (match-string-no-properties 1)
            (string-to-number (match-string-no-properties 2))))))

(defun mrq-mode-visit ()
  "point 의 스레드가 가리키는 소스 위치로 이동한다."
  (interactive)
  (let ((target (mrq-mode--header-at-point)))
    (unless target
      (user-error "여기에는 위치가 있는 스레드 헤더가 없습니다"))
    (let ((path (expand-file-name (car target) (mrq-mode--repo-root))))
      (unless (file-exists-p path)
        (user-error "%s 가 없습니다" (car target)))
      (find-file path)
      (goto-char (point-min))
      (forward-line (1- (cdr target))))))

(defun mrq-mode-next-error (n reset)
  "`next-error-function'.  N 개 앞/뒤로, RESET 이면 처음부터.

`(general)' 헤더는 `mrq-mode-header-re' 가 잡지 않으므로 자연히 건너뛴다."
  (when reset (goto-char (point-min)))
  (let ((forward (>= n 0)))
    (dotimes (_ (max 1 (abs n)))
      (if forward
          (progn
            (end-of-line)
            (unless (re-search-forward mrq-mode-header-re nil t)
              (user-error "다음 코멘트가 없습니다")))
        (beginning-of-line)
        (unless (re-search-backward mrq-mode-header-re nil t)
          (user-error "이전 코멘트가 없습니다")))
      (beginning-of-line)))
  (mrq-mode-visit))

(defun mrq-mode-toggle-state ()
  "point 가 속한 블록의 체크박스를 순환시킨다.

`[ ]' -> `[x]' -> `[~]' -> `[-]' -> `[ ]'.  **문자만 바꾼다** — 이 함수는
상태의 의미를 해석하지 않고, 반영은 저장 시 `mrq sync' 가 한다."
  (interactive)
  (save-excursion
    (beginning-of-line)
    (unless (looking-at "^## \\[.\\]")
      (if (re-search-backward mrq-mode-anchor-re nil t)
          (forward-line 1)
        (user-error "스레드 블록 안이 아닙니다")))
    (unless (looking-at "^## \\[\\(.\\)\\]")
      (user-error "스레드 헤더를 찾을 수 없습니다"))
    (let* ((current (string-to-char (match-string 1)))
           (rest (cdr (memq current mrq-mode--state-cycle)))
           (next (or (car rest) (car mrq-mode--state-cycle))))
      (replace-match (char-to-string next) t t nil 1))))

(provide 'mrq-mode)
;;; mrq-mode.el ends here
