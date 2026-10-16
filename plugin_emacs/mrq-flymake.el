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
  "flymake 백엔드.  REPORT-FN 에 진단 리스트를 넘긴다.

**에러를 밖으로 내보내지 않는다.**  내보내면 flymake 가 이 백엔드를 끄고
진단이 조용히 0 개가 되며, 이유는 flymake 로그에만 남는다 — 사용자에게는
\"댓글이 있는데 안 보인다\" 로만 보인다.  실제로 그렇게 당했다: 파일 하나만
재로드해 `mrq-message-width' 가 void 가 된 적이 있다.

대신 `*mrq*' 와 에코 영역에 **한 번** 알리고 빈 목록을 돌려준다.  숨기는 것이
아니라 더 눈에 띄는 곳으로 옮기는 것이고, 백엔드가 살아 있어 고친 뒤 바로
복구된다."
  (funcall report-fn
           (condition-case err
               (mrq-flymake--diagnostics (current-buffer))
             (error
              (mrq-core-warn-once
               (mrq-core-review-dir (buffer-file-name))
               (car err)
               (format "mrq: 진단을 만들지 못했습니다 — %s (M-x mrq-reload 로 전부 다시 읽어 보세요)"
                       (error-message-string err)))
              nil))))

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

띄우지 않는 조건 셋 — `location' 이 없다(MUST, `mrq-core-threads-for' 가 이미
걸렀다), `confidence' 가 `stale' 이다(MUST), **닫힌 스레드다**(SHOULD).

`stale' 을 띄우지 않는 이유는 틀린 위치에 붙은 진단이 위치 신뢰를 잃는 가장
빠른 길이기 때문이다 (`data-model.md' §4.9).  마지막 것은 `mrq-show-handled'
가 끈다."
  (let ((location (gethash "location" thread))
        (local (gethash "local" thread)))
    (when (and (not (equal (gethash "confidence" location) "stale"))
               (or mrq-show-handled
                   (mrq-flymake--open-p thread local)))
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

(defun mrq-flymake--open-p (thread local)
  "THREAD(그 `local' 부분이 LOCAL)가 기본 보기에 남아야 하는가.

**닫힌 것은 숨긴다 — 서버가 닫았든 내가 닫았든.  단 미전송 답글이 있으면
보인다.**

- 서버가 닫음: `server.resolved'
- 내가 닫음: `local.state' 가 `skipped'
- 미전송 답글: `local.reply' 가 비어 있지 않음.  `push' 가 성공해야 비우므로
  (`cli.md' §9) 이것이 \"아직 보낼 것이 있다\" 의 유일한 신호다.
  `local.state' 로는 가를 수 없다 — 보낸 뒤에도 `done' 으로 남는다

`state == \"todo\"' 만 보여 주던 예전 규칙은 `[~]'(답글만)과 `[x]'(미전송)를
소스 버퍼에서 지웠다.  `[~]' 는 `push' 가 resolve 하지 않으므로 서버에서
계속 열려 있는 대화이고, `[x]' 미전송은 아직 내가 보낼 것이 남은 상태다.

**`review.md' 와 한 줄 다르다** — 거기서는 `skipped' 도 보인다.  그 면은
결정을 **바꾸는** 곳이라 건너뛴 것을 숨기면 되돌릴 수가 없고, 소스 버퍼는
**남은 일**을 보는 곳이다 (`editor.md' §3.1)."
  (or (not (string-empty-p (string-trim (or (gethash "reply" local) ""))))
      (and (not (eq (gethash "resolved" (gethash "server" thread)) t))
           (not (equal (gethash "state" local) "skipped")))))

(defun mrq-flymake--line (buffer thread location)
  "THREAD 의 LOCATION 이 가리키는 줄을 BUFFER 안에서 보정한다.

**저장 여부를 보지 않는다.**  예전에는 저장하지 않은 버퍼에서만 보정했는데
\(`reanchoring.md' §6 의 원래 문구), 그 근거인 \"CLI 가 git 으로 계산한 값이 더
낫다\" 는 **디스크가 CLI 가 본 상태일 때만** 참이다.  저장하는 순간 그 전제가
깨지고 되돌릴 장치가 없어서, 보정이 가장 필요해지는 순간에 정확히 꺼졌다 —
편집 중에는 맞던 진단이 저장하는 순간 틀어졌다.

디스크가 CLI 가 본 그대로면 앵커는 이미 `location.line' 에 있고 보정은 같은
값을 돌려주거나(유일) 포기한다(모호) — 그 경우 무해하다.  큰 이동·파일 이동·
rename 은 여전히 CLI 의 git 매핑이 필요하고 `mrq-reanchor' 가 그것을 부른다."
  (let ((line (gethash "line" location))
        (anchor (gethash "anchor" thread)))
    (with-current-buffer buffer
      (if (not (hash-table-p anchor))
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

본문의 **줄바꿈과 연속 공백을 한 칸으로 접은 뒤** `mrq-message-width' 까지
자른다.  첫 줄에서 끊으면 \"첫 줄입니다.\" 같은 머리말만 보이고 정작 내용이
사라진다.

노트가 둘 이상이면 `답글 N' 을 덧붙인다 — 잘린 메시지만 보고 \"가서 읽을
값이 있나\" 를 판단할 수 있어야 한다.  전부 읽는 경로는 `C-c m r'(그 스레드의
`review.md' 블록)과 `flymake-show-buffer-diagnostics' 다.

LOCATION 으로 `[fuzzy]' 여부를 정한다."
  (let* ((notes (gethash "notes" thread))
         (root (and (> (length notes) 0) (elt notes 0)))
         (author (or (and root (gethash "author" root)) "?"))
         (body (or (and root (gethash "body" root)) ""))
         (replies (max 0 (1- (length notes))))
         (head (concat "@" author ": "))
         (tail (concat (if (> replies 0) (format "  (답글 %d)" replies) "")
                       (if (equal (gethash "confidence" location) "fuzzy")
                           " [fuzzy]" "")))
         (room (max 16 (- (or mrq-message-width (1- (frame-width)))
                          (string-width head) (string-width tail)))))
    (concat head
            (truncate-string-to-width (mrq-flymake--one-line body) room nil nil "…")
            tail)))

(defun mrq-flymake--one-line (text)
  "TEXT 의 줄바꿈과 연속 공백을 한 칸으로 접는다."
  (string-trim (replace-regexp-in-string "[ \t\n\r]+" " " text)))

;;;###autoload
(defun mrq-flymake-thread-at-point (&optional position)
  "POSITION(기본 `point')의 진단이 가리키는 thread id.  없으면 nil.

point 에 걸린 것이 없으면 **그 줄 전체**에서 찾는다.  진단 영역은 첫 비공백에서
시작하는데(`flymake-diag-region') 소스 코드는 들여쓰기가 있는 것이 보통이라,
줄 맨 앞에서 부르면 아무것도 못 찾았다.  반대 방향(`review.md' -> 소스)은 줄
맨 앞으로 보내므로 동작이 쌍이 맞지 않았다."
  (let* ((at (or position (point)))
         (diagnostics
          (or (flymake-diagnostics at)
              (save-excursion
                (goto-char at)
                (flymake-diagnostics (line-beginning-position)
                                     (line-end-position))))))
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
