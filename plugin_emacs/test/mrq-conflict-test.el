;;; mrq-conflict-test.el --- 충돌 해소 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.4, `cli.md' §5 (`--prefer [ID=]md|json'), `decisions/0013'.
;;
;; 가장 중요한 것: **키를 누를 때마다 `sync' 를 부르면 안 된다.**
;; 부분 해소는 exit 3 으로 전부 실패하므로 첫 키부터 아무것도 안 된다.

;;; Code:

(require 'ert)
(require 'cl-lib)
(require 'mrq-conflict)
(require 'mrq-test-helper)

(defun mrq-conflict-test--payload ()
  "충돌 둘 — 하나는 md, 하나는 json 으로 고를 것이다."
  (json-parse-string
   (concat "{\"iid\":1234,\"conflicts\":["
           "{\"thread\":\"a1b2c3d4e5f6\","
           " \"md\":{\"state\":\"done\",\"reply\":\"확인했습니다.\"},"
           " \"json\":{\"state\":\"replied\",\"reply\":\"AI: 상위에서 설정 중입니다.\"}},"
           "{\"thread\":\"b2c3d4e5f6a1\","
           " \"md\":{\"state\":\"skipped\",\"reply\":\"\"},"
           " \"json\":{\"state\":\"replied\",\"reply\":\"AI: 세션 재사용.\"}}]}")
   :array-type 'list))

(defmacro mrq-conflict-test--with-buffer (root &rest body)
  "ROOT 기준으로 충돌 버퍼를 띄우고 그 안에서 BODY 를 실행한다."
  (declare (indent 1) (debug t))
  `(progn
     (mrq-conflict-show (mrq-conflict-test--payload)
                        (mrq-core-review-dir (expand-file-name "x.py" ,root)))
     (unwind-protect
         (with-current-buffer mrq-conflict-buffer-name ,@body)
       (when (get-buffer mrq-conflict-buffer-name)
         (kill-buffer mrq-conflict-buffer-name)))))

(ert-deftest mrq-conflict-lists-every-conflict-unchosen ()
  (mrq-test-with-repo (root)
    (mrq-conflict-test--with-buffer root
      (let ((text (buffer-string)))
        (should (string-match-p "a1b2c3d4e5f6" text))
        (should (string-match-p "b2c3d4e5f6a1" text))
        (should (= (how-many "→ \\?$" (point-min) (point-max)) 2))))))

(ert-deftest mrq-conflict-shows-both-sides-of-each-thread ()
  "값을 모르면 사용자는 고를 수 없다 (`editor.md' §3.4).

이 UI 가 없으면 충돌을 보여줄 수는 있어도 해소할 방법이 없다 — 사용자가 md 를
수동으로 되돌리는 수밖에 없고, json 값을 모르면 그것도 불가능하다."
  (mrq-test-with-repo (root)
    (mrq-conflict-test--with-buffer root
      (let ((text (buffer-string)))
        (should (string-match-p "확인했습니다\\." text))
        (should (string-match-p "AI: 상위에서 설정 중입니다\\." text))
        (should (string-match-p "done" text))
        (should (string-match-p "replied" text))))))

(ert-deftest mrq-conflict-refuses-to-apply-while-anything-is-unchosen ()
  "부분 해소는 CLI 에서 exit 3 이다.  UI 가 그것을 그대로 반영한다."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root)))
      (mrq-conflict-test--with-buffer root
        (should (equal (mrq-conflict--id-at-point) "a1b2c3d4e5f6"))
        (mrq-conflict-choose-md)
        (should-error (mrq-conflict-apply) :type 'user-error)
        (should (null (mrq-test-cli-calls root)))))))

(ert-deftest mrq-conflict-moves-point-to-the-unchosen-thread ()
  "거부만 하고 어디가 문제인지 안 보여주면 사용자가 찾아야 한다."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root)))
      (mrq-conflict-test--with-buffer root
        (mrq-conflict-choose-md)               ; 첫 번째만 고른다
        (ignore-errors (mrq-conflict-apply))
        (should (equal (mrq-conflict--id-at-point) "b2c3d4e5f6a1"))))))

(ert-deftest mrq-conflict-sends-one-sync-with-every-choice ()
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root :stdout "{\"iid\":1234,\"applied\":[]}")))
      (mrq-conflict-test--with-buffer root
        (mrq-conflict-choose-md)               ; a1b2 → md
        (mrq-conflict-next)
        (mrq-conflict-choose-json)             ; b2c3 → json
        (mrq-conflict-apply))
      (should (equal (mrq-test-cli-calls root)
                     '("sync --json --prefer a1b2c3d4e5f6=md --prefer b2c3d4e5f6a1=json"))))))

(ert-deftest mrq-conflict-fill-all-then-override-one ()
  "`M' 로 채우고 개별 `j' 로 덮는다 — CLI 의 스코프 우선 규칙과 같은 모양."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root :stdout "{\"iid\":1234,\"applied\":[]}")))
      (mrq-conflict-test--with-buffer root
        (mrq-conflict-choose-all-md)
        (mrq-conflict-next)
        (mrq-conflict-choose-json)
        (mrq-conflict-apply))
      (should (equal (mrq-test-cli-calls root)
                     '("sync --json --prefer a1b2c3d4e5f6=md --prefer b2c3d4e5f6a1=json"))))))

(ert-deftest mrq-conflict-choice-is-visible-and-reversible ()
  (mrq-test-with-repo (root)
    (mrq-conflict-test--with-buffer root
      (mrq-conflict-choose-md)
      (should (string-match-p "a1b2c3d4e5f6   → md" (buffer-string)))
      (mrq-conflict-choose-json)
      (should (string-match-p "a1b2c3d4e5f6   → json" (buffer-string)))
      (should (= (how-many "→ \\?$" (point-min) (point-max)) 1)))))

(ert-deftest mrq-conflict-choosing-keeps-point-on-the-same-thread ()
  "다시 그린 뒤 커서가 처음으로 튀면 둘째 스레드를 고르기 전에 길을 잃는다."
  (mrq-test-with-repo (root)
    (mrq-conflict-test--with-buffer root
      (mrq-conflict-next)
      (should (equal (mrq-conflict--id-at-point) "b2c3d4e5f6a1"))
      (mrq-conflict-choose-json)
      (should (equal (mrq-conflict--id-at-point) "b2c3d4e5f6a1")))))

(ert-deftest mrq-conflict-navigation-stops-at-the-ends ()
  (mrq-test-with-repo (root)
    (mrq-conflict-test--with-buffer root
      (mrq-conflict-next)
      (should-error (mrq-conflict-next) :type 'user-error)
      (mrq-conflict-previous)
      (should-error (mrq-conflict-previous) :type 'user-error))))

(ert-deftest mrq-conflict-reports-a-failed-sync-without-closing ()
  "해소가 실패했는데 창이 닫히면 사용자가 선택을 다시 해야 한다."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root :code 3 :stderr "충돌 1건\n")))
      (mrq-conflict-test--with-buffer root
        (mrq-conflict-choose-all-md)
        (mrq-conflict-apply)
        (should (get-buffer mrq-conflict-buffer-name))))))

(provide 'mrq-conflict-test)
;;; mrq-conflict-test.el ends here
