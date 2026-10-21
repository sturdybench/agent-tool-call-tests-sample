# Fixtures

| File | Rule | Expected exit |
|---|---|---|
| bad/SL001-missing-type.json | SL001 (ERROR) | 1 |
| bad/SL001-type-string.json | SL001 (ERROR) | 1 |
| bad/SL004-array-no-items.json | SL004 (WARN) | 0 |
| bad/SL004-nested-array.json | SL004 (WARN) | 0 |
| bad/SL007-duplicate-name.json | SL007 (ERROR) | 1 |
| good/good-SL001-object-root.json | none | 0 |
| good/good-SL004-items.json | none | 0 |
| good/good-SL007-unique-names.json | none | 0 |

SL004 is a warning, so it does not change the exit code.
