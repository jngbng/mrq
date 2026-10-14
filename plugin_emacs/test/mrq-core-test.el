;;; mrq-core-test.el --- 리뷰 상태 접근 계층 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §2 (리뷰 디렉터리 찾기), §1-5 (파일 감시), §1-6 (schema_version).

;;; Code:

(require 'ert)
(require 'cl-lib)
(require 'mrq-core)
(require 'mrq-test-helper)

(ert-deftest mrq-core-finds-review-dir-through-symlink ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let ((file (expand-file-name "src/api/client.py" root)))
      (should (equal (file-truename (mrq-core-review-dir file))
                     (file-name-as-directory (file-truename (expand-file-name ".mrq/1234" root)))))
      (should (equal (file-name-as-directory (file-truename (mrq-core-root file)))
                     (file-name-as-directory (file-truename root)))))))

(ert-deftest mrq-core-finds-review-dir-through-plain-file ()
  "`current' 가 일반 파일이면 내용을 iid 로 읽는다 (`data-model.md' §1)."
  (mrq-test-with-repo (root :symlink nil :files '(("src/api/client.py" . "x\n")))
    (should (equal (file-truename
                    (mrq-core-review-dir (expand-file-name "src/api/client.py" root)))
                   (file-name-as-directory (file-truename (expand-file-name ".mrq/1234" root)))))))

(ert-deftest mrq-core-returns-nil-outside-a-review-repo ()
  (let ((dir (file-truename (make-temp-file "mrq-bare-" t))))
    (unwind-protect
        (should (null (mrq-core-review-dir (expand-file-name "a.py" dir))))
      (delete-directory dir t))))

(ert-deftest mrq-core-does-not-cache-a-failed-lookup ()
  "`.mrq' 가 생기기 전에 연 버퍼가 영원히 죽으면 안 된다.

사용자는 `mrq pull' 전에 소스를 열어 둔다.  탐색 실패를 버퍼 로컬에 기억하면
그 버퍼는 pull 뒤에도 진단이 안 뜬다."
  (let ((dir (file-truename (make-temp-file "mrq-late-" t))))
    (unwind-protect
        (let ((file (expand-file-name "a.py" dir)))
          (write-region "x\n" nil file nil 'quiet)
          (with-current-buffer (find-file-noselect file)
            (should (null (mrq-core-review-dir file)))
            (make-directory (expand-file-name ".mrq/7" dir) t)
            (write-region (mrq-test-sample-review) nil
                          (expand-file-name ".mrq/7/review.json" dir) nil 'quiet)
            (make-symbolic-link "7" (expand-file-name ".mrq/current" dir))
            (should (mrq-core-review-dir file))))
      (mrq-test-kill-buffers-under dir)
      (mrq-core-forget-all)
      (delete-directory dir t))))

(ert-deftest mrq-core-follows-current-when-it-points-elsewhere ()
  "`pull --mr 9' 가 심링크를 갈아 끼운다.

리뷰 디렉터리를 버퍼 로컬에 캐시하면 옛 MR 의 코멘트를 계속 보여준다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let ((file (expand-file-name "src/api/client.py" root)))
      (should (mrq-core-review-dir file))
      (make-directory (expand-file-name ".mrq/9" root) t)
      (write-region (mrq-test-sample-review) nil
                    (expand-file-name ".mrq/9/review.json" root) nil 'quiet)
      (delete-file (expand-file-name ".mrq/current" root))
      (make-symbolic-link "9" (expand-file-name ".mrq/current" root))
      (should (equal (file-truename (mrq-core-review-dir file))
                     (file-name-as-directory (file-truename (expand-file-name ".mrq/9" root))))))))

(ert-deftest mrq-core-threads-for-filters-by-path ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")
                                     ("src/api/retry.py" . "y\n")))
    (let ((threads (mrq-core-threads-for (expand-file-name "src/api/client.py" root))))
      ;; rendered.json 에서 client.py 를 가리키는 스레드는 셋이다
      (should (= (length threads) 3))
      (dolist (thread threads)
        (should (equal (gethash "path" (gethash "location" thread))
                       "src/api/client.py"))))))

