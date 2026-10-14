;;; mrq-flymake-test.el --- flymake 백엔드 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.1 의 필터 규칙, 버퍼 내 보정, 버퍼 범위 clamp.
;;
;; `rendered.json' 의 `src/api/client.py' 스레드 셋이 가시성 세 경우를 다 덮는다:
;;   a1b2c3d4e5f6  todo  답글없음  미resolve  -> 기본에서 보인다
;;   d4e5f6a1b2c3  done  답글있음  resolve    -> 처리됨이라 기본에서 숨김
;;   e5f6a1b2c3d4  todo  답글없음  resolve    -> 동료가 resolve 해서 숨김

;;; Code:

(require 'ert)
(require 'mrq-flymake)
(require 'mrq-test-helper)

(defun mrq-flymake-test--settle ()
  "진단이 준비될 때까지 기다린다.

`mrq-flymake-backend' 는 **동기**라 `flymake-start' 가 돌아온 시점에 이미
보고를 마쳤다.  `flymake-running-backends' 를 폴링하면 안 된다 — 동기
백엔드는 flymake 가 \"running\" 으로 등록하기 **전에** 보고해 버려서 그
리스트가 비지 않고, 같은 버퍼의 `python-flymake' 는 체커가 없는 환경에서
영영 끝나지 않는다.  둘 다 실측으로 확인했다."
  nil)

(defun mrq-flymake-test--diagnostics (file)
  "FILE 을 열어 flymake 를 돌리고 진단 리스트를 돌려준다."
  (with-current-buffer (find-file-noselect file)
    (mrq-flymake-setup)
    (flymake-start nil t)
    (mrq-flymake-test--settle)
    (flymake-diagnostics)))

(defun mrq-flymake-test--ids (file)
  "FILE 의 진단이 가리키는 thread id 들."
  (mapcar #'flymake-diagnostic-data (mrq-flymake-test--diagnostics file)))

(ert-deftest mrq-flymake-shows-only-unhandled-by-default ()
  (mrq-test-with-repo (root :files (list (cons "src/api/client.py"
                                           (mrq-flymake-test--lines 320))))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/client.py" root))))
      (should (= (length diags) 1))
      (should (eq (flymake-diagnostic-type (car diags)) :note))
      (should (equal (flymake-diagnostic-data (car diags)) "a1b2c3d4e5f6")))))

(ert-deftest mrq-flymake-hides-a-thread-a-colleague-resolved ()
  "`review.md' 와 `mrq list' 가 감추는 것을 flymake 도 감춘다.

`e5f6a1b2c3d4' 는 서버에서 resolve 됐고 내 미전송 작업이 없다.  띄우면 사람이
보는 세 면이 서로 다른 집합을 보여준다 (`decisions/0001')."
  (mrq-test-with-repo (root :files (list (cons "src/api/client.py"
                                           (mrq-flymake-test--lines 320))))
    (should-not (member "e5f6a1b2c3d4"
                        (mrq-flymake-test--ids
                         (expand-file-name "src/api/client.py" root))))))

(ert-deftest mrq-flymake-keeps-a-resolved-thread-that-has-unsent-work ()
  "`d4e5f6a1b2c3' 는 resolve 됐지만 답글이 남아 있다 — `--all' 집합에는 있다.

동료가 먼저 resolve 했을 때 내 답글이 조용히 사라지면 안 된다
\(`review-md.md' §5 의 예외와 같은 근거)."
  (mrq-test-with-repo (root :files (list (cons "src/api/client.py"
                                           (mrq-flymake-test--lines 320))))
    (let ((mrq-show-handled t))
      (should (member "d4e5f6a1b2c3"
                      (mrq-flymake-test--ids
                       (expand-file-name "src/api/client.py" root)))))))

(ert-deftest mrq-flymake-shows-handled-when-asked ()
  (mrq-test-with-repo (root :files (list (cons "src/api/client.py"
                                           (mrq-flymake-test--lines 320))))
    (let ((mrq-show-handled t))
      (should (= (length (mrq-flymake-test--diagnostics
                          (expand-file-name "src/api/client.py" root)))
                 3)))))

(ert-deftest mrq-flymake-skips-stale-threads ()
  "`editor.md' §3.1 MUST — `stale' 에는 진단을 띄우지 않는다.

틀린 위치에 붙은 진단이 위치 신뢰를 잃는 가장 빠른 길이다."
  (mrq-test-with-repo (root :files '(("src/api/legacy.py" . "a\nb\n")))
    (should (null (mrq-flymake-test--diagnostics
                   (expand-file-name "src/api/legacy.py" root))))))

(ert-deftest mrq-flymake-skips-stale-even-with-show-handled ()
  "`stale' 은 MUST 라 `mrq-show-handled' 로도 켜지지 않는다."
  (mrq-test-with-repo (root :files '(("src/api/legacy.py" . "a\nb\n")))
    (let ((mrq-show-handled t))
      (should (null (mrq-flymake-test--diagnostics
                     (expand-file-name "src/api/legacy.py" root)))))))

(ert-deftest mrq-flymake-marks-fuzzy-in-the-message ()
  (mrq-test-with-repo (root :files '(("src/api/session.py" . "a\nb\nc\n")))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/session.py" root))))
      (should (= (length diags) 1))
      (should (string-match-p "\\[fuzzy\\]" (flymake-diagnostic-text (car diags)))))))

(ert-deftest mrq-flymake-message-starts-with-the-author ()
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "a\nb\nc\n")))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/retry.py" root))))
      (should (string-match-p "\\`@" (flymake-diagnostic-text (car diags))))
      ;; 한 줄이다 — 루트 노트의 첫 줄만 쓴다
      (should-not (string-match-p "\n" (flymake-diagnostic-text (car diags)))))))

(ert-deftest mrq-flymake-clamps-a-line-past-the-end-of-the-buffer ()
  "버퍼가 줄면 `location.line' 이 버퍼 밖을 가리킨다.

CLI 는 디스크 파일만 보므로 이 경우를 모른다.  clamp 하지 않으면
`flymake-diag-region' 이 nil 을 돌려주고 진단이 조용히 사라진다."
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "a\n")))
    (let* ((file (expand-file-name "src/api/retry.py" root))
           (diags (mrq-flymake-test--diagnostics file)))
      (should (= (length diags) 1))
      (with-current-buffer (find-file-noselect file)
        (should (<= (flymake-diagnostic-end (car diags)) (point-max)))))))

(ert-deftest mrq-flymake-spans-a-multiline-comment ()
  "`f6a1b2c3d4e5' 는 location.line 14, line_end 18 이다.

`flymake-diag-region' 의 둘째 인자는 끝 줄이 아니라 **열**이라, 거기에 끝 줄을
넘기면 멀티라인 코멘트가 엉뚱한 자리의 한 칸짜리 영역이 된다.  R6 이 되살린
span 을 그렇게 잃는다."
  (mrq-test-with-repo (root :files (list (cons "src/api/retry.py"
                                               (mrq-flymake-test--lines 40))))
    (let* ((file (expand-file-name "src/api/retry.py" root))
           (diag (car (mrq-flymake-test--diagnostics file))))
      (with-current-buffer (find-file-noselect file)
        (should (= (line-number-at-pos (flymake-diagnostic-beg diag)) 14))
        (should (= (line-number-at-pos (flymake-diagnostic-end diag)) 18))))))

(ert-deftest mrq-flymake-makes-one-diagnostic-per-thread-on-the-same-line ()
  "합치지 않는다 (`editor.md' §3.1)."
  (mrq-test-with-repo (root :review (mrq-flymake-test--with-twin)
                            :files '(("src/api/retry.py" . "a\nb\nc\n")))
    (should (= (length (mrq-flymake-test--diagnostics
                        (expand-file-name "src/api/retry.py" root)))
               2))))

(ert-deftest mrq-flymake-corrects-the-line-in-a-modified-buffer ()
  "`reanchoring.md' §6 — 저장하지 않은 버퍼에서만 보정한다.

`f6a1b2c3d4e5' 의 앵커 줄을 한 번만 두고 그 위에 두 줄을 끼운다.  보정이
없으면 진단이 원래 줄에 남는다."
  (let ((anchor (mrq-flymake-test--anchor-line "f6a1b2c3d4e5"))
        (line (mrq-flymake-test--location-line "f6a1b2c3d4e5")))
    (mrq-test-with-repo (root :files (list (cons "src/api/retry.py"
                                                 (mrq-flymake-test--filler line anchor))))
      (let ((file (expand-file-name "src/api/retry.py" root)))
        (with-current-buffer (find-file-noselect file)
          (goto-char (point-min))
          (insert "\n\n")                      ; 두 줄 밀고 modified 로 만든다
          (should (buffer-modified-p))
          (mrq-flymake-setup)
          (flymake-start nil t)
          (mrq-flymake-test--settle)
          (let ((diags (flymake-diagnostics)))
            (should (= (length diags) 1))
            (should (= (line-number-at-pos (flymake-diagnostic-beg (car diags)))
                       (+ line 2))))
          (set-buffer-modified-p nil))))))

(ert-deftest mrq-flymake-does-not-correct-a-saved-buffer ()
  "저장된 버퍼의 위치는 CLI 가 git 으로 계산한 값이고 그쪽이 언제나 더 낫다."
  (let ((anchor (mrq-flymake-test--anchor-line "f6a1b2c3d4e5"))
        (line (mrq-flymake-test--location-line "f6a1b2c3d4e5")))
    ;; 앵커를 **다른 줄**에 두고 저장된 상태로 연다.  보정하면 그 줄로 가고,
    ;; 보정하지 않으면 location.line 에 남는다.
    (mrq-test-with-repo (root :files (list (cons "src/api/retry.py"
                                                 (mrq-flymake-test--filler
                                                  (+ line 3) anchor))))
      (let* ((file (expand-file-name "src/api/retry.py" root))
             (diags (mrq-flymake-test--diagnostics file)))
        (should (= (length diags) 1))
        (with-current-buffer (find-file-noselect file)
          (should (= (line-number-at-pos (flymake-diagnostic-beg (car diags)))
                     line)))))))

;;; 픽스처 조작 — 테스트 파일이므로 json-parse 금지 규칙의 대상이 아니다
;;; (`mrq-boundary-test.el' 은 plugin_emacs/*.el 소스만 본다).

(defun mrq-flymake-test--thread (id)
  "`rendered.json' 에서 ID 스레드의 해시테이블."
  (let ((review (json-parse-string (mrq-test-sample-review) :array-type 'list)))
    (seq-find (lambda (th) (equal (gethash "id" th) id))
              (gethash "threads" review))))

(defun mrq-flymake-test--anchor-line (id)
  "ID 스레드의 `anchor.line'."
  (gethash "line" (gethash "anchor" (mrq-flymake-test--thread id))))

(defun mrq-flymake-test--location-line (id)
  "ID 스레드의 `location.line'."
  (gethash "line" (gethash "location" (mrq-flymake-test--thread id))))

(defun mrq-flymake-test--lines (n)
  "N 줄짜리 버퍼 내용.  줄마다 번호가 달라 영역이 겹치지 않는다."
  (let ((out nil))
    (dotimes (i n) (push (format "line %d" (1+ i)) out))
    (concat (string-join (nreverse out) "\n") "\n")))

(defun mrq-flymake-test--filler (at text)
  "AT 번째 줄(1-indexed)만 TEXT 이고 나머지는 `pass' 인 버퍼 내용."
  (let ((lines nil))
    (dotimes (i (+ at 5))
      (push (if (= (1+ i) at) text "pass") lines))
    (concat (string-join (nreverse lines) "\n") "\n")))

(defun mrq-flymake-test--with-twin ()
  "`f6a1b2c3d4e5' 를 같은 위치에 복제한 `review.json' 문자열.

`:array-type' 을 기본값(벡터)으로 둔다 — `json-serialize' 는 리스트를 배열로
내보내지 못하고 plist/alist 로 해석하려다 죽는다."
  (let* ((review (json-parse-string (mrq-test-sample-review)))
         (threads (append (gethash "threads" review) nil))
         (original (seq-find (lambda (th) (equal (gethash "id" th) "f6a1b2c3d4e5"))
                             threads))
         (twin (copy-hash-table original)))
    (puthash "id" "f6a1b2c3d4ff" twin)
    (puthash "root_note_id" 999999 twin)
    ;; 같은 줄의 **다른** 사람.  내용까지 같으면 flymake 가 같은 영역·타입·
    ;; 텍스트의 오버레이를 하나로 합쳐, 우리가 둘을 만들었는지 알 수 없다.
    (let ((note (copy-hash-table (aref (gethash "notes" twin) 0))))
      (puthash "author" "park" note)
      (puthash "body" "여기도 한 줄 더 봅시다." note)
      (puthash "notes" (vector note) twin))
    (puthash "threads" (vconcat threads (list twin)) review)
    (json-serialize review)))

(provide 'mrq-flymake-test)
;;; mrq-flymake-test.el ends here
