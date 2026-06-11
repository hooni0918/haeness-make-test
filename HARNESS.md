# HARNESS.md — 운영자 가이드

Claude Code와 소스 트리 사이에 끼어 있는 **계층형 게이트 강제 집행 하네스**다.
Claude가 소스 파일을 `Edit`, `Write`, `MultiEdit` 하려고 할 때마다 **PreToolUse 훅**이
*제안된* 내용을 **디스크에 쓰이기 전에** 가로채서 게이트 사다리에 태운다. 하드(error 등급)
위반이면 훅이 쓰기를 **DENY** 하고, Claude는 그 파일에 손도 못 댄다.

이건 Claude↔OS 강제 집행 레이어다. 규칙은 레포 안에 살고, OS가 훅으로 그걸 돌리며,
모델이 뭘 의도하든 *모든* 편집에 적용된다.

---

## 4단 게이트 사다리 (토큰을 아끼는 이유)

변경은 점점 비싸지는 게이트를 차례로 지난다. 싼 게이트가 먼저 돌아 위반 대부분을 잡으니,
비싼 게이트는 어쩌다 한 번 돈다.

| Gate | Engine | Cost | Catches | When it runs |
|------|--------|------|---------|--------------|
| **Gate 1** | 순수 셸 / `grep` vs `rules.json` | **0 tokens** | 기계적 규칙: 금지패턴(예: `print()`), 필수패턴(예: 모듈 docstring), 파일명 컨벤션, 최대 줄길이 | **항상** |
| **Gate 2** | diff에 **Haiku** | ~300 tokens | 정규식이 못 보는 의미적 냄새(네이밍 의도, 빤히 보이는 로직 실수) | 변경 **≥ 50 lines** *그리고* 활성화 시 |
| **Gate 3** | diff + `ARCHITECTURE.md`에 **Sonnet** | higher | 구조 드리프트(레이어링, 경계, 결합) | 변경 **≥ 200 lines** *그리고* 활성화 시 |
| **Gate 4** | **사람** | — | 기계가 못 정하는 모든 것 | 이 하네스의 범위 밖 |

**토큰 근거:** 편집 대부분은 작고, Gate 1이 **0토큰**으로 끝까지 판정한다.
큰 변경만 LLM 게이트 비용을 치르고, 그마저도 diff/내용만 보낸다 — 레포 전체는 절대 안 보낸다.
Sonnet(Gate 3)은 아키텍처 리뷰가 실제로 중요한 큰 구조 변경에만 쓴다.

**하드 보장은 Gate 1뿐이다.** Gate 2와 3은 **fail-open**이다. 꺼져 있거나, 변경이 크기
임계값 아래거나, `claude` CLI가 없거나, 모델 호출이 에러/타임아웃 나면 위반을 **하나도** 내지
않고 변경이 그대로 진행된다(경고만 로그에 남는다). 이들은 보호를 *더할* 뿐, Gate 1의 보호를
빼앗지 못한다.

**단락(short-circuit).** `enforce` 모드에서는 더 싼 게이트가 이미 `error` 위반을 냈으면
결정이 DENY 로 정해진 것이므로 LLM 게이트(2/3)를 **건너뛴다** — 사다리는 첫 실패 단에서
멈춘다(토큰 0 추가). `warn` 모드는 아무것도 막지 않으므로, 정보 요약이 온전하도록 켜진
게이트를 전부 돌린다. 배치 컨트롤러(`tools/hes_controller.py`)도 같은 단락 규칙을 따른다.

---

## 흐름

```
Claude proposes an Edit/Write/MultiEdit
            │
            ▼
   PreToolUse hook  ──►  .claude/hooks/router.sh   (reads stdin JSON once)
            │
            ▼
        gate1-shell.sh        (always; 0 tokens)
            │
            ▼
   change ≥ 50 lines AND gate2 enabled?  ──► gate2-semantic.sh   (Haiku, fail-open)
            │
            ▼
   change ≥ 200 lines AND gate3 enabled? ──► gate3-architect.sh  (Sonnet, fail-open)
            │
            ▼
   any error-severity violation?
        ├─ yes ─►  DENY   (emit deny JSON; write is blocked)
        └─ no  ─►  ALLOW  (silent in enforce mode; warnings printed in warn mode)
```

라우터는 게이트마다 위반 줄(파이프 구분 `severity|gate|message`)을 모은 뒤 결정한다.
**`error`가 하나라도 있으면 deny**, 아니면 allow다(`warn` 줄은 정보로 띄운다).

---

## 파일 맵

