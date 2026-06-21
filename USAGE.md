# USAGE.md — 실제로 어떻게 쓰나

HES 게이트 하네스를 실전에서 돌리는 3가지 방법, 그리고 규칙 수정과 다른 레포 이식, 스킬 파이프라인까지 복붙 가능한 명령어 중심으로 정리했다. 모든 명령은 프로젝트 루트에서 실행한다.

한 줄 요약: 컨벤션과 아키텍처를 어긴 코드가 파일에 닿기 전에(또는 커밋되기 전에) 막는다. Gate 1(grep)은 0 토큰으로 항상 동작하는 유일한 하드 게이트이고, Gate 2/3(LLM)은 기본 OFF이며 fail-open이다.

---

## 3가지 사용 모드 한눈에

| 모드 | 조건 | 켜는 법 | 막는 주체 |
|------|------------|---------|-----------|
| **A. Claude Code 안에서 (자동)** | Claude가 `Edit/Write/MultiEdit` 할 때 | 그냥 이 레포를 Claude Code로 연다 | `PreToolUse` 훅 |
| **B. git commit 마다 (자동)** | `git commit` 할 때 | `bash tools/install-git-hooks.sh` 1회 | pre-commit 훅 |
| **C. 배치 / CI / 수동 리뷰** | 직접 돌릴 때 | `python3 tools/hes_controller.py …` | 직접 호출 |

A와 B는 서로 독립이다. 둘 다 켜두면 Claude가 쓸 때 1번, 커밋할 때 2번 걸러진다.

---

## MODE A — Claude Code 안에서 (자동)

설정은 따로 없다. 이 레포를 Claude Code로 열기만 하면 된다. `.claude/settings.json`이 `PreToolUse` 훅(`matcher: Edit|Write|MultiEdit`)을 `.claude/hooks/router.sh`에 이미 연결해 두었다. 이후 Claude가 소스 파일을 쓸 때마다 쓰기 직전에 게이트가 자동으로 돈다. error 위반이 하나라도 있으면 `permissionDecision: "deny"`가 되어 그 쓰기는 물리적으로 일어나지 않는다.

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

`Edit` 페이로드는 `tool_input.new_string`을, `MultiEdit`는 `tool_input.edits[]`를 쓴다. 라우터가 세 형태 모두 처리한다.

로그는 `.claude/logs/gates.log`에 쌓인다(git 추적 제외). 게이트 결정과 fail-open 경고가 여기에 남는다.

```bash
tail -f .claude/logs/gates.log
```

---

## MODE B — git commit 마다 (Claude Code 밖에서)

Claude Code를 안 거치고 직접(또는 다른 에디터로) 커밋해도 막고 싶을 때 쓴다. 설치는 1회만 하면 된다.

```bash
# pre-commit 훅 설치 (최초 1회)
bash tools/install-git-hooks.sh
```

이후 `git commit` 할 때마다 훅이 `python3 tools/hes_controller.py --staged`를 돌리고, error 위반이 있으면 커밋을 BLOCK 한다.

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

훅 없이 컨트롤러를 직접 호출해 무엇이든 검사한다. 대상 지정 방식은 3가지다.

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

CI 게이트로 쓰려면 exit code 1을 실패로 받으면 된다.

샘플 출력은 깨끗한 파일(통과)과 위반 파일(차단)을 나란히 보여준다.

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

