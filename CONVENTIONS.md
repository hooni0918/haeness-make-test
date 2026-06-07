# 코딩 컨벤션

이 컨벤션은 HES(Hook-Enforced Standards) 게이트 하네스가 **강제**한다.
소스 파일을 Edit, Write, MultiEdit 하면 PreToolUse 훅이 쓰기 *직전에* 제안된 내용을
가로채 일련의 게이트를 돌린다. Gate 1은 순수 셸/grep 패스(0토큰)로, 아래 기계가독
rule 블록을 평가한다. 하드(error 등급) 위반이 나오면 그 쓰기는 **거부**된다.

이 파일의 산문은 의도를 설명한다. "Rules (machine-readable)" 아래의 `rule` 펜스
블록이 진실의 원천이고, 하네스는 이걸 파싱해 `.claude/cache/rules.json`으로 만든다.

## Principles

- **`print()`보다 로깅을 쓴다.** 진단 출력은 `print()`가 아니라 `logging`
  모듈에 둔다. 소스 파일에서 `print()`는 금지다.
- **import는 명시적으로 — 와일드카드 금지.** `from module import *`는 절대 쓰지 않는다.
  쓰는 이름만 골라서 import해야 의존성이 드러나고 도구도 제대로 돈다.
- **모듈 docstring을 쓴다.** 모든 모듈은 무엇이 들었는지 설명하는 `"""docstring"""`으로
  시작한다.
- **줄 길이는 적당히.** 한 줄은 최대 100칸까지다.
- **파이썬 파일명은 snake_case로.** 파이썬 파일 베이스명은
  `snake_case`(소문자·숫자·밑줄)에 맞춘다.

## Rules (machine-readable)

```rule
id: no-print
severity: error
applies: *.py
type: forbid_pattern
pattern: (^|[^a-zA-Z_.])print[[:space:]]*\(
message: print() is forbidden — use the logging module
```

```rule
id: no-wildcard-import
severity: error
applies: *.py
type: forbid_pattern
pattern: ^[[:space:]]*from[[:space:]]+[^[:space:]]+[[:space:]]+import[[:space:]]+\*
message: wildcard imports (from x import *) are forbidden
```

```rule
id: module-docstring
severity: warn
applies: *.py
type: require_pattern
pattern: """
message: module should start with a docstring
```

```rule
id: max-line-100
severity: warn
applies: *.py
type: max_line_length
max: 100
message: line exceeds 100 characters
```

```rule
id: py-snake-case-file
severity: warn
applies: *.py
type: filename_pattern
pattern: ^[a-z_][a-z0-9_]*\.py$
message: Python files should be snake_case
```
