# HES — Harness Enforcement System

> 모델에게 규칙을 지켜달라고 부탁하지 않는다. 규칙을 어긴 쓰기를 디스크 직전에서 차단한다.
> Claude Code `PreToolUse` 훅 위에서 도는 강제 집행(enforcement) 레이어 — guidance가 아니다.

**전제.** LLM 에이전트의 컨벤션 준수는 프롬프트로 보장되지 않는다. 실패는 세 패턴으로
반복되며, HES는 각각을 프롬프트가 아니라 **구조**로 막는다.

| 실패 모드 | 증상 | 구조적 해법 |
|---|---|---|
| **Instruction decay** | `CLAUDE.md`의 "print() 금지"는 부탁 — 컨텍스트가 길어지면 잊힌다 | 규칙을 모델 밖으로. 훅은 OS가 돌리는 셸 프로세스 — 게이트 미통과 `Edit/Write/MultiEdit`는 **파일시스템에 닿지 않는다** |
| **Self-preferential bias** | 생성자가 검증을 겸하면 루프는 심판을 속이는 방향으로 진화한다 | 판정 1순위는 **결정론 신호** (grep · 구조검증 · pytest · 게이트 통과율). LLM 리뷰는 독립 프로세스의 보조 의견, 최종 서명은 사람 |
| **Goal drift · agentic laziness** | 긴 자율 루프는 목표를 이탈하거나 부분완료에서 멈춘다 | 제어 흐름은 모델 재량이 아니라 **스크립트가 집행** — 생성→검증→승격 전 단계가 결정론적 파이프라인, 모델은 그 안의 한 단계 |

```
Edit / Write / MultiEdit
        │
        ▼
PreToolUse 훅 = router.sh ──▶ Gate 1  grep            0 토큰 · 항상 · 유일한 하드 게이트
        │                     Gate 2  Haiku           ≥50줄 · 기본 OFF · fail-open
        │                     Gate 3  Sonnet+ARCH.md  ≥200줄 · 기본 OFF · fail-open
        ▼
error 위반? ── yes ─▶ deny (쓰기 자체가 일어나지 않음)  /  no ─▶ allow
```

규칙은 `CONVENTIONS.md` 한 곳에 산다 — 현재 10개 (Python 5 + Swift 5).
이 저장소는 HES 0~4 전 계층의 레퍼런스 구현이며, Python 테스트베드(`src/`)와
SwiftUI 샘플(`samples/ios/`)로 게이트를 end-to-end 검증한다.

---

## ⚡ Quick Start

**1. Claude Code** — 레포를 열면 끝. `.claude/settings.json`이 훅을 연결해 두었고, 매 편집이 쓰기 직전 게이트된다.

**2. 훅 단독 검증** (Claude Code 불필요):

```bash
# deny — print() 위반
jq -nc --arg fp "$PWD/src/calculator.py" \
  --arg c $'def f():\n    print("x")\n    return 1\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
# → {"hookSpecificOutput":{"permissionDecision":"deny", ...}}

# allow — 깨끗한 코드, 무출력
jq -nc --arg fp "$PWD/src/calculator.py" \
  --arg c $'"""mod."""\n\n\ndef f():\n    return 1\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
```

**3. git / CI — 같은 게이트, 같은 판정:**

```bash
bash tools/install-git-hooks.sh                            # git commit 마다 차단 (1회 설치)
python3 tools/hes_controller.py --range main..HEAD --json  # CI: REJECTED → exit 1
```

> 규칙 변경 후에는 `python3 tools/parse_conventions.py` — 훅은 Markdown이 아니라 컴파일된 `rules.json`을 읽는다.

---

## 게이트 사다리

변경은 싼 순서대로 게이트를 오른다. 대부분의 편집은 Gate 1(0토큰)에서 종결.

| Gate | 엔진 | 비용 | 잡는 것 | 조건 |
|---|---|---|---|---|
| **1** | 셸 grep vs `rules.json` | **0 토큰** | 금지/필수 패턴 · 줄길이 · 파일명 (Py+Swift 10룰) | **항상** |
| **2** | Haiku (diff만) | ~300 토큰 | 정규식이 못 보는 의미적 결함 | ≥50줄 + ON |
| **3** | Sonnet (+`ARCHITECTURE.md`) | 수천 토큰 | 레이어 · 경계 · 결합 드리프트 | ≥200줄 + ON |
| **4** | 사람 | — | 기계가 못 정하는 것 | 스킬 · 프롬프트 승격 승인 |

