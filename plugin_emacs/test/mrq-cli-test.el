;;; mrq-cli-test.el --- mrq 프로세스 호출 계층 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `cli.md' §2 — stdout 은 순수 JSON, 경고·에러는 stderr.  섞으면 파싱이 깨진다.

;;; Code:

(require 'ert)
(require 'mrq-cli)
(require 'mrq-test-helper)

(ert-deftest mrq-cli-separates-stdout-from-stderr ()
  "둘을 섞으면 `--json' 페이로드 파싱이 경고 한 줄에 깨진다."
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli
                            root
                            :stdout "{\"iid\": 1234, \"applied\": []}"
                            :stderr "review.md:142: 앵커 다음 줄이 헤더가 아님\n"))
           (result (mrq-cli-run '("sync" "--json") nil root)))
      (should (= (plist-get result :code) 0))
      (should (equal (gethash "iid" (plist-get result :json)) 1234))
      (should (string-match-p "review.md:142" (plist-get result :stderr)))
      (should-not (string-match-p "review.md:142" (plist-get result :stdout))))))

(ert-deftest mrq-cli-reports-the-exit-code ()
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli
                            root :code 3
                            :stdout "{\"iid\": 1, \"conflicts\": []}"))
           (result (mrq-cli-run '("sync" "--json") nil root)))
      (should (= (plist-get result :code) 3))
      ;; exit 3 에도 페이로드가 있다 (cli.md §5)
      (should (plist-get result :json)))))

(ert-deftest mrq-cli-leaves-json-nil-when-stdout-is-not-json ()
  "`pull' 처럼 `--json' 이 없는 명령은 평문을 낸다.  깨지면 안 된다."
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli root :stdout "pulled: 15 스레드\n"))
           (result (mrq-cli-run '("pull") nil root)))
      (should (= (plist-get result :code) 0))
      (should (null (plist-get result :json)))
      (should (string-match-p "15" (plist-get result :stdout))))))

(ert-deftest mrq-cli-leaves-json-nil-when-stdout-is-truncated-json ()
  "중간에 죽은 CLI 의 반쪽 stdout 에 에러를 올리지 않는다."
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli root :code 1 :stdout "{\"iid\": 12"))
           (result (mrq-cli-run '("sync" "--json") nil root)))
      (should (= (plist-get result :code) 1))
      (should (null (plist-get result :json))))))

(ert-deftest mrq-cli-passes-the-body-on-stdin-not-as-an-argument ()
  "답글 본문을 인자로 넘기지 않는다 (CLAUDE.md, `cli.md' §9)."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root)))
      (mrq-cli-run '("reply" "a1b2" "-F" "-") "본문에 --force 가 있어도 안전하다" root)
      (should (equal (mrq-test-cli-stdin root) "본문에 --force 가 있어도 안전하다"))
      (should (equal (mrq-test-cli-calls root) '("reply a1b2 -F -"))))))

(ert-deftest mrq-cli-runs-in-the-given-directory ()
  "CLI 는 cwd 에서 리포를 찾는다 (`store.py').

DIR 을 무시하면 리포 밖 `default-directory' 를 가진 버퍼에서 엉뚱한 리포를
보거나 실패한다 — 호출 기록만 보면 그것이 드러나지 않는다."
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli root))
           (default-directory temporary-file-directory))
      (mrq-cli-run '("status" "--json") nil root)
      (should (equal (mrq-test-cli-calls root) '("status --json")))
      (should (equal (mapcar #'file-truename (mrq-test-cli-cwds root))
                     (list (file-truename root)))))))

(ert-deftest mrq-cli-reports-a-missing-executable-without-signalling ()
  "`mrq-executable' 이 PATH 에 없을 때 편집을 막으면 안 된다."
  (mrq-test-with-repo (root)
    (let* ((mrq-executable "mrq-does-not-exist-anywhere")
           (result (mrq-cli-run '("status" "--json") nil root)))
      (should (/= (plist-get result :code) 0))
      (should (null (plist-get result :json))))))

(provide 'mrq-cli-test)
;;; mrq-cli-test.el ends here
