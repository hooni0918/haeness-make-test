# haeness-make-test

파이썬 기본 프로젝트 + 테스트 예제.

## 구조

```
.
├── src/
│   └── calculator.py   # 간단한 계산기 모듈
├── tests/
│   └── test_calculator.py
├── requirements.txt
└── README.md
```

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 테스트 실행

```bash
pytest -v
```
