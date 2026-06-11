# HES — Harness Enforcement System

> 모델에게 규칙을 지켜달라고 부탁하는 대신, 규칙을 어긴 쓰기가 디스크에 닿지 못하게 만들었다.
> Claude Code `PreToolUse` 훅 위에서 도는 강제 집행 하네스 — guidance가 아니라 enforcement다.

## 왜 만들었나 — 세 가지 실패 모드

AI 코딩 에이전트를 오래 돌리면 누구나 같은 벽을 만난다. 우리는 그 벽에 이름을 붙이고,
각각을 프롬프트가 아니라 **구조**로 풀었다.

**1. 지시는 부패한다 (instruction decay).**
`CLAUDE.md`의 "print() 금지"는 부탁이다. 컨텍스트가 길어지고 지시가 충돌하면 모델은 잊는다.
→ 규칙을 모델 밖에 둔다. `PreToolUse` 훅은 모델의 의지와 무관하게 OS가 돌리는 셸 프로세스고,
게이트를 통과 못 한 `Edit / Write / MultiEdit`는 **파일시스템에 닿지 않는다.**

**2. 자기 채점은 후하다 (self-preferential bias).**
생성한 모델이 검증까지 맡으면 자기 결과에 관대해지고, 루프는 심판을 속이는 방향으로 진화한다.
→ 판정의 1순위는 LLM이 아니라 **결정론적 신호**다 — grep, 구조 검증, pytest, 게이트 통과율.
LLM 리뷰는 독립 프로세스의 보조 의견이고, 최종 서명은 사람이 한다.

**3. 긴 루프는 표류한다 (goal drift, agentic laziness).**
자율 루프는 목표에서 벗어나거나 부분완료에서 멈춘다.
→ 루프의 제어 흐름은 모델 재량이 아니라 **스크립트가 집행**한다. 생성→검증→승격의 모든 단계를
셸/파이썬 파이프라인이 결정론적으로 돌리고, 모델은 그 안의 한 단계일 뿐이다.

```
Claude 가 코드 작성 시도 (Edit / Write / MultiEdit)
        │
        ▼
PreToolUse 훅 = router.sh ──▶ Gate 1  grep            0 토큰 · 항상 · 유일한 하드 게이트
        │                     Gate 2  Haiku           ≥50줄 · 기본 OFF · fail-open
        │                     Gate 3  Sonnet+ARCH.md  ≥200줄 · 기본 OFF · fail-open
        ▼
error 위반 있나? ── yes ─▶ deny  (쓰기 자체가 일어나지 않음)
        └────────── no ──▶ allow
```

규칙은 `CONVENTIONS.md`에 한 번 써두면 끝. 이 저장소는 HES 0~4 전 계층의 레퍼런스 구현이며,
게이트가 실제 도는 걸 보여주려고 작은 파이썬 프로젝트(`src/`, `tests/`)를 검증 대상으로 둔다.

---

## ⚡ Quick Start

**1. Claude Code에서 (설정 0)** — 이 레포를 열기만 하면 끝. 이후 매 편집이 쓰기 직전 자동 게이트된다.

**2. 훅만 30초 검증** (Claude Code 불필요):

```bash
# 막히는 케이스 — print() 는 컨벤션 위반 → deny
jq -nc --arg fp "$PWD/src/calculator.py" \
  --arg c $'def f():\n    print("x")\n    return 1\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
# → {"hookSpecificOutput":{"permissionDecision":"deny", ...}}

# 통과 케이스 — 깨끗한 코드 → 빈 출력(allow)
jq -nc --arg fp "$PWD/src/calculator.py" \
  --arg c $'"""mod."""\n\n\ndef f():\n    return 1\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
```

**3. git / CI에도 같은 게이트:**

```bash
bash tools/install-git-hooks.sh                            # git commit 마다 차단 (1회 설치)
python3 tools/hes_controller.py --range main..HEAD --json  # CI: REJECTED 면 exit 1
```

> 규칙을 고쳤으면 `python3 tools/parse_conventions.py`로 캐시 재컴파일 — 훅은 Markdown이 아니라 `rules.json`을 읽는다.

---

## 게이트 사다리

변경은 싼 순서대로 게이트를 오른다. 대부분은 Gate 1(0토큰)에서 끝난다.

