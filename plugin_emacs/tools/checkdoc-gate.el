;;; checkdoc-gate.el --- checkdoc 를 실제 게이트로 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `checkdoc-file' 은 경고를 찍기만 하고 종료 코드를 바꾸지 않는다 — 그대로
;; 쓰면 `make lint' 이 checkdoc 에 대해서는 게이트가 아니다.  여기서 진단
;; 버퍼를 읽어 경고가 하나라도 있으면 실패시킨다.
;;
;; 대소문자 규칙 둘은 거른다.  이 코드베이스의 독스트링과 메시지는 한국어라
;; "첫 글자를 대문자로" 가 적용될 수 없고, 그것 때문에 나머지 진짜 경고
;; (인자가 독스트링에 안 나옴, 0열의 여는 괄호 등)를 못 쓰게 되는 쪽이 나쁘다.
;;
;; `plugin_emacs/' 가 아니라 `tools/' 에 있는 이유는 Makefile 의 SRC 가
;; `*.el' 이기 때문이다 — 이 파일은 패키지의 일부가 아니다.

;;; Code:

(require 'checkdoc)
(require 'cl-lib)
(require 'seq)

(defconst mrq-checkdoc-ignored
  '("should be capitalized" "start with a capital letter")
  "한국어 독스트링·메시지에 적용할 수 없는 규칙들.")

(defun mrq-checkdoc-gate ()
  "명령행 인자의 파일들을 checkdoc 로 검사하고, 경고가 있으면 실패한다.

`checkdoc-file' 은 batch 에서 진단 버퍼가 아니라 `message' 로 내보내므로
그것을 가로챈다."
  (let ((kept nil)
        (original (symbol-function 'message)))
    (cl-letf (((symbol-function 'message)
               (lambda (format-string &rest args)
                 (let ((line (if args (apply #'format format-string args)
                               format-string)))
                   (when (and (stringp line) (string-match-p "\\.el:[0-9]+" line))
                     (push line kept))
                   (apply original format-string args)))))
      (let ((checkdoc-autofix-flag 'never))
        (dolist (file command-line-args-left)
          (checkdoc-file file))))
    (setq kept (seq-remove (lambda (line)
                             (seq-some (lambda (ignored) (string-match-p ignored line))
                                       mrq-checkdoc-ignored))
                           (nreverse kept)))
    (when kept
      (funcall original "checkdoc: 경고 %d건 (대소문자 규칙 제외)" (length kept))
      (kill-emacs 1))))

(provide 'checkdoc-gate)
;;; checkdoc-gate.el ends here
