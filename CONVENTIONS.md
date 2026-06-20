# 코딩 컨벤션

이 컨벤션은 HES(Hook-Enforced Standards) 게이트 하네스가 **강제**한다. 소스 파일을 Edit, Write, MultiEdit 하면 PreToolUse 훅이 쓰기 직전에 제안된 내용을 가로채 일련의 게이트를 돌린다. Gate 1은 순수 셸/grep 패스(0토큰)로, 아래 기계가독 rule 블록을 평가한다. 하드(error 등급) 위반이 나오면 그 쓰기는 **거부**된다.

이 파일의 산문은 의도를 설명한다. "규칙 (machine-readable)" 아래의 `rule` 펜스 블록이 진실의 원천이고, 하네스는 이걸 파싱해 `.claude/cache/rules.json`으로 만든다.

## 원칙

- **`print()`보다 로깅을 쓴다.** 진단 출력은 `print()`가 아니라 `logging` 모듈에 둔다. 소스 파일에서 `print()`는 금지다.
- **import는 명시적으로 쓰고 와일드카드는 금지한다.** `from module import *`는 절대 쓰지 않는다. 쓰는 이름만 골라서 import해야 의존성이 드러나고 도구도 제대로 돈다.
- **모듈 docstring을 쓴다.** 모든 모듈은 무엇이 들었는지 설명하는 `"""docstring"""`으로 시작한다.
- **줄 길이는 적당히.** 한 줄은 최대 100칸까지다.
- **파이썬 파일명은 snake_case로.** 파이썬 파일 베이스명은 `snake_case`(소문자, 숫자, 밑줄)에 맞춘다.

## 규칙 (machine-readable)

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

## Swift / iOS 컨벤션

iOS 소스(`*.swift`)에도 같은 게이트가 적용된다. 아래 규칙은 SwiftLint 류 정적분석과 같은 의도를 0 토큰 grep으로 작성 시점에 강제한다. 정규식은 ugrep, BSD grep, GNU grep 세 엔진에서 동작하도록 분기형(`^kw!|[^word]kw!`)으로 작성했다.

- **`print()` 대신 `Logger`.** 진단 출력은 `os`의 `Logger`로 남긴다. 릴리스 빌드에 콘솔 로그가 새지 않게 하기 위함이다.
- **강제 캐스트(`as!`) 금지.** `as?`와 옵셔널 바인딩으로 실패를 흡수한다.
- **강제 try(`try!`) 금지.** `do`/`catch` 또는 `try?`로 에러를 다룬다.
- **강제 언래핑(`!`) 경고.** 휴리스틱 warn이다. 옵셔널 바인딩이나 `guard`로 대체할 수 있는지 검토하라는 신호이지 무조건 차단은 아니다(오탐 가능성을 인정한 의도적 warn).
- **줄 길이 120자.** SwiftLint 기본값과 맞춘다.

## Swift 규칙 (machine-readable)

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