| Gate | 엔진 | 비용 | 잡는 것 | 실행 조건 |
|---|---|---|---|---|
| **1** | 셸 grep vs `rules.json` | **0 토큰** | 금지/필수 패턴 · 줄길이 · 파일명 | **항상** |
| **2** | Haiku (diff만) | ~300 토큰 | 정규식이 못 보는 의미적 냄새 | ≥50줄 + ON |
| **3** | Sonnet (+`ARCHITECTURE.md`) | 수천 토큰 | 레이어·경계·결합 드리프트 | ≥200줄 + ON |
| **4** | 사람 | — | 기계가 못 정하는 것 | 스킬·프롬프트 승격 승인 |

- **하드 보장은 Gate 1뿐.** Gate 2/3은 fail-open — 꺼짐/CLI 없음/모델 에러면 그냥 통과.
- **단락(short-circuit):** enforce 모드에서 싼 게이트가 이미 `error`를 내면 LLM 게이트는 스킵 —
  사다리는 첫 실패 단에서 멈춘다(토큰 0 추가).
- `mode: "warn"`으로 바꾸면 차단 없이 경고만 — 새 규칙 점진 도입용.

## 규칙 추가는 3줄

`CONVENTIONS.md`에 rule 블록을 쓰고 재컴파일하면 다음 편집부터 강제된다:

````markdown
```rule
id: no-force-unwrap
severity: error
applies: *.swift
type: forbid_pattern
pattern: as!|try!
message: force-cast / force-try 금지
```
````

```bash
python3 tools/parse_conventions.py   # → .claude/cache/rules.json
```

타입: `forbid_pattern` · `require_pattern` · `max_line_length` · `filename_pattern`. 언어 무관 — glob과 정규식만 본다.

---

## 🔁 스킬 팩토리 — eval이 닫는 자가개선 루프

자가개선 루프의 품질 상한선은 eval의 신뢰도가 결정한다. 그래서 이 루프는 세 문장으로 요약된다:

> **모델은 제안한다. 증거가 승격시킨다. 사람이 서명한다.**

```
 고정 goal set ──▶ v9(메타프롬프트 vN) ──▶ 스킬 후보 ──▶ HES 게이트 ──▶ 설치
 (eval_goals)            ▲                                │              │
                         │                                ▼              ▼
                         │                       runs.jsonl ◀── 모든 결과 자동 기록
                         │                       (위반·반려·잔여문제가 데이터로 쌓임)
                         │                                │
                         │      v9_eval: 같은 goal set 을 vN(챔피언) vs 후보(도전자)로
                         │      재생 → 결정론 신호로 채점 → verdict (동점은 챔피언 유지)
                         │                                │
                         └── 이긴 후보만 --approve 승격 ◀──┘  (진 후보는 --force 없인 거부)
```

```bash
# 스킬 생성 → 품질루프 → 검증·충돌·회귀 → AI리뷰 → 사람 게이트 (한 명령)
bash tools/skill_pipeline.sh "파이썬 파일 수정 시 import 정리하는 스킬"
bash tools/skill_pipeline.sh "..." --approve        # 검토 후 설치 (Gate 4)

# 메타프롬프트 자가개선 — 실패 이력이 자동으로 다음 제안의 입력이 된다
python3 tools/v9_improve.py                         # 제안 (runs.jsonl 실패 자동 환류)
python3 tools/v9_eval.py                            # 챔피언 vs 도전자 — 증거 생산
python3 tools/v9_improve.py --approve               # 이긴 후보만 승격 (v9 → v10, 구버전 아카이브)
```

설계 원칙 — 위의 실패 모드 세 개가 그대로 적용된다:

- **생성은 fail-loud, 게이트·비평은 fail-open.** 모델 없이는 만들 게 없으니 크게 실패하고,
  검증 부가물이 죽어도 결정론적 게이트의 보호는 빠지지 않는다.
- **생성자는 절대 자기를 채점하지 않는다.** eval의 채점은 산수다 — 구조 유효율 → 잔여 문제 수 →
  수정 라운드 수. 동점이면 챔피언 유지(증거 없이 갈아치우지 않는다).
- **`--approve` 없이는 어떤 것도 설치·승격되지 않는다.** 검증 안 거친 생성물이 시스템에 들어올 경로가 없다.