- **하드 보장은 Gate 1뿐.** Gate 2/3은 fail-open — 꺼짐 · CLI 부재 · 모델 에러 시 통과. 보호를 더할 뿐, Gate 1의 보호를 빼앗지 못한다.
- **단락(short-circuit).** enforce 모드에서 싼 게이트가 `error`를 내면 LLM 게이트 스킵 — 사다리는 첫 실패 단에서 멈춘다.
- **점진 도입.** `mode: "warn"` — 차단 없이 경고만. 새 규칙 적응기에 사용.

## 규칙 — 추가는 3줄, 채택은 측정으로

`CONVENTIONS.md`의 rule 블록이 진실의 원천. 실제 적용 중인 Swift 룰 그대로:

````markdown
```rule
id: swift-no-force-cast
severity: error
applies: *.swift
type: forbid_pattern
pattern: (^as!|[^A-Za-z0-9_]as!)
message: 강제 캐스트(as!) 는 금지입니다. as? 와 옵셔널 바인딩을 쓰세요
```
````

```bash
python3 tools/parse_conventions.py   # 재컴파일 → .claude/cache/rules.json
python3 tools/bench_rules.py         # 정밀도/재현율 측정 → FP/FN 0 강제 (현재 18/18 CLEAN)
```

규칙 타입 4종: `forbid_pattern` · `require_pattern` · `max_line_length` · `filename_pattern` — glob과 정규식만 보므로 언어 무관.
규칙을 추가하면 라벨링된 픽스처(`tools/bench/rule_fixtures.json`)도 추가한다. 벤치마크는
오탐·미탐이 하나라도 있으면 non-zero로 종료하고 `pytest`에 물려 있다 — **규칙은 감이 아니라 측정으로 결정한다.**

---

## 🔁 스킬 팩토리 — eval이 닫는 자가개선 루프

자가개선 루프의 품질 상한선은 eval의 신뢰도다.

> **모델은 제안한다. 증거가 승격시킨다. 사람이 서명한다.**

```
 고정 goal set ──▶ v9(메타프롬프트 vN) ──▶ 스킬 후보 ──▶ HES 게이트 ──▶ 설치
 (eval_goals)            ▲                                │              │
                         │                                ▼              ▼
                         │                       runs.jsonl ◀── 전 결과 자동 기록
                         │                                │
                         │      v9_eval: 같은 goal set을 vN(챔피언) vs 후보(도전자)로
                         │      재생 → 결정론 채점 → verdict (동점 = 챔피언 유지)
                         │                                │
                         └── 이긴 후보만 --approve 승격 ◀──┘ (진 후보는 --force 없인 거부)
```

```bash
bash tools/skill_pipeline.sh "<goal>"            # 생성→품질루프→검증·충돌·회귀→AI리뷰→사람 게이트
bash tools/skill_pipeline.sh "<goal>" --approve  # 검토 후 설치 (Gate 4)

python3 tools/v9_improve.py                      # 개선 제안 — runs.jsonl 실패 이력 자동 환류
python3 tools/v9_eval.py                         # 챔피언 vs 도전자 채점 — 증거 생산
python3 tools/v9_improve.py --approve            # 이긴 후보만 승격 (vN → vN+1, 구버전 아카이브)
```

설계 계약 3개 — 위 실패 모드의 대칭:

- **생성 = fail-loud, 게이트·비평 = fail-open.** 모델 없이는 만들 게 없으므로 크게 실패하고, 검증 부가물이 죽어도 결정론 게이트의 보호는 빠지지 않는다.
- **생성자는 자기를 채점하지 않는다.** eval 채점은 산수 — 구조 유효율 → 잔여 문제 수 → 수정 라운드. 동점이면 챔피언 유지.
- **`--approve` 없이는 설치·승격 불가.** 검증 안 거친 생성물이 시스템에 들어올 경로가 없다.

## 계층 구조 (0→4)

