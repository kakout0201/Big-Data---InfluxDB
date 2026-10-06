"""Unit tests for run_sql.split_statements (no database).

Run: python python/test_run_sql.py
"""

import sys

from run_sql import split_statements

SCRIPT = """-- ==========================
-- header: UTC; giờ VN = UTC+7; not a statement
-- ==========================

-- Query 1: first
SELECT 1 AS a
FROM t
WHERE x = 1   -- inline comment; with a semicolon
;

-- Query 2: second
-- second title line
SELECT 2 AS b;
SELECT 3 AS c
"""


def test_semicolons_in_comments_are_ignored():
    parts = split_statements(SCRIPT)
    assert len(parts) == 3, parts
    assert parts[0][1].startswith("SELECT 1") and "WHERE x = 1" in parts[0][1]
    assert not parts[0][1].rstrip().endswith(";")
    print("[PASS] semicolons inside header and inline comments do not split statements")


def test_titles():
    parts = split_statements(SCRIPT)
    assert parts[0][0] == "Query 1: first", parts[0][0]
    assert parts[1][0] == "Query 2: second | second title line", parts[1][0]
    assert parts[2] == ("", "SELECT 3 AS c"), parts[2]          # last statement without ';'
    print("[PASS] titles come from the comment block directly above each statement")


def main() -> None:
    tests = [test_semicolons_in_comments_are_ignored, test_titles]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"[FAIL] {test.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
