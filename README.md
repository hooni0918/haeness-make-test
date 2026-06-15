# HES — Harness Enforcement System

> 모델에게 규칙을 **부탁하지 않는다.** 규칙을 어긴 쓰기를 디스크 직전에서 **차단한다.**
> Claude Code `PreToolUse` 훅 위에서 도는 강제 집행 레이어 — guidance가 아니다.

LLM은 컨텍스트가 길어지면 규칙을 잊고(instruction decay), 스스로 채점하면 심판을
속이고(self-preferential bias), 긴 루프에서 목표를 이탈한다(goal drift). HES는 이 셋을
프롬프트가 아니라 **구조**로 막는다 — 규칙은 모델 밖 셸 훅이 집행하고, 판정 1순위는
결정론 신호(grep·pytest)이며, 제어 흐름은 모델이 아니라 스크립트가 쥔다.

## 구조 한눈에

두 부분이다. **강제집행(0–1)** 은 이미 구축된 하네스, **스킬 팩토리(2–4)** 는 그 위에서
스킬을 만들어 안전하게 설치하는 자가개선 루프.

```
강제집행 — 이미 구축 완료
  0  Core Runtime           → PreToolUse 훅이 위반 쓰기를 OS 직전 차단
  1  Automation Controller  → 배치·커밋·CI에서 같은 게이트를 실행·판정

스킬 팩토리 — 위 하네스 위에서 도는 루프
  2  V9 Lane                → 스킬 생성 + 품질루프 + 메타프롬프트 자가개선
  3  Skill Adapter          → 만들어진 스킬 후보를 검증·정규화
  4  Integration Bridge     → 충돌·회귀·AI리뷰·사람승인 후 설치
```

스킬 하나가 만들어져 설치되기까지의 흐름:

```
v9 스킬 생성 ─▶ v9 품질루프 ─▶ 어댑터 검증 ─▶ HES 충돌·회귀 ─▶ AI 리뷰 ─▶ 사람 --approve ─▶ 설치
    (L2)          (L2)          (L3)           (L4)           (L4)        (L4)            (L4)
```

> 스킬을 **"만드는"** 건 Layer 2(`v9_generate`)다. Layer 3 어댑터는 만든 후보를 **검증·정규화만** 한다.

---

## 게이트 사다리

변경은 싼 순서로 게이트를 오른다. 대부분의 편집은 Gate 1(0토큰)에서 끝난다.

| Gate | 엔진 | 비용 | 잡는 것 | 조건 |
|---|---|---|---|---|
| **1** | 셸 grep vs `rules.json` | **0 토큰** | 금지/필수 패턴·줄길이·파일명 (10룰) | **항상 ON** |
| **2** | Haiku (diff) | ~300 토큰 | 정규식이 못 보는 의미적 결함 | ≥50줄 + 켜야 함 |
| **3** | Sonnet (+`ARCHITECTURE.md`) | 수천 토큰 | 레이어·경계·결합 드리프트 | ≥200줄 + 켜야 함 |
| **4** | 사람 | — | 기계가 못 정하는 것 | 스킬·프롬프트 승격 승인 |

- **하드 보장은 Gate 1뿐.** Gate 2/3은 기본 OFF이고 fail-open — 꺼짐·CLI 부재·모델 에러 시 그냥 통과한다(Gate 1 보호는 그대로).
- **단락(short-circuit).** enforce 모드에서 싼 게이트가 `error`를 내면 LLM 게이트는 스킵 — 사다리는 첫 실패 단에서 멈춘다.
- **점진 도입.** `config.json`의 `mode:"warn"` — 차단 없이 경고만.

## Quick Start

```bash
# 1. Claude Code: 레포를 열면 끝 — settings.json이 훅을 연결해 둠. 매 편집이 쓰기 직전 게이트됨.

# 2. 훅 단독 검증 (Claude Code 불필요)
jq -nc --arg fp "$PWD/src/calculator.py" \
  --arg c $'def f():\n    print("x")\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
# → {"hookSpecificOutput":{"permissionDecision":"deny", ...}}   (print() 위반 → 차단)

# 3. git / CI — 같은 게이트, 같은 판정
bash tools/install-git-hooks.sh                              # 커밋마다 차단 (1회 설치)
python3 tools/hes_controller.py --range <base>..HEAD --json  # CI: REJECTED → exit 1
```

> 규칙을 고치면 `python3 tools/parse_conventions.py` — 훅은 Markdown이 아니라 컴파일된 `rules.json`을 읽는다.

## 규칙 — 추가는 3줄, 채택은 측정으로

`CONVENTIONS.md`가 진실의 원천. rule 블록을 추가 → 재컴파일 → 벤치마크로 정밀도/재현율 확인.

