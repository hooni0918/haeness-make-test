# USAGE.md — 실제로 어떻게 쓰나

HES 게이트 하네스를 **실전에서 돌리는 3가지 방법** + 규칙 수정 / 다른 레포 이식 / 스킬 파이프라인까지,
복붙 가능한 명령어 중심으로 정리했다. 모든 명령은 **프로젝트 루트**에서 실행한다.

> 한 줄 요약: 컨벤션·아키텍처를 어긴 코드가 **파일에 닿기 전에**(또는 **커밋되기 전에**) 막는다.
> Gate 1(grep)은 0 토큰, 항상 동작하는 유일한 하드 게이트. Gate 2/3(LLM)은 기본 OFF·fail-open.

---

## 3가지 사용 모드 한눈에

| 모드 | 언제 막히나 | 켜는 법 | 막는 주체 |
|------|------------|---------|-----------|
| **A. Claude Code 안에서 (자동)** | Claude가 `Edit/Write/MultiEdit` 할 때 | 그냥 이 레포를 Claude Code로 연다 | `PreToolUse` 훅 |
| **B. git commit 마다 (자동)** | `git commit` 할 때 | `bash tools/install-git-hooks.sh` 1회 | pre-commit 훅 |
| **C. 배치 / CI / 수동 리뷰** | 직접 돌릴 때 | `python3 tools/hes_controller.py …` | 직접 호출 |

A와 B는 서로 독립이다. 둘 다 켜두면 Claude가 쓸 때 1번, 커밋할 때 2번 걸러진다.

---

## MODE A — Claude Code 안에서 (자동)

**설정 0.** 이 레포를 Claude Code로 열기만 하면 된다. `.claude/settings.json`이 `PreToolUse` 훅
(`matcher: Edit|Write|MultiEdit`)을 `.claude/hooks/router.sh`에 이미 연결해 두었다.
이후 Claude가 소스 파일을 쓸 때마다 **쓰기 직전** 게이트가 자동으로 돈다.
error 위반이 하나라도 있으면 `permissionDecision: "deny"` → 그 쓰기는 **물리적으로 일어나지 않는다.**

### 수동 테스트 (Claude Code 없이 훅만 검증)

`jq`로 가짜 PreToolUse JSON을 만들어 라우터에 파이프하면 된다.

```bash
# 막히는 케이스 — src/calculator.py 에 print() 를 Write → deny
jq -nc \
  --arg fp "$PWD/src/calculator.py" \
  --arg c $'def divide(a, b):\n    print("debugging")\n    return a / b\n' \
  '{tool_name:"Write", tool_input:{file_path:$fp, content:$c}}' \
| bash .claude/hooks/router.sh
```

기대 출력:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked by HES gate: [no-print] print() is forbidden — use the logging module (line 2)"
  }
}
```

```bash
# 통과 케이스 — 깨끗한 코드 → 빈 출력(allow), exit 0
jq -nc \
  --arg fp "$PWD/src/calculator.py" \
  --arg c $'"""Calculator module."""\n\n\ndef divide(a, b):\n    return a / b\n' \
  '{tool_name:"Write", tool_input:{file_path:$fp, content:$c}}' \
| bash .claude/hooks/router.sh
```

> `Edit` 페이로드는 `tool_input.new_string`, `MultiEdit`는 `tool_input.edits[]` 를 쓴다. 라우터가 세 형태 모두 처리한다.

**로그:** 게이트 결정과 fail-open 경고는 `.claude/logs/gates.log` 에 쌓인다(git 추적 제외).

```bash
tail -f .claude/logs/gates.log
```

---

## MODE B — git commit 마다 (Claude Code 밖에서)

Claude Code를 안 거치고 직접(또는 다른 에디터로) 커밋해도 막고 싶을 때. **1회만 설치**한다.

```bash
# pre-commit 훅 설치 (최초 1회)
bash tools/install-git-hooks.sh
```

이후 `git commit` 할 때마다 훅이 `python3 tools/hes_controller.py --staged` 를 돌리고,
**error 위반이 있으면 커밋을 BLOCK** 한다.

```bash
git add src/calculator.py
git commit -m "add divide"
# error 위반 있으면 → 커밋 거부, 위반 목록 출력
```

### 한 번만 우회 / 완전 제거

```bash
# 이번 커밋만 게이트 건너뛰기
git commit --no-verify -m "wip"

# 훅 제거(언인스톨)
rm "$(git rev-parse --git-path hooks)/pre-commit"
```

---

## MODE C — 배치 / CI / 수동 리뷰

훅 없이 컨트롤러를 직접 호출해 무엇이든 검사한다. 대상 지정 방식 3가지:

```bash
# 1) 스테이징된 변경 (pre-commit 훅이 내부적으로 쓰는 것과 동일)
python3 tools/hes_controller.py --staged

# 2) 특정 파일들
python3 tools/hes_controller.py --files src/calculator.py src/foo.py

# 3) 커밋 범위 (CI에서 PR diff 검사할 때)
python3 tools/hes_controller.py --range main..HEAD
```

옵션:

```bash
# 머신 가독 JSON 출력 (CI 파싱용)
python3 tools/hes_controller.py --range main..HEAD --json

