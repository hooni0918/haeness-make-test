"""간단한 계산기 모듈."""


def add(a: float, b: float) -> float:
    """두 수를 더한다."""
    return a + b


def subtract(a: float, b: float) -> float:
    """두 수를 뺀다."""
    return a - b


def multiply(a: float, b: float) -> float:
    """두 수를 곱한다."""
    return a * b


def divide(a: float, b: float) -> float:
    """두 수를 나눈다. 0으로 나누면 ZeroDivisionError를 발생시킨다."""
    if b == 0:
        raise ZeroDivisionError("0으로 나눌 수 없습니다.")
    return a / b