| Path | Purpose |
|------|---------|
| `.claude/settings.json` | `PreToolUse` 훅(`matcher: Edit\|Write\|MultiEdit`)을 `bash .claude/hooks/router.sh`에 연결한다. |
| `.claude/config.json` | 게이트 토글, 크기 임계값, source glob, `mode`(`enforce`\|`warn`). |
| `.claude/cache/rules.json` | `CONVENTIONS.md`를 컴파일한 기계가독 규칙. Gate 1이 읽는다. |
| `.claude/logs/.gitkeep` | logs 디렉토리를 git에 남기려는 용도. 실제 `*.log` 파일은 gitignore된다. |
| `.claude/logs/gates.log` | 게이트 결정과 경고의 런타임 로그(git 추적 제외). |
| `.claude/hooks/lib/common.sh` | 공용 헬퍼(`hes_root`, `hes_log`, `hes_deny`, `hes_allow`, `hes_inform`, `hes_basename_match`). 라우터와 게이트가 source 한다. |
| `.claude/hooks/router.sh` | **단일 진입점.** PreToolUse JSON을 stdin에서 한 번 읽고, 게이트를 돌리고, 결정 딱 하나를 emit 한다. |
| `.claude/hooks/gate1-shell.sh` | Gate 1: `rules.json` 대조 grep 검사(0토큰). |
| `.claude/hooks/gate2-semantic.sh` | Gate 2: diff에 Haiku(가드, fail-open). |
| `.claude/hooks/gate3-architect.sh` | Gate 3: Sonnet 아키텍처 리뷰(가드, fail-open). |
| `tools/parse_conventions.py` | `CONVENTIONS.md` → `.claude/cache/rules.json` 컴파일. |
| `CONVENTIONS.md` | 사람이 읽는 컨벤션 **더하기** 기계가 파싱하는 rule 블록. |
| `ARCHITECTURE.md` | 아키텍처 문서. Gate 3이 컨텍스트로 읽는다. |
| `HARNESS.md` | 이 운영자 가이드. |

---

## 3대 핵심 원칙

1. **규칙은 한 번만 파싱해 캐시로.** `CONVENTIONS.md`가 사람용 진실의 원천이고,
   `tools/parse_conventions.py`가 이걸 `.claude/cache/rules.json`으로 컴파일한다.
   훅은 매 편집마다 컴파일된 캐시만 읽는다 — 산문 재파싱도, 기계적 검사를 위한 LLM 비용도 없다.
2. **LLM 게이트엔 diff/내용만 보낸다.** Gate 2와 3은 레포 전체를 절대 안 본다 — 제안된 새 코드
   (그리고 Gate 3은 `ARCHITECTURE.md`)만 본다. 그래서 호출 하나가 수백 토큰에 머문다.
3. **게이트는 변경 규모로 고른다.** 작은 변경은 공짜 Gate 1에서 멈춘다. Gate 2(Haiku)는 변경된
   줄이 ≥ 50일 때만, Gate 3(Sonnet)은 ≥ 200일 때만 돈다. 변경이 그만큼 커야 LLM 비용을 치른다.

---

## 쓰는 법

### 1. 컨벤션을 고치고, 규칙 캐시를 새로 굽는다
`CONVENTIONS.md`의 rule 블록을 고친 뒤 캐시를 다시 컴파일한다:

```bash
python3 tools/parse_conventions.py
```

이러면 `.claude/cache/rules.json`이 다시 생성된다. Gate 1은 다음 편집부터 새 규칙을 집는다.
**`CONVENTIONS.md`를 바꿨으면 반드시 이걸 다시 돌려라** — 훅은 Markdown이 아니라 캐시를 읽는다.

### 2. LLM 게이트를 토글한다
`.claude/config.json`을 고쳐 Gate 2 / Gate 3을 켜거나 끄고, 크기 임계값을 조정하고,
강제 집행 모드를 고른다:

- 게이트별 `enabled: true|false` — 끄면 그 게이트를 통째로 건너뛴다(fail-open).
- `mode: "enforce"` — error 등급 위반이 쓰기를 **막는다**.
- `mode: "warn"` — 위반을 모델에게 **정보로 출력**하되 쓰기는 **허용한다**(흐름을 깨지 않고 새
  규칙을 점진 도입할 때 좋다).

### 3. 로그를 읽는다
게이트 결정과 fail-open 경고는 다음에 쌓인다:

```
.claude/logs/gates.log
```

형식: `<timestamp> | <gate> | <level> | <message>`. 이 파일은 gitignore되고,
디렉토리는 `.gitkeep`으로 유지한다.

---

## 수동 테스트 방법

하네스를 굴려보는 데 Claude Code가 돌고 있을 필요는 없다 — 가짜 PreToolUse JSON 객체를 라우터에
파이프하면 된다. 따옴표가 늘 유효하도록 JSON은 `jq`로 만든다. 아래는 **프로젝트 루트**에서 실행한다.

### A) DENY 되어야 하는 변경 (`print()` 포함)

```bash
jq -nc \
  --arg fp "$PWD/src/calculator.py" \
  --arg c $'def divide(a, b):\n    print("debugging")\n    return a / b\n' \
  '{tool_name:"Write", tool_input:{file_path:$fp, content:$c}}' \
| bash .claude/hooks/router.sh
```

