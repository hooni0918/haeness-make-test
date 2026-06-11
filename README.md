# HES — Harness Enforcement System

> **AI가 규칙 어긴 코드를 쓰는 그 순간, 셸이 막는다.**
> Claude Code `PreToolUse` 훅 위에서 도는 강제 집행(enforcement) 레이어 — 부탁(guidance)이 아니라 차단(harness)이다.

`CLAUDE.md`의 "print() 쓰지 마세요"는 부탁이다. 컨텍스트가 길어지면 모델은 잊는다.
HES는 AI와 파일시스템 사이에 앉아, 규칙을 어긴 `Edit / Write / MultiEdit`를 **디스크에 닿기 전에 deny** 한다.
훅은 모델 의지와 무관하게 OS가 돌리는 셸 프로세스라서, 모델이 무시할 수 없다.

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

> 규칙을 고쳤으면 `python3 tools/parse_conventions.py` 로 캐시 재컴파일 — 훅은 Markdown이 아니라 `rules.json`을 읽는다.

---

## 게이트 사다리

변경은 싼 순서대로 게이트를 오른다. 대부분은 Gate 1(0토큰)에서 끝난다.

| Gate | 엔진 | 비용 | 잡는 것 | 실행 조건 |
|---|---|---|---|---|
| **1** | 셸 grep vs `rules.json` | **0 토큰** | 금지/필수 패턴 · 줄길이 · 파일명 | **항상** |
| **2** | Haiku (diff만) | ~300 토큰 | 정규식이 못 보는 의미적 냄새 | ≥50줄 + ON |
| **3** | Sonnet (+`ARCHITECTURE.md`) | 수천 토큰 | 레이어·경계·결합 드리프트 | ≥200줄 + ON |
| **4** | 사람 | — | 기계가 못 정하는 것 | 스킬 설치 승인 등 |

- **하드 보장은 Gate 1뿐.** Gate 2/3은 fail-open — 꺼짐/CLI 없음/모델 에러면 그냥 통과.
- **단락(short-circuit):** enforce 모드에서 싼 게이트가 이미 `error`를 내면 LLM 게이트는 스킵 — 사다리는 첫 실패 단에서 멈춘다(토큰 0 추가).
- `mode: "warn"` 으로 바꾸면 차단 없이 경고만 — 새 규칙 점진 도입용.

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

## 🔁 스킬 파이프라인 (Layer 2→4)

AI가 만든 **스킬도 같은 원칙으로** 들어온다: 모델은 생성·제안만, 설치는 검증 + 사람 승인을 통과해야만.

```bash
# 생성 → 품질루프 → 검증·충돌·회귀 → AI리뷰 → 사람 게이트에서 정지 (dry-run)
bash tools/skill_pipeline.sh "파이썬 파일 수정 시 import 정리하는 스킬"

# 검토 후 설치 (--approve = Gate 4)
bash tools/skill_pipeline.sh "..." --approve

# 메타프롬프트 자가개선 — 제안은 모델, 승격은 사람
python3 tools/v9_improve.py            # → meta_prompt.candidate.md 제안
python3 tools/v9_improve.py --approve  # → 검토 후 승격 (구버전 아카이브, version +1)
```

```
v9 생성 ─▶ 1차 품질루프 ─▶ 어댑터 검증 ─▶ 충돌·회귀(pytest) ─▶ AI 리뷰 ─▶ 사람 --approve ─▶ 설치
(Layer 2)   (Layer 2)       (Layer 3)      (Layer 0+1)        (Layer 1)   (Gate 4)      (Layer 4)
```

`--approve` 없이는 어떤 스킬도 설치되지 않는다. 검증 안 거친 생성물이 시스템에 들어올 경로가 없다.

## 계층 구조 (0→4)

| 계층 | 역할 | 구현 |
|---|---|---|
| **0** Core Runtime | PreToolUse 게이트 런타임 — 나쁜 쓰기를 OS 직전 차단 | `.claude/hooks/` |
| **1** Automation Controller | 배치/커밋/CI 게이트 실행·판정 | `tools/hes_controller.py` |
| **2** V9 Auto-Improvement | 스킬 후보 생성 + 품질루프, 메타프롬프트 자가개선 | `tools/v9_generate.py` · `v9_improve.py` |
| **3** Skill Adapter | 후보 검증·정규화 | `tools/skill_adapter.py` |
| **4** Integration Bridge | 검증 → 사람 승인 → 설치 | `tools/skill_integrate.sh` |

## 저장소 구조

```
.claude/
  settings.json          # PreToolUse "Edit|Write|MultiEdit" → router.sh
  config.json            # 게이트 토글 · 임계값 · mode(enforce|warn)
  cache/rules.json       # CONVENTIONS.md 컴파일 결과 (Gate 1이 읽음)
  hooks/                 # router.sh + gate1/2/3 + lib/common.sh
tools/
  parse_conventions.py   # 규칙 컴파일러
  hes_controller.py      # Layer 1 배치 컨트롤러 (--staged/--files/--range)
  v9/meta_prompt.md      # Layer 2 메타프롬프트 (진실의 원천)
  v9_generate.py         # Layer 2 생성 + 품질루프      v9_improve.py  # 자가개선
  skill_adapter.py       # Layer 3                      skill_integrate.sh  # Layer 4
  skill_pipeline.sh      # Layer 2→4 한 명령
  ai_review.sh           # advisory 리뷰어 (fail-open)
CONVENTIONS.md           # 규칙 (사람용 산문 + 기계용 rule 블록)
ARCHITECTURE.md          # Gate 3 컨텍스트
src/ tests/              # 게이트 검증용 테스트베드 + 도구 회귀 테스트 (pytest)
```

## 왜 기성 도구가 아닌가

Ouroboros · Superpowers · GSD · gstack 은 전부 프롬프트/스킬/스펙 레이어의 **유도**다 — 모델이 마음먹으면 무시할 수 있다.
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
| [USAGE.md](./USAGE.md) | 실전 명령어 — 3가지 모드, 규칙 편집, 다른 레포 이식, 스킬 파이프라인 |
| [CONVENTIONS.md](./CONVENTIONS.md) | 강제되는 규칙 (진실의 원천) |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Gate 3가 읽는 아키텍처 문서 |

<sub>비교 근거: [Ouroboros](https://github.com/Q00/ouroboros) · [Superpowers](https://github.com/obra/superpowers) · [gstack](https://github.com/garrytan/gstack) · [orchestration frameworks 비교](https://www.pulumi.com/blog/claude-code-orchestration-frameworks/)</sub>
