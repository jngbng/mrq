;;; mrq-flymake.el --- MR 코멘트를 flymake 진단으로 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.1.  `flymake-goto-next-error' 가 그대로 "다음 MR 코멘트로
;; 이동" 이 되므로 별도 명령을 만들지 않는다.
;;
;; severity 는 `:note' 다 (MUST) — 컴파일 에러와 섞이면 사용자가 둘을 구별하지
;; 못하고, MR 코멘트가 빌드를 깬 것처럼 보인다.

;;; Code:

(require 'flymake)
(require 'subr-x)
(require 'mrq-anchor)
(require 'mrq-core)

;;;###autoload
(defun mrq-flymake-setup ()
  "이 버퍼에 mrq 백엔드를 걸고 `flymake-mode' 를 켠다."
  (interactive)
  (add-hook 'flymake-diagnostic-functions #'mrq-flymake-backend nil t)
  (add-hook 'mrq-core-refresh-functions #'mrq-flymake-refresh)
  (flymake-mode 1))

(defun mrq-flymake-backend (report-fn &rest _)
  "flymake 백엔드.  REPORT-FN 에 진단 리스트를 넘긴다."
  (funcall report-fn (mrq-flymake--diagnostics (current-buffer))))

(defun mrq-flymake--diagnostics (buffer)
  "BUFFER 의 진단 리스트."
  (with-current-buffer buffer
    (let ((file (buffer-file-name))
          (out nil))
      (when file
        (dolist (thread (mrq-core-threads-for file))
          (let ((diagnostic (mrq-flymake--one buffer thread)))
            (when diagnostic (push diagnostic out)))))
      (nreverse out))))

(defun mrq-flymake--one (buffer thread)
  "THREAD 하나를 BUFFER 의 진단으로.  띄우지 않을 조건이면 nil.

LOCAL 은 THREAD 의 `local' 해시테이블이다.

띄우지 않는 조건 넷 — `location' 이 없다(MUST, `mrq-core-threads-for' 가 이미
걸렀다), `confidence' 가 `stale' 이다(MUST), 처리된 상태다(SHOULD), 서버에서
resolve 됐고 내 미전송 작업이 없다.

`stale' 을 띄우지 않는 이유는 틀린 위치에 붙은 진단이 위치 신뢰를 잃는 가장
빠른 길이기 때문이다 (`data-model.md' §4.9).  뒤의 둘은 `mrq-show-handled' 가
함께 끈다."
  (let ((location (gethash "location" thread))
        (local (gethash "local" thread)))
    (when (and (not (equal (gethash "confidence" location) "stale"))
               (or mrq-show-handled
                   (and (equal (gethash "state" local) "todo")
                        (mrq-flymake--pending-p thread local))))
      (let* ((line (mrq-flymake--line buffer thread location))
             (end-line (mrq-flymake--end-line location line))
             (region (mrq-flymake--region buffer line end-line)))
        (when region
          (flymake-make-diagnostic
           buffer (car region) (cdr region) :note
           (mrq-flymake--text thread location)
           (gethash "id" thread)
           ;; overlay-properties 는 **alist** 다 (plist 가 아니다).  plist 를
           ;; 넘기면 flymake 가 wrong-type-argument 로 죽고, 그러면 이 백엔드가
           ;; 세션 내내 **disabled** 로 남아 진단이 조용히 사라진다.
           (list (cons 'mrq-thread-id (gethash "id" thread)))))))))

(defun mrq-flymake--pending-p (thread local)
  "THREAD(그 `local' 부분이 LOCAL)가 기본 보기에 남아야 하는가.

서버에서 resolve 됐는데 내 미전송 작업이 없으면 아니다 — `review-md.md' §5 와
`cli.md' §7 이 쓰는 것과 같은 규칙이다.  동료가 코멘트를 resolve 한 뒤에도
진단이 남으면 `review.md'/`mrq list' 와 flymake 가 서로 다른 집합을 보여준다
\(`decisions/0001-human-and-ai-are-peers.md')."
  (or (not (eq (gethash "resolved" (gethash "server" thread)) t))
      (not (string-empty-p (string-trim (or (gethash "reply" local) ""))))
      (not (equal (gethash "state" local) "todo"))))

(defun mrq-flymake--line (buffer thread location)
  "THREAD 의 LOCATION 이 가리키는 줄을 BUFFER 안에서 보정한다.

보정은 **저장하지 않은 버퍼에서만** 한다 (`reanchoring.md' §6).  저장된
버퍼의 위치는 CLI 가 git 으로 계산한 값이고 그쪽이 언제나 더 낫다 — git diff
hunk 맵과 context 점수를 쓸 수 있는 쪽은 CLI 뿐이다."
  (let ((line (gethash "line" location))
        (anchor (gethash "anchor" thread)))
    (with-current-buffer buffer
      (if (or (not (buffer-modified-p)) (not (hash-table-p anchor)))
          line
        (mrq-anchor-correct (mrq-flymake--buffer-lines)
                            (gethash "line" anchor)
                            line)))))

(defun mrq-flymake--buffer-lines ()
  "현재 버퍼를 1 행이 인덱스 0 인 문자열 벡터로."
  (vconcat (split-string (buffer-substring-no-properties (point-min) (point-max))
                         "\n")))

(defun mrq-flymake--end-line (location line)
  "LOCATION 의 끝 줄에 보정 delta 를 반영한다.  `line_end' 가 없으면 LINE.

멀티라인 코멘트의 span 을 잃지 않는다 — 보정이 `d' 줄 옮기면 끝 줄도 같은
`d' 만큼 옮긴다."
  (let ((raw (gethash "line" location))
        (end (gethash "line_end" location)))
    (if (and (numberp end) (numberp raw))
        (+ end (- line raw))
      line)))

(defun mrq-flymake--region (buffer line end-line)
  "BUFFER 의 LINE..END-LINE 을 (시작 . 끝) 로.  버퍼 범위로 clamp 한다.

버퍼가 줄면 `location.line' 이 버퍼 밖을 가리킨다.  CLI 는 디스크 파일만
보므로 이 경우를 모른다.  clamp 하지 않으면 진단이 조용히 사라진다.

`flymake-diag-region' 의 둘째 인자는 **끝 줄이 아니라 열(column)** 이다
\(`(buffer line &optional col)').  끝 줄을 거기 넘기면 멀티라인 코멘트가
엉뚱한 위치의 한 칸짜리 영역이 된다.  그래서 양 끝 줄에 각각 불러 두 영역을
잇는다 — 빈 줄 처리 같은 가장자리 규칙을 flymake 쪽에 맡길 수 있다."
  (with-current-buffer buffer
    (let* ((last (line-number-at-pos (point-max)))
           (start (max 1 (min line last)))
           (stop (max start (min end-line last)))
           (head (flymake-diag-region buffer start)))
      (when head
        (if (= start stop)
            head
          (let ((tail (flymake-diag-region buffer stop)))
            (if tail (cons (car head) (cdr tail)) head)))))))

(defun mrq-flymake--text (thread location)
  "THREAD 의 진단 메시지를 한 줄로 만든다.

루트 노트의 첫 줄을 자르고 LOCATION 으로 `[fuzzy]' 여부를 정한다."
  (let* ((root (car (gethash "notes" thread)))
         (author (and root (gethash "author" root)))
         (body (or (and root (gethash "body" root)) ""))
         (first-line (car (split-string body "\n"))))
    (concat "@" (or author "?") ": "
            (truncate-string-to-width first-line 70 nil nil "…")
            (if (equal (gethash "confidence" location) "fuzzy") " [fuzzy]" ""))))

;;;###autoload
(defun mrq-flymake-thread-at-point (&optional position)
  "POSITION(기본 `point')의 진단이 가리키는 thread id.  없으면 nil."
  (let ((diagnostics (flymake-diagnostics (or position (point)))))
    (and diagnostics (flymake-diagnostic-data (car diagnostics)))))

(defun mrq-flymake-refresh (dir)
  "DIR 의 리뷰를 보는 열린 버퍼 전체의 flymake 를 다시 돌린다.

`mrq-core-refresh-functions' 에 붙는다 — 사람과 AI 가 동시에 작업하므로
AI 가 `mrq reply' 로 json 을 고치는 동안 사용자의 버퍼가 갱신돼야 한다
\(`editor.md' §1-5)."
  (dolist (buffer (buffer-list))
    (with-current-buffer buffer
      (when (and buffer-file-name
                 (bound-and-true-p flymake-mode)
                 (memq #'mrq-flymake-backend flymake-diagnostic-functions)
                 (equal (mrq-core-review-dir buffer-file-name) dir))
        (flymake-start)))))

(provide 'mrq-flymake)
;;; mrq-flymake.el ends here