기대 출력 — deny 결정이다. 사유는 `Blocked by HES gate: ` 뒤에 각 error 규칙의 `message`를
붙여 만든다(내부 `error|gate1|…` 파이프 인코딩은 벗겨져 여기 나타나지 않는다):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked by HES gate: [no-print] print() is forbidden — use the logging module (line 2)"
  }
}
```

Claude Code가 이걸 받으면 쓰기가 **막힌다**.

### B) ALLOW 되어야 하는 깨끗한 변경

```bash
jq -nc \
  --arg fp "$PWD/src/calculator.py" \
  --arg c $'"""Calculator module."""\n\n\ndef divide(a, b):\n    return a / b\n' \
  '{tool_name:"Write", tool_input:{file_path:$fp, content:$c}}' \
| bash .claude/hooks/router.sh
```

기대: **출력 없음, 종료 코드 0**(조용한 allow). `warn` 모드에서는 JSON 대신 평문 경고가 보일 수
있지만 쓰기는 그대로 진행된다.

> Tip: `Edit` 페이로드는 `tool_input.content` 대신 `tool_input.new_string`(과 `old_string`)을
> 쓴다. `MultiEdit` 페이로드는 `tool_input.edits[]`(`{old_string,new_string}` 배열)을 쓴다.
> 라우터가 세 형태를 모두 처리한다.

---

## iOS / Swift 지원 (구현됨)

하네스는 언어를 안 가린다 — 파일 glob과 정규식 규칙만 본다. 그래서 같은 Layer-0
게이트가 Swift 컨벤션도 강제한다. 이건 더 이상 가설이 아니다: `*.swift` 규칙이
`CONVENTIONS.md`에 들어 있고, 깨끗한 SwiftUI 샘플이 `samples/ios/`에 있으며,
게이트는 그 샘플로 end-to-end 검증되어 있다.

**적용 중인 Swift 규칙** (`applies: *.swift`, `rules.json`으로 컴파일됨):

| id | severity | 잡는 것 |
|----|----------|---------|
| `swift-no-print` | error | `print(` — `os.Logger`를 쓸 것 |
| `swift-no-force-cast` | error | `as!` 강제 캐스트 |
| `swift-no-force-try` | error | `try!` 강제 try |
| `swift-no-force-unwrap` | warn | 휴리스틱 강제 언래핑 `x!` |
| `swift-max-line-120` | warn | 120자 초과 줄 (SwiftLint 기본값) |

**크로스 엔진 정규식.** 토큰 규칙은 BSD grep·GNU grep·ugrep 세 엔진에서 모두 도는
분기형(`^kw!|[^word]kw!`)으로 작성했다. 주의: 로컬 `grep`이 ugrep이면 `(^|[^…])`
그룹이 일부 키워드(특히 0열의 `try!`)를 조용히 놓친다 — 분기형이 의도적인 이유다.
실전의 전부인 들여쓰기된 Swift는 세 엔진 모두에서 잡힌다.

**직접 검증:**

```bash
# 깨끗한 SwiftUI 샘플 -> 무출력 allow
jq -nc --arg fp "$PWD/samples/ios/Sources/CounterFeature/CounterView.swift" \
  --rawfile c samples/ios/Sources/CounterFeature/CounterView.swift \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' \
| bash .claude/hooks/router.sh          # 출력 없음 = allow

# print / 강제 캐스트 / 강제 try -> deny
jq -nc --arg fp "$PWD/Bad.swift" \
  --arg c $'func f() {\n    print("x")\n    let s = a as! String\n    let d = try! load()\n}\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' \
| bash .claude/hooks/router.sh          # permissionDecision: deny
```

Swift 규칙을 추가/변경하려면 `CONVENTIONS.md`의 `*.swift` rule 블록을 고치고
`python3 tools/parse_conventions.py`를 다시 돌린다. `.claude/config.json`의
`source_globs`에는 `*.swift`가 이미 들어 있다 — `settings.json`과 라우터는 손댈 게 없다.

---

## 규칙을 측정한다 (정밀도 / 재현율)

로그는 게이트가 *무엇을 했는지*는 말해주지만 규칙의 *오탐율*은 말해주지 못한다 —
`gates.log`에는 정답(ground truth)이 없기 때문이다. `tools/bench_rules.py`가 그걸
공급한다: 모든 스니펫에 "발화해야 할 규칙 id"가 라벨링된 코퍼스
(`tools/bench/rule_fixtures.json`) 위로 진짜 Gate 1을 돌린다 — 아무것도 발화하면
안 되는 까다로운 클린 케이스(`x != y`, `!flag`, `as?`, `try await`, `reprint(`)까지 포함해서.

```bash
python3 tools/bench_rules.py          # 규칙별 TP/FP/FN, 정밀도, 재현율
python3 tools/bench_rules.py --json   # 머신 가독
```

`hes_controller.py`와 같은 `HES_*` 계약으로 게이트를 재사용하며(규칙 로직 재구현
없음), **어느 규칙이든 오탐이나 미탐이 하나라도 있으면 non-zero로 종료한다** —
"모든 규칙 정밀도/재현율 1.00, FP 0, FN 0"이 강제 가능한 기준선이고,
`tests/test_rules_bench.py`로 `pytest`에 연결되어 있다. 규칙을 추가했다면 픽스처도
추가하라(발화해야 하는 케이스 *그리고* 발화하면 안 되는 까다로운 케이스). 규칙은
감이 아니라 측정으로 결정한다.
