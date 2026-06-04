# haeness-make-test — HES (Harness Enforcement System)

> AI 코딩 에이전트가 컨벤션·아키텍처를 어긴 코드를 파일에 쓰기 전에 결정론적으로 막는
> 계층형 게이트 하네스. Claude Code의 `PreToolUse` 훅 위에 올린 강제 집행 레이어다.

이 저장소는 HES의 0번 계층(Core Runtime) 레퍼런스 구현이자 테스트베드다.
게이트가 실제로 도는 걸 보려고 작은 파이썬 프로젝트(`src/`, `tests/`)를 검증 대상으로 뒀다.

운영·사용법은 [HARNESS.md](./HARNESS.md)에, 실전 명령어는 [USAGE.md](./USAGE.md)에 있다.

---

## 1. HES가 하는 일

```
사용자 지시
   ↓
Claude (AI) ──────────── 코드 생성 / 의사결정
   ↓ 도구 호출 시도 (Edit / Write / MultiEdit)
HES 게이트 (PreToolUse 훅 = 셸 프로세스)  ←── 가드레일이 여기 있다
   ↓ 통과해야만
OS / 파일시스템 ──────── 실제 쓰기
```

훅은 Claude의 의지와 무관하게 셸 프로세스로 실행된다.
게이트가 `deny`를 내면(`permissionDecision: "deny"`) 그 쓰기는 실제로 일어나지 않는다.
모델에게 규칙을 지켜달라고 부탁하는 방식이 아니라, 규칙을 어긴 쓰기가 OS에 닿지 못하게 막는 방식이다.

### 계층형 게이트 (토큰 효율)

```
변경 발생
   ↓
[Gate 1] 셸/grep        ← 0 토큰. 네이밍/금지패턴/필수패턴/줄길이. 유일한 "하드 게이트"
   ↓ 통과
[Gate 2] Haiku          ← ~300 토큰. diff만 전달, 의미적 검토. 기본 OFF, ≥50줄에서만
   ↓ 통과
[Gate 3] Sonnet         ← ~2000 토큰. ARCHITECTURE.md 포함, 구조 판단. 기본 OFF, ≥200줄에서만
   ↓ 통과
[Gate 4] 사람           ← 주요 피처 변경만
```

3대 원칙

1. 규칙은 한 번만 파싱한다. `CONVENTIONS.md`를 `rules.json`으로 캐시해두면 이후 게이트는 LLM 없이 읽기만 한다.
2. LLM 게이트에는 전체 파일이 아니라 변경된 diff만 넘긴다.
3. 게이트는 변경 규모로 고른다. 작은 변경은 Gate 1만 거치고, 큰 변경만 위 게이트로 올라간다.

---

## 2. Ouroboros / Superpowers / GSD / gstack 와 정확히 뭐가 다른가

> 한 줄로 말하면, 이들은 더 나은 코드를 만들게 유도하고 HES는 나쁜 코드가 파일에 닿는 걸 막는다.
> 동작하는 레이어가 다르니 경쟁 관계가 아니라 서로 보완한다(아래 5절).

가장 중요한 축은 모델이 이걸 무시할 수 있느냐다.