# LLM 게이트(Gate 2/3)까지 태워 의미·아키텍처 리뷰 포함
python3 tools/hes_controller.py --staged --ai-review
```

### 판정(verdict)과 종료 코드

| verdict | 의미 | exit code |
|---------|------|-----------|
| **APPROVED** | 위반 없음 | 0 |
| **REVIEW** | warn 위반만 있음 (커밋은 가능, 검토 권장) | 0 |
| **REJECTED** | error 위반 있음 | **1** |

> CI 게이트로 쓰려면 exit code 1 을 실패로 받으면 된다.

샘플 출력 — 깨끗한 파일(통과)과 위반 파일(차단):

```text
$ python3 tools/hes_controller.py --files src/calculator.py
OK   src/calculator.py

1 files checked (1 source), 0 errors, 0 warnings
VERDICT: APPROVED
$ echo $?
0

$ python3 tools/hes_controller.py --files src/bad_example.py   # print() 포함
---- src/bad_example.py
  error gate1  [no-print] print() is forbidden — use the logging module (line 2)
1 files checked (1 source), 1 errors, 0 warnings
VERDICT: REJECTED
$ echo $?
1
```

---

## 규칙 편집 (EDITING RULES)

규칙의 **진실의 원천은 `CONVENTIONS.md`** 의 ```` ```rule ```` 블록이다. 훅은 Markdown이 아니라
컴파일된 `.claude/cache/rules.json` 을 읽으므로, 규칙을 바꾸면 **반드시 다시 컴파일**한다.

```bash
# CONVENTIONS.md 의 rule 블록을 수정한 뒤
python3 tools/parse_conventions.py     # → .claude/cache/rules.json 갱신
```

게이트 토글 / 모드는 `.claude/config.json` 에서 바꾼다:

- `"mode": "enforce"` — error 위반 시 쓰기/커밋을 **막음**.
- `"mode": "warn"` — 위반을 **정보로만 출력**하고 통과(새 규칙 점진 도입용).
- `"gates": { "gate2": { "enabled": true } }` — Haiku 의미 게이트 ON (≥50줄에서만 동작).
- `"gates": { "gate3": { "enabled": true } }` — Sonnet 아키텍처 게이트 ON (≥200줄에서만 동작).

> `tools/` 와 `tests/` 는 `ignore_path_substrings` 로 게이트 대상에서 제외돼 있다.
> (CLI 도구가 정당하게 `print()` 를 써도 막히지 않게 하기 위함.)

---

## 다른 레포에 이식하기 (예: iOS `ios-qube`)

언어 무관 — 글로브와 규칙만 바꾸면 된다.

```bash
# 1) 하네스 일습 복사
cp -R .claude tools CONVENTIONS.md ARCHITECTURE.md /path/to/ios-qube/

# 2) (대상 레포에서) source_globs 를 Swift 로 변경
#    .claude/config.json → "source_globs": ["*.swift"]
```

3) `CONVENTIONS.md` 에 `applies: *.swift` rule 블록을 작성한다. 예:

- `forbid_pattern` on `\bprint\(` → "use `os.Logger`, not `print`"
- `forbid_pattern` on `as!|try!` → "force-cast / force-try 금지"
- `filename_pattern` → 뷰 파일은 `*View.swift` 로 끝나게
- `max_line_length` → SwiftLint 설정과 동일하게

```bash
# 4) 규칙 재컴파일
python3 tools/parse_conventions.py

# 5) (선택) git 커밋 게이트 설치
bash tools/install-git-hooks.sh
```

`settings.json` / `router.sh` 는 손댈 필요 없다. Gate 1 이 0 토큰으로 Swift 규칙을 강제한다.

---

## 스킬 파이프라인 (Layer 3/4)

v9 메타프롬프트가 만든 결과물을 **스킬 후보**로 변환하고, HES 게이트를 거쳐 통합하는 흐름이다.

```bash
# 1) 마크다운 → 스킬 후보로 변환
python3 tools/skill_adapter.py <md>

# 2) 통합 검증 (dry-run: verdict 만 보여주고 아무것도 설치 안 함)
bash tools/skill_integrate.sh <candidate.md>

# 3) 실제 설치 — 반드시 --approve 가 있어야만 설치됨 (사람 게이트 = Gate 4)
bash tools/skill_integrate.sh <candidate.md> --approve
```

> **`--approve` 없이는 어떤 스킬도 설치되지 않는다.** 검증을 통과하지 못한(또는 사람이 승인하지 않은)
> 스킬이 시스템에 들어가는 경로는 없다.

---

## 빠른 참조

```bash
bash tools/install-git-hooks.sh                              # B: 커밋 게이트 설치
python3 tools/hes_controller.py --staged                     # C: 스테이지 검사
python3 tools/hes_controller.py --range main..HEAD --json    # C: PR diff (CI)
python3 tools/parse_conventions.py                           # 규칙 재컴파일
git commit --no-verify                                       # B: 1회 우회
tail -f .claude/logs/gates.log                               # A: 로그
```
