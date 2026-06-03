# Architecture

This is a small, layered Python project. It is intentionally simple so that the
boundaries between layers stay easy to reason about and easy to enforce.

## Layers

- **`src/` — domain logic.** This is where the application's behavior lives. The
  calculator module (`src/calculator.py`) provides the core arithmetic operations
  (add, subtract, multiply, divide). Domain code is the heart of the project and
  should remain free of incidental concerns such as printing, file access, or
  network calls.
- **`tests/` — pytest test suite.** This layer exercises the domain logic. Tests
  import from `src/` and verify behavior. They are the consumers of the domain,
  never the other way around.

## Architectural rules (prose)

- **`src/` must not import from `tests/`.** The dependency direction flows in one
  direction only: tests depend on the domain, and the domain stays unaware that
  any tests exist. A domain module that reaches into the test layer is a design
  error and should be rejected.

- **No business logic in `__init__` files.** Package `__init__.py` modules exist
  to mark packages and, at most, to re-export public names. They must not contain
  arithmetic, branching logic, side effects, or any other meaningful behavior.
  Keep the real logic in dedicated modules where it can be tested directly.

- **Calculator functions stay pure.** The functions in `src/calculator.py` must be
  pure: given the same inputs they always return the same outputs, and they
  perform no I/O and have no side effects. They do not print, log to files, mutate
  global state, read from disk, or touch the network. They simply take numbers in
  and return a result. Purity keeps the domain trivially testable and makes the
  enforced `no-print` convention a natural fit rather than a burden.