| | 동작 레이어 | 모델이 무시 가능? | 주 목적 | 트리거 |
|---|---|---|---|---|
| **HES** (이 repo) | OS 직전 — `PreToolUse` 훅(셸 프로세스) | **불가능.** `exit 2`/`deny`면 쓰기 차단 | 작성 시점에 컨벤션·아키텍처 **강제** (1→N 유지보수) | 모든 파일 쓰기에 **자동** |
| **[Ouroboros](https://github.com/Q00/ouroboros)** | 스펙→생성→검증 파이프라인 (MCP 서버 / Agent OS) | 가능 — 생성 오케스트레이션 자체 | 모호함 제거 + 진화적 **0→1 생성**, 3단계 자동검증 | `seed`/`run` 명시 호출 |
| **[Superpowers](https://github.com/obra/superpowers)** | 스킬 + 서브에이전트 | 가능 — 지시 기반 단계 진행 | **TDD 방법론** 강제(실패하는 테스트 먼저) | 스킬 자동 발동 |
| **GSD** | 페이즈별 오케스트레이터 + 상태파일(Markdown/XML) | 가능 — 슬래시 명령 기반 | **컨텍스트 부패 방지**(환경 격리) | `/gsd-*` 명령 |
| **[gstack](https://github.com/garrytan/gstack)** | 23개 역할 페르소나 + 슬래시 명령 + `CLAUDE.md` | 가능 — 역할별 컨텍스트 제한 | 1인 창업자의 **팀 시뮬레이션**(역할 격리) | `/review` `/ship` 등 명령 |

### 강제성

Ouroboros·Superpowers·GSD·gstack은 모두 프롬프트·스킬·슬래시 명령·스펙 레이어에서 동작한다.
모델에게 건네는 좋은 지시인 셈이라, 모델이 마음먹으면 무시할 수 있다.
컨텍스트가 길어지거나 다른 지시와 부딪히면 실제로 흔들린다.
HES는 셸 훅이라 모델의 협조와 상관없이 실행되고, 게이트를 통과하지 못한 쓰기는 OS에 닿지 못한다.
강제(harness)와 유도(guidance)의 차이가 여기서 갈린다.

### 0→1 생성이냐, 1→N 유지보수냐

- Ouroboros는 생성기다. Socratic 인터뷰로 모호함을 0.2 이하로 줄이고 Seed 스펙을 고정한 뒤,
  실행→3단계 검증(기계적→의미적→멀티모델 합의)→ralph 진화 루프로 수렴시킨다. 0→1에는 강력하지만
  유지보수에서는 작은 변경 하나에도 멀티모델 합의급 검증이 붙어 토큰이 많이 든다.
- HES는 유지보수 게이트다. 변경이 생길 때마다 Gate 1(grep)이 0 토큰으로 먼저 거르고, 필요할 때만
  LLM 게이트로 올린다. 작은 변경 하나에 드는 비용이 0~수백 토큰이라 1→N에 맞다.

### 범위

HES는 좁다. 인터뷰도 계획 수립도 TDD 방법론도 역할 팀 시뮬레이션도 하지 않는다.
이 변경이 우리 컨벤션·아키텍처를 어기는지만 작성 시점에 판정한다.
위 프레임워크들이 개발 과정 전체를 다루는 방법론이라면, HES는 그 과정의 마지막 안전망이다.

### 커스텀과 제어

Ouroboros 같은 도구는 저마다의 워크플로 모델(seed 포맷, 페이즈, 역할 정의)을 따라야 한다.
HES는 셸 스크립트와 JSON 규칙이 전부라 마음대로 고칠 수 있다.
규칙 타입을 추가하거나 게이트 순서를 바꾸거나 회사 전용 검증을 끼워 넣는 일이 파일 몇 개 수정으로 끝난다.

---

## 3. 왜 기성 도구를 안 쓰고 직접 만들었나

1. 커스텀. 기성 도구는 자기 워크플로 모델을 강제해서 사내 컨벤션·아키텍처 검증을 끼워 넣기 어렵다.
2. 유지보수 토큰. Ouroboros는 0→1엔 좋지만 1→N, 즉 매 PR 검증엔 토큰이 과하다. HES는 grep을 먼저 쓰니 거의 0이다.
3. 완전한 제어. 훅·규칙·게이트가 전부 우리 코드라 동작을 끝까지 이해하고 고칠 수 있다.

| 항목 | Ouroboros | HES (직접 구현) |
|---|---|---|
| 0→1 생성 | 강함 | 보통(범위 밖) |
| 1→N 유지보수 토큰 | ~5000 | 0~300 |
| 강제성(모델이 무시 가능?) | 가능 | **불가능** |
| 커스텀 | 제한적 | 완전 자유 |

---

## 4. HES 계층 아키텍처 (로드맵: 0 → 4)

> 전체 구상이다. 이 저장소는 0번(Core Runtime)을 구현했고,
> 1~4번은 HES를 v9 메타프롬프트·스킬 자가개선 파이프라인과 안전하게 잇는 상위 계층이다.

```
0. HES Core Runtime          [이 repo: 구현 완료]
   └ PreToolUse 게이트 런타임(router + gate1/2/3 + rules.json). "나쁜 쓰기"를 OS 직전에서 차단.

1. HES Automation Controller  [상위 계층]
   └ HES의 자동 실행·검증·승인 자동화. 게이트 결과를 수집/판정/라우팅하는 컨트롤러.

2. V9 Auto-Improvement Lane   [상위 계층]
   └ v9 메타프롬프트가 자기 자신을 개선하는 전용 하네스(자가개선 루프).

3. V9 Skill Authoring Adapter [상위 계층]
   └ v9이 만든 프롬프트를 "스킬 후보"로 변환하는 어댑터.

4. V9-HES Integration Bridge  [상위 계층]
   └ 2번(개선된 v9) + 3번(스킬 후보) 결과물을 HES에 안전하게 연결하는 브리지.
```

### 스킬 생성 → 통합까지의 흐름 (사용자 구상 그대로)

```
v9 가 스킬을 만든다
        ↓
v9 하네스가 1차 품질 검토             (2. Auto-Improvement Lane)
        ↓
HES 가 역할·충돌·회귀 검증            (0. Core Runtime + 1. Automation Controller)
        ↓
AI Reviewer 가 승인/반려 의견          (1. Automation Controller)
        ↓
사용자가 최종 승인                     (Gate 4 = 사람)
        ↓
HES 에 통합                            (4. V9-HES Integration Bridge)
```

이 구조가 맞다. 핵심은 생성(v9)과 강제 검증(HES)을 떼어놓고, 그 사이를 게이트(품질→역할·충돌·회귀→AI리뷰→사람)로 잇는 데 있다. 위 2절의 '생성 대 강제'를 그대로 파이프라인으로 옮긴 셈이다. 새 스킬은 HES 게이트를 통과해야만 통합되니, v9이 자가개선으로 무엇을 만들어내든 검증을 거치지 않은 스킬이 시스템에 들어올 길이 없다.

> 1~4번은 이 저장소 밖, 상위 HES 프로젝트(예: iOS `ios-qube`)에서 구현한다.
> 이 repo는 그 토대인 0번 게이트 런타임이 실제로 도는지를 보여준다.

---

## 5. 함께 쓰기 (상호 보완)

HES는 위 프레임워크를 대체하지 않는다. 그 아래 깔리는 안전망으로 함께 쓰면 된다.

```
[Superpowers / gstack / Ouroboros 로 코드 생성]   ← 좋은 코드를 "만들게" 유도
                  ↓ Edit/Write/MultiEdit
[HES 게이트]                                       ← 컨벤션·아키텍처 위반을 "막음"(결정론적)
                  ↓ 통과분만
              파일시스템
```

생성 도구가 무엇을 쓰든 마지막에 HES가 회사 규칙을 강제한다.

---

## 6. 저장소 구조

```
.
├── .claude/
│   ├── settings.json            # PreToolUse "Edit|Write|MultiEdit" → router.sh 연결
│   ├── config.json              # 게이트 토글·임계값·source/ignore globs·mode(enforce|warn)
│   ├── cache/rules.json         # 기계가독 규칙 (CONVENTIONS.md에서 파싱)
│   ├── logs/                    # gates.log (런타임 감사 로그, git 추적 제외)
│   └── hooks/
│       ├── router.sh            # 단일 진입점: stdin 1회 읽고 단 하나의 결정 emit
│       ├── gate1-shell.sh       # grep 검사 (0토큰, 유일한 하드 게이트)
│       ├── gate2-semantic.sh    # Haiku + diff (기본 OFF, fail-open, ≥50줄)
│       ├── gate3-architect.sh   # Sonnet + ARCHITECTURE.md (기본 OFF, ≥200줄)
│       └── lib/common.sh        # hes_deny/allow/inform/log/root 헬퍼
├── tools/
│   ├── parse_conventions.py     # CONVENTIONS.md rule 블록 → rules.json
│   ├── hes_controller.py        # Layer 1: 배치 게이트 컨트롤러 (--staged/--files/--range)
│   ├── ai_review.sh             # AI Reviewer (advisory, fail-open)
│   ├── skill_adapter.py         # Layer 3: 스킬 후보 검증·정규화
│   ├── skill_integrate.sh       # Layer 4: 검증→사람 승인(--approve)→설치
│   ├── install-git-hooks.sh     # pre-commit 훅 설치
│   └── git-hooks/pre-commit     # 커밋마다 컨트롤러 실행
├── CONVENTIONS.md               # 사람용 규칙 + 파싱가능 rule 블록
├── ARCHITECTURE.md              # gate3가 읽는 아키텍처 컨텍스트
├── HARNESS.md                   # 운영 가이드 + 수동 테스트 스니펫
├── USAGE.md                     # 실전 사용법 (3가지 모드)
│
├── src/calculator.py            # 게이트 검증 "대상" (테스트베드 소스)
└── tests/test_calculator.py     # pytest
```

## 7. 빠른 테스트

```bash
# 막히는 케이스 — print() 는 컨벤션 위반 → deny
jq -nc --arg fp "$PWD/src/calculator.py" \
  --arg c $'def f():\n    print("x")\n    return 1\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
# → permissionDecision: "deny"

# 통과 케이스 — 깨끗한 코드 → 빈 출력(allow)
jq -nc --arg fp "$PWD/src/calculator.py" \
  --arg c $'"""mod."""\n\n\ndef f():\n    return 1\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' | bash .claude/hooks/router.sh
```

이 저장소를 Claude Code로 열면 파일을 쓸 때마다 위 게이트가 자동으로 걸린다.
동작 로그는 `.claude/logs/gates.log`에 남는다.

### 테스트베드(파이썬) 자체 실행

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```

---

## 사용법

실전 명령어는 [USAGE.md](./USAGE.md)에 복붙 가능한 형태로 정리해뒀다. 세 가지 모드다.

- **MODE A — Claude Code 안에서 (자동):** 이 레포를 Claude Code로 열면 `PreToolUse` 훅이 매 `Edit/Write/MultiEdit` 를 자동 게이트한다.
- **MODE B — git commit 마다 (자동):** `bash tools/install-git-hooks.sh` 1회 설치 → 이후 error 위반 커밋을 차단(`--no-verify` 로 우회).
- **MODE C — 배치 / CI / 수동 리뷰:** `python3 tools/hes_controller.py --staged | --files … | --range main..HEAD [--json] [--ai-review]` (REJECTED 시 exit 1).

---

### Sources

프레임워크 비교의 근거 자료:
- Ouroboros — https://github.com/Q00/ouroboros
- gstack (Garry Tan) — https://github.com/garrytan/gstack
- Superpowers (obra/Jesse Vincent) — https://github.com/obra/superpowers
- 프레임워크 비교 분석 — https://www.pulumi.com/blog/claude-code-orchestration-frameworks/