```bash
python3 tools/parse_conventions.py   # CONVENTIONS.md → .claude/cache/rules.json
python3 tools/bench_rules.py         # FP/FN 0 강제 (현재 18/18 CLEAN), pytest에 연결됨
```

룰 타입 4종(`forbid_pattern`·`require_pattern`·`max_line_length`·`filename_pattern`)은 glob+정규식만 보므로 언어 무관. 현재 10룰(Python 5 + Swift 5). 규칙을 추가하면 라벨링 픽스처(`tools/bench/rule_fixtures.json`)도 같이 추가한다 — **규칙은 감이 아니라 측정으로 채택한다.**

## 스킬 팩토리 — eval이 닫는 루프

> **모델은 제안한다. 증거가 승격시킨다. 사람이 서명한다.**

```bash
bash tools/skill_pipeline.sh "<goal>"            # 생성→품질→검증·충돌·회귀→AI리뷰→사람 게이트 (설치 안 함)
bash tools/skill_pipeline.sh "<goal>" --approve  # 검토 후 설치 (Gate 4)

python3 tools/v9_improve.py            # 개선 제안 — runs.jsonl 실패 이력 자동 환류
python3 tools/v9_eval.py               # 챔피언 vs 도전자 채점 (동점이면 챔피언 유지)
python3 tools/v9_improve.py --approve  # 이긴 후보만 승격 (vN→vN+1, 구버전 아카이브)
```

설계 계약 3개: **생성은 fail-loud, 게이트·비평은 fail-open** · **생성자는 자기를 채점하지 않는다**(eval은 산수 채점) · **`--approve` 없이는 설치·승격 불가**.

## 저장소 구조

```
.claude/
  settings.json          PreToolUse "Edit|Write|MultiEdit" → router.sh
  config.json            게이트 토글·임계값·mode(enforce|warn)
  cache/rules.json       CONVENTIONS.md 컴파일 결과 — Gate 1이 읽음 (10룰)
  hooks/                 router.sh + gate1/2/3 + lib/common.sh
  logs/v9_runs.jsonl     루프 텔레메트리 (git 추적 제외)
tools/
  parse_conventions.py   규칙 컴파일러
  hes_controller.py      [L1] 배치·커밋·CI 컨트롤러
  bench_rules.py         룰 정밀도/재현율 벤치 (+ bench/rule_fixtures.json, 18 픽스처)
  v9_generate.py         [L2] 스킬 생성 + 품질루프
  v9_eval.py             [L2] 챔피언 vs 도전자 채점
  v9_improve.py          [L2] 제안 → 증거 → 승격
  v9/                    메타프롬프트(meta_prompt.md) + eval 고정 goal set(eval_goals.json, 12)
  skill_adapter.py       [L3] 후보 검증·정규화
  skill_integrate.sh     [L4] 검증 → 사람 승인 → 설치
  skill_pipeline.sh      L2→4 단일 명령 (생성→통합)
  ai_review.sh           advisory 리뷰어 (fail-open)
CONVENTIONS.md           규칙 (진실의 원천, Python 5 + Swift 5)
ARCHITECTURE.md          Gate 3가 읽는 아키텍처 문서
src/ tests/              Python 테스트베드 + 도구 회귀 테스트 (pytest 43)
samples/ios/             게이트 검증용 SwiftUI 샘플 (클린 통과 보장)
```

## 기성 도구와의 관계

Ouroboros·Superpowers·gstack 등은 프롬프트/스펙 레이어의 **유도** — 모델이 무시할 수 있다.
HES는 그 아래 마지막 안전망이다: deny JSON이면 쓰기 자체가 막혀 모델이 무시할 수 없고, 비용은
변경당 0~300토큰. **0→1 생성은 그들의 영역, HES는 1→N 유지보수를 grep 우선으로 거의 0토큰에 검증한다.**

## 문서

| 문서 | 내용 |
|---|---|
| [HARNESS.md](./HARNESS.md) | 운영자 가이드 — 게이트 동작 상세·Swift 지원·룰 벤치마크 |
| [USAGE.md](./USAGE.md) | 실전 명령어 — 3가지 모드·규칙 편집·레포 이식·스킬 팩토리 |
| [CONVENTIONS.md](./CONVENTIONS.md) | 강제되는 규칙 (진실의 원천) |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Gate 3가 읽는 아키텍처 문서 |

<sub>설계 근거: [Ouroboros](https://github.com/Q00/ouroboros) · [Superpowers](https://github.com/obra/superpowers) · [gstack](https://github.com/garrytan/gstack) · [Dynamic workflows in Claude Code (Anthropic)](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code) — 실패 모드 명명(instruction decay · self-preferential bias · goal drift)과 "검증은 독립 에이전트가, 제어 흐름은 스크립트가" 원칙을 공유한다.</sub>
