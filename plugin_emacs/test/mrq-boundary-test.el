;;; mrq-boundary-test.el --- editor.md §1 을 코드 모양으로 고정 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §1 의 경계는 문장이라 코드가 조용히 벗어날 수 있다.  네 가지를
;; grep 수준에서 강제한다 —
;;
;;   §1-1  json 을 파싱하는 코드는 `mrq-core.el'(review.json) 과
;;         `mrq-cli.el'(CLI 의 --json 페이로드) 둘에만 있다
;;   §1-2  `mrq-core.el' 에 쓰기 함수가 없다
;;   §1-4  어디에도 git 호출이 없다
;;         프로세스를 띄우는 코드는 `mrq-cli.el' 에만 있다
;;
;; 약한 테스트지만, 이 경계를 깨는 변경은 거의 항상 이 패턴으로 나타난다.
;; 특히 §1-1 이 막으려는 것은 `review.md' 파서가 두 번째로 생기는 것이다.

;;; Code:

(require 'ert)

;; 다섯 번째 규칙("md 에서 상태 문자를 해석하지 않는다")은 두지 않는다.
;; `local.state' 를 **review.json 에서** 읽는 것은 에디터가 해야 하는 일이라
;; grep 으로는 허용과 금지를 가를 수 없다 — 쓸 수 있는 형태가 전부 항상
;; 통과하는 테스트가 된다.  그 경계는 `mrq-mode.el' 의 토글이 읽은 문자를
;; 즉시 치환만 한다는 것(`replace-match')으로 지켜지고, 리뷰가 본다.

(defconst mrq-boundary-test--src-dir
  (expand-file-name ".." (file-name-directory (or load-file-name buffer-file-name)))
  "`plugin_emacs/' 자신.")

(defun mrq-boundary-test--sources ()
  "`plugin_emacs/*.el' 전부.  테스트 파일은 포함하지 않는다."
  (directory-files mrq-boundary-test--src-dir t "\\.el\\'"))

(defun mrq-boundary-test--content (path)
  "PATH 의 내용."
  (with-temp-buffer (insert-file-contents path) (buffer-string)))

(ert-deftest mrq-boundary-only-core-and-cli-parse-json ()
  "§1-1 — json 을 읽는 자리가 둘뿐이면 `review.md' 파서가 생길 자리가 없다.

`mrq-core.el' 은 `review.json' 을, `mrq-cli.el' 은 CLI 의 `--json' 페이로드를
파싱한다.  서로 다른 것을 읽으므로 둘 다 허용한다."
  (dolist (path (mrq-boundary-test--sources))
    (unless (member (file-name-nondirectory path) '("mrq-core.el" "mrq-cli.el"))
      (ert-info ((file-name-nondirectory path) :prefix "파일: ")
        (should-not (string-match-p "json-parse\\|json-read"
                                    (mrq-boundary-test--content path)))))))

(ert-deftest mrq-boundary-core-never-writes ()
  "§1-2 — 상태 변경은 `mrq reply'/`state'/`sync' 로만 한다."
  (let ((text (mrq-boundary-test--content
               (expand-file-name "mrq-core.el" mrq-boundary-test--src-dir))))
    (dolist (forbidden '("write-region" "with-temp-file" "delete-file" "rename-file"))
      (ert-info (forbidden :prefix "금지: ")
        (should-not (string-match-p (regexp-quote forbidden) text))))))

(ert-deftest mrq-boundary-nothing-calls-git ()
  "§1-4 MUST NOT — git 도 네트워크도 부르지 않는다.

리포 루트는 `.mrq/current' 를 위로 찾아 얻는다 (§2) — 디렉터리 탐색이지
git 호출이 아니다."
  (dolist (path (mrq-boundary-test--sources))
    (let ((text (mrq-boundary-test--content path)))
      (ert-info ((file-name-nondirectory path) :prefix "파일: ")
        (should-not (string-match-p "\"git\"\\|url-retrieve\\|\\bmagit-" text))))))

(ert-deftest mrq-boundary-only-cli-spawns-processes ()
  "프로세스를 띄우는 자리가 하나여야 `mrq-executable' 설정이 의미가 있다."
  (dolist (path (mrq-boundary-test--sources))
    (unless (equal (file-name-nondirectory path) "mrq-cli.el")
      (ert-info ((file-name-nondirectory path) :prefix "파일: ")
        (should-not (string-match-p "call-process\\|start-process\\|shell-command"
                                    (mrq-boundary-test--content path)))))))

(provide 'mrq-boundary-test)
;;; mrq-boundary-test.el ends here