## 계층 구조 (0→4)

| 계층 | 역할 | 구현 |
|---|---|---|
| **0** Core Runtime | PreToolUse 게이트 런타임 — 나쁜 쓰기를 OS 직전 차단 | `.claude/hooks/` |
| **1** Automation Controller | 배치/커밋/CI 게이트 실행·판정 | `tools/hes_controller.py` |
| **2** V9 Auto-Improvement | 스킬 생성 + 품질루프 + **eval 기반 자가개선** | `tools/v9_generate.py` · `v9_eval.py` · `v9_improve.py` |
| **3** Skill Adapter | 후보 검증·정규화 | `tools/skill_adapter.py` |
| **4** Integration Bridge | 검증 → 사람 승인 → 설치 | `tools/skill_integrate.sh` |

## 저장소 구조

```
.claude/
  settings.json          # PreToolUse "Edit|Write|MultiEdit" → router.sh
  config.json            # 게이트 토글 · 임계값 · mode(enforce|warn)
  cache/rules.json       # CONVENTIONS.md 컴파일 결과 (Gate 1이 읽음)
  hooks/                 # router.sh + gate1/2/3 + lib/common.sh
  logs/v9_runs.jsonl     # 루프 텔레메트리 (생성·통합·승격 전 결과, git 추적 제외)
tools/
  parse_conventions.py   # 규칙 컴파일러
  hes_controller.py      # Layer 1 배치 컨트롤러 (--staged/--files/--range)
  v9/meta_prompt.md      # Layer 2 메타프롬프트 (진실의 원천, version 관리)
  v9/eval_goals.json     # eval 고정 goal set — 메타프롬프트의 시험 문제지
  v9_generate.py         # 생성 + 품질루프        v9_eval.py     # 챔피언 vs 도전자 채점
  v9_improve.py          # 제안→증거→승격          skill_adapter.py    # Layer 3
  skill_integrate.sh     # Layer 4                skill_pipeline.sh   # 2→4 한 명령
  ai_review.sh           # advisory 리뷰어 (fail-open)
CONVENTIONS.md           # 규칙 (사람용 산문 + 기계용 rule 블록)
ARCHITECTURE.md          # Gate 3 컨텍스트
src/ tests/              # 게이트 검증용 테스트베드 + 도구 회귀 테스트 (pytest, 42개)
```

## 왜 기성 도구가 아닌가

Ouroboros · Superpowers · GSD · gstack은 전부 프롬프트/스킬/스펙 레이어의 **유도**다 — 모델이 마음먹으면 무시할 수 있다.
HES는 그 아래 깔리는 마지막 안전망으로, **함께 쓰는** 보완재다:

| | 동작 레이어 | 모델이 무시 가능? | 1변경당 비용 |
|---|---|---|---|
| **HES** | OS 직전 (셸 훅) | **불가능** — deny JSON이면 쓰기 차단 | 0~300 토큰 |
| Ouroboros 등 | 프롬프트·스펙·MCP | 가능 | 수천 토큰 (멀티모델 검증) |

생성은 그들이 잘한다(0→1). HES는 매 변경 검증(1→N)을 grep 우선으로 거의 공짜에 한다.

## 문서

| 문서 | 내용 |
|---|---|
| [HARNESS.md](./HARNESS.md) | 운영자 가이드 — 게이트 동작 상세, 로그, 수동 테스트 |
| [USAGE.md](./USAGE.md) | 실전 명령어 — 3가지 모드, 규칙 편집, 다른 레포 이식, 스킬 팩토리 |
| [CONVENTIONS.md](./CONVENTIONS.md) | 강제되는 규칙 (진실의 원천) |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Gate 3가 읽는 아키텍처 문서 |

<sub>비교·설계 근거: [Ouroboros](https://github.com/Q00/ouroboros) · [Superpowers](https://github.com/obra/superpowers) · [gstack](https://github.com/garrytan/gstack) · [Dynamic workflows in Claude Code (Anthropic)](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code) — agentic laziness · self-preferential bias · goal drift 라는 실패 모드 명명과 "검증은 독립 에이전트가, 제어 흐름은 스크립트가" 원칙을 공유한다.</sub>
