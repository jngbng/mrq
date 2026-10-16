;;; mrq-anchor.el --- 저장 안 된 버퍼의 앵커 보정 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `docs/spec/reanchoring.md' §6 의 범위 그대로다.  에디터가 할 수 있는 보정은
;; 이것뿐이고, 앵커 보정을 구현하는 모든 구현(`plugin_emacs', `plugin_vscode')이
;; `testdata/conformance/anchor.json' 으로 같게 동작하는 것을 강제당한다.
;;
;; CLI 의 `mrq.search' 와 **일부러 다른 알고리즘**이다.  CLI 는 창 50 + context
;; 점수 + 전체 파일 fallback 을 쓴다.  여기서는 창 200, exact -> strip, 후보가
;; 유일할 때만 채택한다.  창을 넓힌 것은 저장 안 된 버퍼가 세션 중에 많이
;; 움직이기 때문이고, 나머지를 좁힌 것은 두 언어로 복제되는 코드라 어긋날
;; 여지를 줄여야 하기 때문이다.
;;
;; 이 파일은 Emacs 내장 외에 아무것도 require 하지 않는다.  버퍼도 파일도
;; `review.json' 도 모른다 — 그래서 적합성 테이블이 순수 단위 테스트가 된다.

;;; Code:

(require 'subr-x)

(defconst mrq-anchor-window 200
  "`location.line' 에서 앞뒤로 몇 줄까지 보는가.  `reanchoring.md' §6.")

(defun mrq-anchor-correct (lines anchor-line location-line)
  "LINES 안에서 ANCHOR-LINE 을 찾아 보정된 줄 번호를 돌려준다.

LINES 는 1 행이 인덱스 0 인 문자열 벡터다.  LOCATION-LINE 은 1-indexed
검색 시작점이며, 보정하지 않기로 하면 그대로 돌려준다.

후보가 **유일할 때만** 채택한다 (MUST).  ANCHOR-LINE 완전 일치를 먼저 보고,
완전 일치가 **한 건도 없을 때만** `string-trim' 일치로 내려간다 — 완전 일치가
여럿이면 더 느슨한 비교로 내려가 봐야 후보가 늘기만 한다.

ANCHOR-LINE 이 공백뿐이면 완전 일치만 본다.  빈 줄 주변은 또 빈 줄이라 trim
비교가 근거를 잃는다 — CLI 의 `mrq.search' 가 같은 결정을 한다.

창은 양끝을 포함하고 버퍼 범위로 clamp 한다.  창이 버퍼와 겹치지 않으면
\(버퍼가 줄어 LOCATION-LINE 이 한참 밖인 경우) 보정하지 않는다."
  (if (or (null anchor-line) (null location-line))
      location-line
    (let ((lo (max 1 (- location-line mrq-anchor-window)))
          (hi (min (length lines) (+ location-line mrq-anchor-window))))
      (if (> lo hi)
          location-line
        (let ((exact (mrq-anchor--matches
                      lines lo hi (lambda (text) (equal text anchor-line)))))
          (cond
           ((string-empty-p (string-trim anchor-line))
            (if (= (length exact) 1) (car exact) location-line))
           ((= (length exact) 1) (car exact))
           ;; exact 가 둘 이상이면 여기서 끝낸다.  **이 가지는 결과를 바꾸지
           ;; 않는다** — 공백뿐이 아닌 앵커에서 strip 일치 집합은 exact 일치
           ;; 집합을 항상 포함하므로, |exact| >= 2 면 |strip| >= 2 이고 아래
           ;; 분기도 LOCATION-LINE 을 돌려준다.  의도를 코드에 남기려고 두지만,
           ;; 적합성 테이블이 이 줄의 유무를 **구별하지 못한다**(실측).
           ;; 뒤집어 말하면 두 번째 구현이 이 점에서 어긋날 수 없다.
           (exact location-line)
           (t
            (let* ((target (string-trim anchor-line))
                   (stripped (mrq-anchor--matches
                              lines lo hi
                              (lambda (text) (equal (string-trim text) target)))))
              (if (= (length stripped) 1) (car stripped) location-line)))))))))

(defun mrq-anchor--matches (lines lo hi predicate)
  "LINES 의 LO..HI(1-indexed, 양끝 포함)에서 PREDICATE 를 만족하는 줄 번호들."
  (let ((found nil)
        (line hi))
    (while (>= line lo)
      (when (funcall predicate (aref lines (1- line)))
        (push line found))
      (setq line (1- line)))
    found))

(provide 'mrq-anchor)
;;; mrq-anchor.el ends here
