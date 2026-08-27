# Feature: `capitalize` string helper

## Why

`src/strings.js` exposes small, dependency-free string helpers (currently just
`reverse`). Callers repeatedly need to upper-case the first character of a word
for display (labels, headings, generated identifiers). Today they hand-roll
`s[0].toUpperCase() + s.slice(1)`, which is easy to get wrong on empty input.

## Scope

Add one function, `capitalize`, to `src/strings.js` and export it alongside
`reverse`.

### Behaviour

- `capitalize("hello")` → `"Hello"` — upper-case the first character.
- The rest of the string is left exactly as-is: `capitalize("hELLO")` → `"HELLO"`.
- `capitalize("")` → `""` — empty string returns empty, no error.
- `capitalize("123abc")` → `"123abc"` — a non-letter first character is returned unchanged.
- Input is assumed to be a string. Non-string input is out of scope (no runtime
  type checking, no coercion).

### Explicitly out of scope

- Title-casing multiple words.
- Locale-aware casing.
- Trimming or other normalisation.
- Unicode surrogate-pair handling beyond what native `String.prototype.toUpperCase` does.

## Success criteria

- `capitalize` is exported from `src/strings.js`.
- Each behaviour above has a passing test in `src/strings.test.js`.
- `npm test` is green.
