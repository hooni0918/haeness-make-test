# Coding Conventions

These conventions are **ENFORCED** by the HES (Hook-Enforced Standards) gate harness.
When you Edit, Write, or MultiEdit a source file, a PreToolUse hook intercepts the
proposed content *before* it is written and runs a series of gates against it.
Gate 1 is a pure shell/grep pass (0 tokens) that evaluates the machine-readable rule
blocks below. Hard (error-severity) violations cause the write to be **denied**.

The prose in this file explains the intent; the fenced `rule` blocks under
"Rules (machine-readable)" are the source of truth that the harness parses into
`.claude/cache/rules.json`.

## Principles

- **Prefer logging over `print()`.** Diagnostic output belongs in the `logging`
  module, not in `print()` calls. `print()` is forbidden in source files.
- **Use explicit imports — no wildcards.** Never write `from module import *`.
  Import the specific names you use so dependencies stay visible and tooling works.
- **Write module docstrings.** Every module should begin with a `"""docstring"""`
  describing what it contains.
- **Keep lines reasonable.** Lines should be at most 100 columns wide.
- **Use snake_case Python filenames.** Python file basenames should match
  `snake_case` (lowercase letters, digits, and underscores).

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

## Swift / iOS conventions

iOS 소스(`*.swift`)에도 같은 게이트가 적용된다. 아래 규칙은 SwiftLint 류 정적분석과
같은 의도를 0 토큰 grep으로 작성 시점에 강제한다. 정규식은 ugrep·BSD grep·GNU grep
세 엔진에서 동작하도록 분기형(`^kw!|[^word]kw!`)으로 작성했다.

- **`print()` 대신 `Logger`.** 진단 출력은 `os`의 `Logger`로 남긴다. 릴리스 빌드에
  콘솔 로그가 새지 않게 하기 위함이다.
- **강제 캐스트(`as!`) 금지.** `as?` + 옵셔널 바인딩으로 실패를 흡수한다.
- **강제 try(`try!`) 금지.** `do`/`catch` 또는 `try?`로 에러를 다룬다.
- **강제 언래핑(`!`) 경고.** 휴리스틱 warn. 옵셔널 바인딩/`guard`로 대체할 수 있는지
  검토하라는 신호이지 무조건 차단은 아니다(오탐 가능성을 인정한 의도적 warn).
- **줄 길이 120자.** SwiftLint 기본값과 맞춘다.

## Swift rules (machine-readable)

```rule
id: swift-no-print
severity: error
applies: *.swift
type: forbid_pattern
pattern: (^|[^a-zA-Z_.])print[[:space:]]*\(
message: print() 는 금지입니다. os의 Logger 를 사용하세요
```

```rule
id: swift-no-force-cast
severity: error
applies: *.swift
type: forbid_pattern
pattern: (^as!|[^A-Za-z0-9_]as!)
message: 강제 캐스트(as!) 는 금지입니다. as? 와 옵셔널 바인딩을 쓰세요
```

```rule
id: swift-no-force-try
severity: error
applies: *.swift
type: forbid_pattern
pattern: (^try!|[^A-Za-z0-9_]try!)
message: 강제 try(try!) 는 금지입니다. do/catch 또는 try? 를 쓰세요
```

```rule
id: swift-no-force-unwrap
severity: warn
applies: *.swift
type: forbid_pattern
pattern: []A-Za-z0-9_)]!([^=]|$)
message: 강제 언래핑(!) 의심. 옵셔널 바인딩이나 guard 로 대체할 수 있는지 검토하세요
```

```rule
id: swift-max-line-120
severity: warn
applies: *.swift
type: max_line_length
max: 120
message: 줄이 120자를 초과합니다 (SwiftLint 기본값)
```