| 계층 | 역할 | 구현 |
|---|---|---|
| **0** Core Runtime | PreToolUse 게이트 런타임 — 나쁜 쓰기를 OS 직전 차단 | `.claude/hooks/` |
| **1** Automation Controller | 배치 / 커밋 / CI 게이트 실행 · 판정 | `tools/hes_controller.py` |
| **2** V9 Auto-Improvement | 스킬 생성 + 품질루프 + eval 기반 자가개선 | `tools/v9_generate.py` · `v9_eval.py` · `v9_improve.py` |
| **3** Skill Adapter | 후보 검증 · 정규화 | `tools/skill_adapter.py` |
| **4** Integration Bridge | 검증 → 사람 승인 → 설치 | `tools/skill_integrate.sh` |

## 저장소 구조

```
.claude/
  settings.json          # PreToolUse "Edit|Write|MultiEdit" → router.sh
  config.json            # 게이트 토글 · 임계값 · mode(enforce|warn)
  cache/rules.json       # CONVENTIONS.md 컴파일 결과 — Gate 1이 읽음 (10 rules)
  hooks/                 # router.sh + gate1/2/3 + lib/common.sh
  logs/v9_runs.jsonl     # 루프 텔레메트리 (생성·통합·eval·승격, git 추적 제외)
tools/
  parse_conventions.py   # 규칙 컴파일러            hes_controller.py   # Layer 1 배치 컨트롤러
  bench_rules.py         # 룰 정밀도/재현율 벤치     bench/rule_fixtures.json  # 라벨링 코퍼스 (18)
  v9/meta_prompt.md      # Layer 2 메타프롬프트     v9/eval_goals.json  # eval 고정 goal set (12)
  v9_generate.py         # 생성 + 품질루프          v9_eval.py          # 챔피언 vs 도전자 채점
  v9_improve.py          # 제안 → 증거 → 승격       skill_adapter.py    # Layer 3
  skill_integrate.sh     # Layer 4                 skill_pipeline.sh   # Layer 2→4 단일 명령
  ai_review.sh           # advisory 리뷰어 (fail-open)
CONVENTIONS.md           # 규칙 — 산문 + 기계가독 rule 블록 (Py 5 + Swift 5)
ARCHITECTURE.md          # Gate 3 컨텍스트
samples/ios/             # 게이트 검증용 SwiftUI 샘플 (클린 통과 보장)
src/ tests/              # Python 테스트베드 + 도구 회귀 테스트 (pytest 43)
```

## 기성 도구와의 관계

Ouroboros · Superpowers · GSD · gstack은 프롬프트/스킬/스펙 레이어의 **유도** — 모델이 무시할 수 있다.
HES는 그 아래의 마지막 안전망으로 **함께** 쓴다.

| | 동작 레이어 | 모델이 무시 가능? | 1변경당 비용 |
|---|---|---|---|
| **HES** | OS 직전 (셸 훅) | **불가능** — deny JSON이면 쓰기 차단 | 0~300 토큰 |
| Ouroboros 등 | 프롬프트 · 스펙 · MCP | 가능 | 수천 토큰 (멀티모델 검증) |

0→1 생성은 그들의 영역. HES는 1→N 유지보수 — 매 변경 검증을 grep 우선으로 거의 0토큰에 수행한다.

## 문서

| 문서 | 내용 |
|---|---|
| [HARNESS.md](./HARNESS.md) | 운영자 가이드 — 게이트 동작 상세 · Swift 지원 · 룰 벤치마크 · 수동 테스트 |
| [USAGE.md](./USAGE.md) | 실전 명령어 — 3가지 모드 · 규칙 편집 · 레포 이식 · 스킬 팩토리 |
| [CONVENTIONS.md](./CONVENTIONS.md) | 강제되는 규칙 (진실의 원천) |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Gate 3가 읽는 아키텍처 문서 |

<sub>설계 근거: [Ouroboros](https://github.com/Q00/ouroboros) · [Superpowers](https://github.com/obra/superpowers) · [gstack](https://github.com/garrytan/gstack) · [Dynamic workflows in Claude Code (Anthropic)](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code) — 실패 모드 명명(instruction decay · self-preferential bias · goal drift)과 "검증은 독립 에이전트가, 제어 흐름은 스크립트가" 원칙을 공유한다.</sub>
