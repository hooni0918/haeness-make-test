# HES — Harness Enforcement System

> 모델에게 규칙을 **부탁하지 않는다.** 규칙을 어긴 쓰기를 디스크 직전에서 **차단한다.**
> Claude Code `PreToolUse` 훅 위에서 도는 강제 집행 레이어 — guidance가 아니다.

## 이게 하는 일

핵심은 하나다 — **코드 규칙 강제 게이트.** 누군가(주로 Claude)가 `print()` 같은 금지
패턴이 든 코드를 쓰려고 하면 **저장되기 직전에 막는다.** "print 쓰지 마"라고 *부탁*하는 게
아니라, 셸 훅이 OS 레벨에서 *차단*한다. 게이트를 통과 못 한 `Edit/Write/MultiEdit`는
파일시스템에 닿지 않는다.

> 팀 컨벤션을 `CLAUDE.md`에 적고 "지켜주세요"라고 비는 대신, 규칙을 셸 훅으로 박아
> **안 지키면 물리적으로 못 쓰게** 한다.

이게 전부다. **스킬 팩토리(Layer 2–4)는 곁다리** — "이 게이트 방식을 스킬 자동생성
루프에도 똑같이 붙여봤다"는 데모 겸 부가기능이고, 스킬을 자동으로 찍어낼 일이 없으면
[맨 아래 섹션](#-스킬-팩토리-옵션--eval이-닫는-자가개선-루프)을 통째로 무시해도 된다.

## 구조 한눈에

두 부분이다. **강제집행(0–1)** 이 위에서 말한 핵심 게이트(이미 구축 완료),
**스킬 팩토리(2–4)** 는 그 위에 얹은 옵션.

```
강제집행 — 핵심, 매 편집마다 작동
  0  Core Runtime           → PreToolUse 훅이 위반 쓰기를 OS 직전 차단
  1  Automation Controller  → 배치·커밋·CI에서 같은 게이트를 실행·판정

스킬 팩토리 — 옵션, 안 써도 됨
  2  V9 Lane                → 스킬 생성 + 품질루프 + 메타프롬프트 자가개선
  3  Skill Adapter          → 만들어진 스킬 후보를 검증·정규화
  4  Integration Bridge     → 충돌·회귀·AI리뷰·사람승인 후 설치
```

> ⚠️ **0–1과 2–4는 순차 단계가 아니다.** "1에서 막히면 2로 넘어간다" 같은 흐름은 없다 —
> 강제집행과 스킬 팩토리는 목적이 다른 별개 시스템이고, 각자 따로 트리거된다.

| 레이어 | 어떻게 켜지나 (트리거) |
|---|---|
| **0** 게이트 | Claude Code가 편집할 때 **자동** (PreToolUse 훅) |
| **1** 컨트롤러 | `git commit`(훅 설치 시) · CI(`--range`) · 수동(`--files`/`--staged`) |
| **2** V9 | `skill_pipeline.sh "<goal>"` · `v9_*` — **수동 실행만** |
| **3** 어댑터 | 2·4 안에서 **자동 호출** (또는 단독 `skill_adapter.py`) |
| **4** 브릿지 | `skill_integrate.sh … --approve` |

## 사용법

### A. 이 레포에서 동작만 구경 (지금 바로)

```bash
# print() 든 코드를 쓰려고 하면 → 차단(deny)
jq -nc --arg fp "$PWD/src/calculator.py" --arg c $'def f():\n    print("x")\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
# → {"hookSpecificOutput":{"permissionDecision":"deny", ...}}

# 깨끗한 코드는 무출력 통과(allow)
jq -nc --arg fp "$PWD/src/calculator.py" --arg c $'"""m."""\n\n\ndef f():\n    return 1\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
```

### B. 내 프로젝트에 적용 (← 진짜 용도)

1. **복사** — `.claude/` 통째로(`settings.json`·`config.json`·`hooks/`·`cache/`) + `CONVENTIONS.md` + `tools/parse_conventions.py`. git/CI까지 쓰려면 `tools/hes_controller.py`·`install-git-hooks.sh`·`git-hooks/`도.
2. **규칙 교체** — `CONVENTIONS.md`의 예제 10룰을 우리 팀 규칙으로 수정.
3. **컴파일** — `python3 tools/parse_conventions.py`. 훅은 Markdown이 아니라 컴파일된 `rules.json`을 읽으니 **규칙 바꿀 때마다 필수.**
4. **작동** — 셋 중 원하는 방식으로:

```bash
# Claude Code 안에서: 레포 열면 끝 — Claude가 편집할 때마다 쓰기 직전 자동 게이트
# git 커밋마다:
bash tools/install-git-hooks.sh                              # 1회 설치
# CI 파이프라인:
python3 tools/hes_controller.py --range <base>..HEAD --json  # 위반 있으면 exit 1
```

## 게이트 사다리

변경은 싼 순서로 게이트를 오른다. 대부분의 편집은 Gate 1(0토큰)에서 끝난다.

| Gate | 엔진 | 비용 | 잡는 것 | 조건 |
|---|---|---|---|---|
| **1** | 셸 grep vs `rules.json` | **0 토큰** | 금지/필수 패턴·줄길이·파일명 (10룰) | **항상 ON** |
| **2** | Haiku (diff) | ~300 토큰 | 정규식이 못 보는 의미적 결함 | ≥50줄 + 켜야 함 |
| **3** | Sonnet (+`ARCHITECTURE.md`) | 수천 토큰 | 레이어·경계·결합 드리프트 | ≥200줄 + 켜야 함 |
| **4** | 사람 | — | 기계가 못 정하는 것 | 스킬·프롬프트 승격 승인 |

- **하드 보장은 Gate 1뿐** (fail-open 상세는 아래 [신뢰성 설계](#왜-믿을-수-있나--신뢰성-설계)).
- **단락(short-circuit).** enforce 모드에서 싼 게이트가 `error`를 내면 LLM 게이트는 스킵 — 사다리는 첫 실패 단에서 멈춘다.
- **점진 도입.** `config.json`의 `mode:"warn"` — 차단 없이 경고만.
- **막혔을 때.** 코드를 고치거나 · 규칙이 틀렸으면 `CONVENTIONS.md` 수정 → 재컴파일 · 급하면 `warn` 모드·`git commit --no-verify`로 우회. **Layer 2–4로 "넘어가는" 길은 없다** — 거긴 스킬 공장이지 규칙 우회로가 아니다.

## 규칙 — 추가는 3줄, 채택은 측정으로

`CONVENTIONS.md`의 rule 블록이 진실의 원천. 룰 타입 4종(`forbid_pattern`·`require_pattern`·
`max_line_length`·`filename_pattern`)은 glob+정규식만 보므로 언어 무관. 현재 10룰(Python 5 + Swift 5).

```bash
python3 tools/parse_conventions.py   # CONVENTIONS.md → .claude/cache/rules.json
python3 tools/bench_rules.py         # FP/FN 0 강제 (현재 18/18 CLEAN), pytest에 연결됨
```

규칙을 추가하면 라벨링 픽스처(`tools/bench/rule_fixtures.json`)도 같이 추가한다 —
**규칙은 감이 아니라 측정으로 채택한다.**

## 왜 믿을 수 있나 — 신뢰성 설계

LLM 에이전트가 컨벤션을 어기는 방식은 세 가지로 반복된다. HES는 각각을 프롬프트가 아니라 **구조**로 막는다.

### 1. Instruction decay — 규칙을 잊는다
`CLAUDE.md`의 "print() 금지"는 컨텍스트가 길어질수록 잊힌다. 그건 *부탁*이니까.
→ **규칙을 모델 밖으로 꺼낸다.** 훅은 OS가 돌리는 셸 프로세스라 모델의 기억과 무관하게 매번 실행되고, 게이트 미통과 쓰기는 디스크에 닿지 못한다. Gate 1은 `config`로 끌 수조차 없는 유일한 하드 게이트다.

### 2. Self-preferential bias — 자기가 만든 걸 자기가 검증하면 심판을 속인다
생성자가 채점까지 겸하면 루프는 "더 나은 코드"가 아니라 "심판을 속이는 코드" 쪽으로 진화한다.
→ **검증을 생성에서 떼어낸다.** 판정 1순위는 LLM 의견이 아니라 **결정론 신호** — grep · 구조 검증 · `pytest` · 게이트 통과율. 자가개선 루프(Layer 2–4)에서도 같은 원칙을 강제한다:

- **생성자 ≠ 심판.** eval은 모델 판단이 아니라 **산수**로 채점한다 — 구조 유효 개수 → 잔여 문제 수 → 수정 라운드 수, 이 우선순위 그대로.
- **챔피언(현행) vs 도전자(후보)** 를 같은 고정 goal set에 돌려 비교하고, **동점이면 챔피언 유지** — 증거 없이는 절대 갈아끼우지 않는다.
- 승격은 평가 결과(verdict)의 **`challenger_sha256`가 지금 후보와 일치할 때만** 인정 — 낡은 평가를 재탕해 통과시키는 걸 차단한다.
- LLM 리뷰어(`ai_review.sh`)는 보조 의견일 뿐: 판정을 **REJECTED로 강등만** 할 수 있고 통과로 승격은 못 한다. CLI가 죽어도 항상 통과(fail-open)라, 검증 부가물 고장이 게이트를 무력화하지 못한다.
- **최종 서명은 사람.** `--approve` 없이는 어떤 스킬·프롬프트도 설치·승격되지 않는다.

### 3. Goal drift · agentic laziness — 긴 루프가 목표를 이탈하거나 중도 포기한다
→ **제어 흐름을 모델 재량에서 뺏는다.** 생성→검증→승격은 스크립트가 집행하는 결정론 파이프라인이고, 모델은 그 안의 한 단계일 뿐. 단계 순서도 통과 조건도 모델이 바꿀 수 없다.

### + 하네스가 자기 자신을 검증한다
`bench_rules.py`가 18개 라벨 픽스처로 각 규칙의 정밀도/재현율을 측정해 **오탐·미탐이 하나라도 있으면 실패**하고, 이게 `pytest`(43개)에 물려 있다. 규칙 품질을 감이 아니라 측정으로 보증한다.

**신뢰성 비대칭 한 줄 요약:** 생성은 **fail-loud**(모델 없이는 만들 게 없으니 크게 실패), 검증 부가물(LLM 게이트·비평·AI리뷰)은 **fail-open**(죽어도 결정론 게이트의 보호는 그대로). 하드 보장은 언제나 Gate 1.

## 직접 확장·자작한다면 — 설계 원칙

HES를 고치거나 비슷한 하네스를 새로 만들 때, 무너지지 않게 하는 단 하나의 법칙:
**생성자와 판사를 분리하고, 판사는 생성자가 못 속이는 것에 묶어둔다.**

### 판사 ↔ 생성자 방화벽

게이트(0–1)는 *판사*, LLM 루프(2–4)는 *생성자*다. "게이트가 자주 막는 걸 신호로
LLM이 규칙을 다시 생성하게 하면 되잖아?"는 자연스러운 발상이지만 — 그 루프는
"더 좋은 규칙"이 아니라 **"나를 안 막는 규칙"** 쪽으로 진화한다(self-preferential bias).
**판사를 죄수가 다시 쓰게 하는 꼴.** 그래서 HES는 코드 게이트의 규칙을 LLM이 자동으로
다시 쓰지 못하게 막아둔다. 규칙 개선은 사람이 `CONVENTIONS.md`를 고치고
`bench_rules.py`가 정탐/오탐을 *측정*해 검증하는 — **결정론 + 사람** 경로로만 일어난다.

### 자기개선 루프를 안전하게 만드는 부품 3개

그래도 "막힌 패턴을 모아 규칙을 자동 개선"하고 싶다면, 이 셋이 반드시 분리돼야 한다:

1. **제안은 LLM** — 규칙/구조 변경을 *제안만* 한다.
2. **검증은 독립된 정답(ground truth)** — 모델이 못 속이는 고정 기준으로 채점. HES의 `rule_fixtures.json`(라벨링 18개)이 그 앵커다. 오탐/미탐 0을 못 지키면 자동 탈락.
3. **승격은 사람** — 최종 `--approve`.

HES의 `v9 propose → eval → approve` 기계가 정확히 이 패턴이다(단, **현재는 *스킬* 생성에만** 적용).
규칙에도 쓰려면: 게이트가 자주 막는 케이스 + 픽스처 → 새 규칙 *제안* → `bench` *검증* → 사람 *승인*.
**게이트가 자기 규칙을 조용히 다시 쓰게만 하지 않으면 된다.**

### 하네스 3분류 (남이 만드는 방식)

- **결정론형** (린터·타입체커·HES Gate 1): 사람이 규칙 작성, 기계가 강제. 빠르고 못 속임, 대신 표현력 한계.
- **LLM-판사형**: 똑똑하지만 *반드시* 생성자와 분리 + 정답 앵커가 있어야 안 무너진다.
- **자기진화형** (Ouroboros 같은 evolve 루프, AlphaEvolve류): 제안→테스트→선택 반복. **고정 fitness(정답/held-out 테스트) + 사람 게이트**가 없으면 결국 벤치를 외워버린다(overfit).

## 🔁 스킬 팩토리 (옵션) — eval이 닫는 자가개선 루프

> 스킬을 자동 생성·개선할 때만 쓴다. 핵심 게이트만 쓸 거면 이 섹션은 건너뛰어도 된다.

스킬 하나가 만들어져 설치되기까지의 흐름:

```
v9 스킬 생성 ─▶ v9 품질루프 ─▶ 어댑터 검증 ─▶ HES 충돌·회귀 ─▶ AI 리뷰 ─▶ 사람 --approve ─▶ 설치
    (L2)          (L2)          (L3)           (L4)           (L4)        (L4)            (L4)
```

> 스킬을 **"만드는"** 건 Layer 2(`v9_generate`)다. Layer 3 어댑터는 만든 후보를 **검증·정규화만** 한다.

```bash
bash tools/skill_pipeline.sh "<goal>"            # 생성→품질→검증·충돌·회귀→AI리뷰→사람 게이트 (설치 안 함)
bash tools/skill_pipeline.sh "<goal>" --approve  # 검토 후 설치 (Gate 4)

python3 tools/v9_improve.py            # 개선 제안 — runs.jsonl 실패 이력 자동 환류
python3 tools/v9_eval.py               # 챔피언 vs 도전자 채점 (동점이면 챔피언 유지)
python3 tools/v9_improve.py --approve  # 이긴 후보만 승격 (vN→vN+1, 구버전 아카이브)
```

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