(ert-deftest mrq-core-threads-for-skips-locationless-threads ()
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "y\n")))
    (let ((ids (mapcar (lambda (th) (gethash "id" th))
                       (mrq-core-threads-for
                        (expand-file-name "src/api/retry.py" root)))))
      (should (equal ids '("f6a1b2c3d4e5"))))))

(ert-deftest mrq-core-refuses-an-unknown-schema-version ()
  "§1-6 MUST — 모르는 버전이면 동작을 거부한다."
  (let ((text (replace-regexp-in-string
               "\"schema_version\": 1" "\"schema_version\": 99"
               (mrq-test-sample-review) t t)))
    (mrq-test-with-repo (root :review text :files '(("src/api/client.py" . "x\n")))
      (let ((file (expand-file-name "src/api/client.py" root)))
        (should (null (mrq-core-threads-for file)))
        (should (null (mrq-core-review (mrq-core-review-dir file))))))))

(ert-deftest mrq-core-warns-once-per-unknown-version ()
  "flymake 는 편집 중 반복 호출된다.  매번 경고하면 미니버퍼를 못 쓴다."
  (let ((text (replace-regexp-in-string
               "\"schema_version\": 1" "\"schema_version\": 99"
               (mrq-test-sample-review) t t)))
    (mrq-test-with-repo (root :review text :files '(("src/api/client.py" . "x\n")))
      (let ((file (expand-file-name "src/api/client.py" root))
            (count 0))
        (cl-letf (((symbol-function 'message)
                   (lambda (&rest _) (setq count (1+ count)))))
          (mrq-core-threads-for file)
          (mrq-core-threads-for file)
          (mrq-core-threads-for file))
        (should (= count 1))))))

(ert-deftest mrq-core-survives-a-corrupt-review-json ()
  "json 이 깨져도 에러를 올리지 않는다 — flymake 백엔드가 호출자다."
  (mrq-test-with-repo (root :review "{ not json" :files '(("a.py" . "x\n")))
    (let ((file (expand-file-name "a.py" root)))
      (cl-letf (((symbol-function 'message) (lambda (&rest _) nil)))
        (should (null (mrq-core-threads-for file)))))))

(ert-deftest mrq-core-caches-until-the-file-changes ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let* ((dir (mrq-core-review-dir (expand-file-name "src/api/client.py" root)))
           (first (mrq-core-review dir)))
      (should first)
      ;; 캐시 히트는 같은 객체여야 한다 — 매번 파싱하면 eq 가 깨진다
      (should (eq first (mrq-core-review dir))))))

(ert-deftest mrq-core-notices-two-consecutive-atomic-rewrites ()
  "`os.replace' 는 inode 를 바꾼다.  rename 교체를 **연달아** 따라가야 한다.

원시 inotify 라면 파일에 건 watch 가 첫 교체 뒤 죽는다.  Emacs 의
`file-notify-add-watch' 는 파일을 받아도 부모 디렉터리를 감시하므로 그 함정이
없지만(실측), 이 테스트는 그 보장이 깨지는 날을 위한 회귀 테스트다 —
한 번만 고쳐 보는 테스트로는 영영 못 본다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let* ((file (expand-file-name "src/api/client.py" root))
           (dir (mrq-core-review-dir file))
           (seen 0))
      (let ((mrq-core-refresh-functions (list (lambda (_) (setq seen (1+ seen))))))
        (mrq-core-review dir)                      ; watch 등록
        (dotimes (round 2)
          (let ((before seen)
                (text (replace-regexp-in-string
                       "\"title\": \"[^\"]*\""
                       (format "\"title\": \"round %d\"" round)
                       (mrq-test-sample-review) t t)))
            (mrq-test-write-review root 1234 text)
            (should (mrq-test-wait-for (lambda () (> seen before))))
            (should (equal (gethash "title" (mrq-core-review dir))
                           (format "round %d" round)))))
        (should (>= seen 2))))))

(ert-deftest mrq-core-watch-catches-a-review-json-created-later ()
  "첫 `pull' 이 json 을 만드는 순간도 디렉터리 watch 가 잡는다."
  (let ((dir (file-truename (make-temp-file "mrq-empty-" t)))
        (seen 0))
    (unwind-protect
        (let ((mrq-core-refresh-functions (list (lambda (_) (setq seen (1+ seen))))))
          (should (null (mrq-core-review dir)))     ; json 이 없다. watch 는 걸린다
          (write-region (mrq-test-sample-review) nil
                        (expand-file-name "review.json" dir) nil 'quiet)
          (should (mrq-test-wait-for (lambda () (> seen 0))))
          (should (mrq-core-review dir)))
      (mrq-core-forget-all)
      (delete-directory dir t))))

(provide 'mrq-core-test)
;;; mrq-core-test.el ends here
