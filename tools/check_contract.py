"""Check <id>.out files against the competition's output contract.

Reads every `*.out` in a directory and, when an input directory is given, every
`*.in` there too, and asserts the contract RULES.txt states:

  * a regular file (not a link) of at most 65,536 bytes of UTF-8 JSON;
  * one object with exactly one key, `hours`;
  * exactly 23 rows, hours 2..24 each once, in any order;
  * each row exactly {"hour": h, "q": [q05, q25, q50, q75, q95]}, no other key;
  * five finite numbers above 0 and at most 1e9, each at least the one before.

Usage:
    python3 tools/check_contract.py OUT_DIR [INPUT_DIR]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HOURS = list(range(2, 25))
LEVELS = 5
MAX_BYTES = 65536
HIGHEST = 1e9


def check_file(path):
    """(ok, reason) for one output file."""
    if path.is_symlink():
        return False, "is a link, not a regular file"
    if not path.is_file():
        return False, "is not a regular file"
    size = path.stat().st_size
    if size > MAX_BYTES:
        return False, f"is {size} bytes, over {MAX_BYTES}"
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, "is not UTF-8"
    try:
        doc = json.loads(text)
    except ValueError as error:
        return False, f"is not JSON ({error})"
    if not isinstance(doc, dict) or set(doc) != {"hours"}:
        return False, f"top level is not exactly {{'hours'}} (keys {sorted(doc) if isinstance(doc, dict) else type(doc).__name__})"
    rows = doc["hours"]
    if not isinstance(rows, list) or len(rows) != len(HOURS):
        return False, f"hours is not a list of {len(HOURS)} rows"
    seen = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"hour", "q"}:
            return False, f"row {index} is not exactly {{'hour', 'q'}}"
        hour = row["hour"]
        if not isinstance(hour, int) or isinstance(hour, bool):
            return False, f"row {index}'s hour is not an integer"
        seen.append(hour)
        values = row["q"]
        if not isinstance(values, list) or len(values) != LEVELS:
            return False, f"row {index}'s q is not {LEVELS} numbers"
        previous = 0.0
        for value in values:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"row {index} has a non-number quantile"
            if not math.isfinite(value):
                return False, f"row {index} has a non-finite quantile"
            if value <= 0 or value > HIGHEST:
                return False, f"row {index} has {value}, outside (0, 1e9]"
            if value < previous:
                return False, f"row {index}'s quantiles are not non-decreasing"
            previous = value
    if sorted(seen) != HOURS:
        missing = sorted(set(HOURS) - set(seen))
        extra = sorted(set(seen) - set(HOURS))
        return False, f"hours are not 2..24 once each (missing {missing}, extra {extra})"
    return True, f"{size} bytes, 23 rows"


def main(argv):
    if not 2 <= len(argv) <= 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    out_dir = Path(argv[1])
    in_dir = Path(argv[2]) if len(argv) == 3 else None

    outs = sorted(out_dir.glob("*.out"))
    if not outs:
        print(f"no *.out under {out_dir}", file=sys.stderr)
        return 1
    failures = 0
    for path in outs:
        ok, reason = check_file(path)
        print(f"{'PASS' if ok else 'FAIL'}  {path.name:<12} {reason}")
        failures += 0 if ok else 1
    if in_dir is not None:
        ids = sorted(path.stem for path in in_dir.glob("*.in"))
        written = sorted(path.stem for path in outs)
        missing = [name for name in ids if name not in written]
        for name in missing:
            print(f"FAIL  {name + '.out':<12} missing for {name}.in")
        failures += len(missing)
    print(f"\n{len(outs) - failures} of {len(outs)} files pass the contract")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