규칙의 진실의 원천은 `CONVENTIONS.md`의 ```` ```rule ```` 블록이다. 훅은 Markdown이 아니라 컴파일된 `.claude/cache/rules.json`을 읽으므로, 규칙을 바꾸면 반드시 다시 컴파일한다.

```bash
# CONVENTIONS.md 의 rule 블록을 수정한 뒤
python3 tools/parse_conventions.py     # → .claude/cache/rules.json 갱신
```

게이트 토글과 모드는 `.claude/config.json`에서 바꾼다.

- `"mode": "enforce"`는 error 위반 시 쓰기/커밋을 막는다.
- `"mode": "warn"`은 위반을 정보로만 출력하고 통과시킨다(새 규칙 점진 도입용).
- `"gates": { "gate2": { "enabled": true } }`는 Haiku 의미 게이트를 ON으로 둔다(≥50줄에서만 동작).
- `"gates": { "gate3": { "enabled": true } }`는 Sonnet 아키텍처 게이트를 ON으로 둔다(≥200줄에서만 동작).
- `"strict_whole_file": true`는 `forbid`/길이 규칙을 **변경 조각이 아니라 결과 파일 전체**에 적용한다(아래 「전체 파일 검사」). 기본 `false`.

`tools/`와 `tests/`는 `ignore_path_substrings`로 게이트 대상에서 제외돼 있다. CLI 도구가 정당하게 `print()`를 써도 막히지 않게 하기 위함이다. 이 매칭은 경로 **세그먼트** 기준이라 `src/mytools/x.py`처럼 `tools` 글자가 일부로 들어간 경로는 제외되지 않는다. 소스/무시 매칭은 대소문자를 가리지 않아 `FOO.PY`도 `*.py`로 본다.

### 전체 파일 검사 (`strict_whole_file`)

기본값(`false`)에서 Edit/MultiEdit의 `forbid`·길이 규칙은 **바뀐 조각만** 본다 — 그래서 이미 `print()`가 있는 파일이라도 무관한 줄은 그냥 편집할 수 있다(무회귀).

`true`로 켜면 Edit 시 디스크 내용에 변경을 적용한 **결과 파일 전체**를 검사한다. 멀티라인·기존 위반까지 잡지만, **이미 위반이 있는 파일은 그 위반을 먼저 고치기 전엔 무관한 줄 편집도 막힌다.** 더 엄격한 enforcement를 원할 때만 켠다.

> `require`(예: 모듈 docstring) 규칙은 이 값과 무관하게 **항상 결과 파일 전체**로 검사한다. 한 줄 Edit이 "docstring 없음"으로 오탐하던 문제를 막기 위함이다.

### AST 룰 (`match: ast`) — 정규식 오탐·누락 없애기

`forbid_pattern` 규칙에 `match: ast`와 `name: <함수명>`을 더하면, 그 호출을 정규식이 아니라 파이썬 `ast`로 검출한다. **`strict_whole_file: true`일 때만** 동작하며(전체 파일이 파싱돼야 하므로), 켜지면:

- 주석·문자열 안의 `print(` 같은 **오탐을 안 낸다**(정규식은 글자만 보고 잡는다).
- **멀티라인 호출**(`print(\n …\n)`)과 **단순 별칭**(`p = print; p(x)`)까지 잡는다.
- 속성 호출(`obj.print()`)은 정당한 메서드를 오탐하지 않으려고 일부러 제외한다.

`pattern`은 그대로 둔다 — strict가 아닐 때(변경 조각 검사)의 폴백 정규식으로 쓰인다. 파이썬 한정(`applies: *.py`)이며, 내용이 파싱되지 않으면 fail-open(정규식 폴백). 예시 rule 블록:

```
id: no-print
severity: error
applies: *.py
type: forbid_pattern
pattern: (^|[^a-zA-Z_.])print[[:space:]]*\(
match: ast
name: print
message: print() is forbidden — use the logging module
```

---

## 다른 레포에 이식하기 (예: iOS `ios-qube`)

언어와 무관하다. 글로브와 규칙만 바꾸면 된다.

```bash
# 1) 하네스 일습 복사
cp -R .claude tools CONVENTIONS.md ARCHITECTURE.md /path/to/ios-qube/

# 2) (대상 레포에서) source_globs 를 Swift 로 변경
#    .claude/config.json → "source_globs": ["*.swift"]
```

3) `CONVENTIONS.md`에 `applies: *.swift` rule 블록을 작성한다. 예를 들면 이렇다.

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

`settings.json`과 `router.sh`는 손댈 필요 없다. Gate 1이 0 토큰으로 Swift 규칙을 강제한다.

---

## 스킬 파이프라인 (Layer 2/3/4)

v9 메타프롬프트로 스킬 후보를 생성하고(Layer 2), 검증·정규화를 거쳐(Layer 3), HES 게이트와 사람 승인으로 통합(Layer 4)하는 흐름이다.

### 한 명령으로 (오케스트레이터)

```bash
# 생성 → 품질루프 → 검증 → AI리뷰 → 사람 게이트에서 정지 (dry-run; 아무것도 설치 안 함)
bash tools/skill_pipeline.sh "파이썬 파일 수정 시 import 정리하는 스킬"

# 검토 후 실제 설치 (--approve = Gate 4 사람 승인)
bash tools/skill_pipeline.sh "..." --approve
```

생성(Layer 2)은 `claude` CLI가 필요하고 fail-loud다. fail-open인 게이트와 달리, 모델 없이는 만들 게 없으므로 크게 실패한다. 생성 모델은 `--model`, `HES_V9_MODEL`, config `gates.gate3.model` 순으로 고른다.

### 단계별로

```bash
# 1) Layer 2 — 후보 생성 + 1차 품질루프 (비평→수정, 기본 2라운드)
python3 tools/v9_generate.py "<goal>" [--rounds N] [--out PATH]
#    → stderr 에 진행 로그, stdout 에 JSON 요약({"out": <후보 경로>, ...})

# 2) Layer 3 — 구조 검증·정규화만 따로 돌릴 때
python3 tools/skill_adapter.py <md>

# 3) Layer 4 — 통합 검증 (dry-run: verdict 만 보여주고 아무것도 설치 안 함)
bash tools/skill_integrate.sh <candidate.md>

# 4) 실제 설치 — 반드시 --approve 가 있어야만 설치됨 (사람 게이트 = Gate 4)
bash tools/skill_integrate.sh <candidate.md> --approve
```

`--approve` 없이는 어떤 스킬도 설치되지 않는다. 검증을 통과하지 못한(또는 사람이 승인하지 않은) 스킬이 시스템에 들어가는 경로는 없다.

### 메타프롬프트 자가개선 (Layer 2 — eval 이 닫는 루프)

v9 메타프롬프트(`tools/v9/meta_prompt.md`) 자체를 개선하는 루프다. 모델은 제안하고, 증거가 승격시키고, 사람이 서명한다.

```bash
# 1) 개선안 제안 — runs.jsonl 의 최근 실패(무효 후보·잔여 문제·반려된 통합)가
#    자동으로 프롬프트에 환류된다. 운영자 메모는 --feedback 으로 추가.
python3 tools/v9_improve.py [--feedback notes.md]
#    → tools/v9/meta_prompt.candidate.md

# 2) 증거 생산 — 고정 goal set(tools/v9/eval_goals.json)을 챔피언(현행)과
#    도전자(후보)로 재생해 결정론 신호(구조 유효율→잔여 문제→라운드)로 채점.
#    동점은 챔피언 유지. exit 0 = 도전자 승.
python3 tools/v9_eval.py [--goals FILE] [--rounds N]
#    → build/eval/verdict.json

# 3) 승격 — verdict 가 "도전자 승"일 때만 통과. 진 후보는 거부(--force 로만 우회),
#    verdict 가 없거나 후보가 바뀌어 stale 이면 경고 후 사람 판단에 맡긴다.
python3 tools/v9_improve.py --approve [--force]
#    → 구버전은 tools/v9/archive/ 보관, version 자동 +1
```

기록(텔레메트리)은 `.claude/logs/v9_runs.jsonl`(git 추적 제외, `HES_RUNS_FILE`로 변경 가능)에 한 줄 JSON으로 쌓인다. 생성·통합·eval·승격의 모든 결과가 여기 남는다. 이 데이터가 1번의 자동 환류와 2번의 채점을 가능하게 하는 루프의 연료다.

---

## 빠른 참조

```bash
bash tools/install-git-hooks.sh                              # B: 커밋 게이트 설치
python3 tools/hes_controller.py --staged                     # C: 스테이지 검사
python3 tools/hes_controller.py --range main..HEAD --json    # C: PR diff (CI)
python3 tools/parse_conventions.py                           # 규칙 재컴파일
bash tools/skill_pipeline.sh "<goal>" [--approve]            # 스킬 생성→통합 (Layer 2→4)
python3 tools/v9_improve.py                                  # 메타프롬프트 개선 제안 (실패 자동 환류)
python3 tools/v9_eval.py                                     # 챔피언 vs 도전자 eval (증거 생산)
python3 tools/v9_improve.py --approve                        # 이긴 후보만 승격
tail -f .claude/logs/v9_runs.jsonl                           # 루프 텔레메트리
git commit --no-verify                                       # B: 1회 우회
tail -f .claude/logs/gates.log                               # A: 로그
```
