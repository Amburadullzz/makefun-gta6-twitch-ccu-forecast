"""Leave-one-out sweep of the dead-air repair and its threshold.

For every comparable in a practice case: hold it out, rebuild the pool from the
whole remaining pool, forecast its own release day through `forecast_case`
exactly as the program would in the final (the held-out launch supplies both
the hour-1 print and the truth for hours 2..24), and score it with the
contest's pinball loss

    item loss = 2 * max(tau * d, (tau - 1) * d),  d = ln(y) - ln(q)

over every scored hour (2..24 that the comparable has a print for) and every
level.  The same 37 launches sit in all four practice cases, so the four cases
produce the same 37 losses; they are scored per case anyway, as the final is.

Two scopes are reported, both as mean and median loss:

  console   the 15 console launches of the pool -- `platforms` naming
            PlayStation or PS5 or Xbox, no PC in the list and not PC-first.
            This is the set whose baseline the brief quotes, and the set the
            final case (a console-only, midnight-rolling launch) belongs to.
  pool      all 37 launches.

The sweep sets `main.DEAD_AIR_REPAIR` and `main.DEAD_AIR_THRESHOLD` and reruns
the whole leave-one-out, so every row is a real program, not a re-derivation.
The `none` rows must reproduce the unrepaired program's 0.2875 / 0.2112 on the
console set and 0.4434 / 0.2851 on the pool; the tool checks that before it
prints anything else and fails loudly if it does not.

Usage:
    python3 tools/dead_air_sweep.py                 # the sweep table
    python3 tools/dead_air_sweep.py --detail        # plus every flagged launch
    python3 tools/dead_air_sweep.py --thresholds 0.2,0.3 --repairs reanchor
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENTRY = HERE.parent

# A target needs a curve with at least this many scored hours to say anything
# about a 23-hour shape.
MIN_TARGET_HOURS = 12

# What the unrepaired program scores on this harness; the `none` row must
# reproduce it to the digit before any comparison counts.
BASELINE_CONSOLE = (0.2875, 0.2112)
BASELINE_POOL = (0.4434, 0.2851)
TOLERANCE = 5e-5


def load_main():
    spec = importlib.util.spec_from_file_location("entry_main", ENTRY / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAIN = load_main()


def is_console_launch(comparable):
    """PlayStation or PS5 or Xbox named, no PC in the list, not PC-first."""
    name = (comparable.get("name") or "").lower()
    if "before release" in name:  # the category's own pre-release history
        return False
    text = (comparable.get("platforms") or "").lower()
    console = "playstation" in text or "ps5" in text or "xbox" in text
    return console and "pc," not in text and not text.startswith("pc")


def synthetic_case(held, others):
    """A case whose target is `held` and whose pool is `others`."""
    curve = MAIN.release_day_curve(held)
    return {
        "id": held.get("name"),
        "day_start": held.get("day_start"),
        "known": [{"hour": MAIN.FIRST_HOUR, "viewers": curve.get(MAIN.FIRST_HOUR)}],
        "comparables": others,
    }


def pinball(rows, truth):
    """Mean pinball loss over the hours and levels that can be scored."""
    total = 0.0
    items = 0
    for row in rows:
        actual = truth.get(row["hour"])
        if actual is None or actual <= 0:
            continue
        y = math.log(actual)
        for tau, q in zip(MAIN.LEVELS, row["q"]):
            d = y - math.log(q)
            total += 2.0 * max(tau * d, (tau - 1.0) * d)
            items += 1
    return total / items if items else None


def score_case(case):
    """(console losses, pool losses, flagged) for one case under the current settings."""
    pool = case.get("comparables") or []
    console, whole = [], []
    for index, held in enumerate(pool):
        curve = MAIN.release_day_curve(held)
        if not curve.get(MAIN.FIRST_HOUR):
            continue
        truth = {hour: curve[hour] for hour in MAIN.FORECAST_HOURS if curve.get(hour)}
        if len(truth) < MIN_TARGET_HOURS:
            continue
        others = pool[:index] + pool[index + 1:]
        forecast = MAIN.forecast_case(synthetic_case(held, others))
        loss = pinball(forecast["hours"], truth)
        if loss is None:
            continue
        whole.append(loss)
        if is_console_launch(held):
            console.append(loss)
    flagged = [(comparable.get("name") or "?",
                MAIN.dead_air_reason(MAIN.release_day_curve(comparable), comparable))
               for comparable in pool
               if MAIN.dead_air_reason(MAIN.release_day_curve(comparable), comparable)]
    return console, whole, flagged


def run(cases, repair, threshold):
    """(console mean, median, n, pool mean, median, n, flagged names)."""
    MAIN.DEAD_AIR_REPAIR = repair
    MAIN.DEAD_AIR_THRESHOLD = threshold
    console, whole, flagged = [], [], []
    for case in cases:
        case_console, case_whole, case_flagged = score_case(case)
        console.extend(case_console)
        whole.extend(case_whole)
        flagged.append(case_flagged)
    return (statistics.mean(console), statistics.median(console), len(console),
            statistics.mean(whole), statistics.median(whole), len(whole),
            flagged[0] if flagged else [])


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", default=str(ENTRY.parent.parent /
                        "kits/gta6-twitch-ccu-forecast-01-kit/input"))
    parser.add_argument("--thresholds", default="0.2,0.3,0.4,0.5,0.6")
    parser.add_argument("--repairs", default="drop,reanchor")
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args(argv)

    thresholds = [float(part) for part in args.thresholds.split(",")]
    repairs = [part.strip() for part in args.repairs.split(",")]
    cases = [json.loads(path.read_text(encoding="utf-8"))
             for path in sorted(Path(args.inputs).glob("*.in"))]
    if not cases:
        raise SystemExit(f"no *.in under {args.inputs}")

    print(f"cases {len(cases)}, comparables per case "
          f"{[len(case.get('comparables') or []) for case in cases]}, "
          f"console launches {sum(is_console_launch(c) for c in cases[0]['comparables'])}")
    print()

    base = run(cases, MAIN.REPAIR_NONE, MAIN.DEAD_AIR_THRESHOLD)
    print(f"unrepaired program: console {base[0]:.4f} / {base[1]:.4f} (n={base[2]}), "
          f"pool {base[3]:.4f} / {base[4]:.4f} (n={base[5]})")
    ok = (abs(base[0] - BASELINE_CONSOLE[0]) < TOLERANCE
          and abs(base[1] - BASELINE_CONSOLE[1]) < TOLERANCE
          and abs(base[3] - BASELINE_POOL[0]) < TOLERANCE
          and abs(base[4] - BASELINE_POOL[1]) < TOLERANCE)
    print(f"reproduces the brief's 0.2875 / 0.2112 and 0.4434 / 0.2851: "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        return 1
    print()

    header = (f"{'repair':>8} {'thr':>4} | {'console mean':>12} {'console med':>11} "
              f"{'n':>3} | {'pool mean':>9} {'pool med':>8} {'n':>3} | {'flag/case':>9}")
    print(header)
    print("-" * len(header))
    print(f"{'none':>8} {'-':>4} | {base[0]:>12.4f} {base[1]:>11.4f} {base[2]:>3d} | "
          f"{base[3]:>9.4f} {base[4]:>8.4f} {base[5]:>3d} | {0:>9d}")
    rows = []
    for repair in repairs:
        for threshold in thresholds:
            console_mean, console_median, n_console, pool_mean, pool_median, n_pool, flagged = \
                run(cases, repair, threshold)
            rows.append((repair, threshold, console_mean, console_median,
                         pool_mean, pool_median, len(flagged)))
            print(f"{repair:>8} {threshold:>4.1f} | {console_mean:>12.4f} "
                  f"{console_median:>11.4f} {n_console:>3d} | {pool_mean:>9.4f} "
                  f"{pool_median:>8.4f} {n_pool:>3d} | {len(flagged):>9d}")

    best = min(rows, key=lambda row: (row[2], row[3]))
    tied = [row for row in rows if row[2] == best[2] and row[3] == best[3]]
    plateau = ", ".join(f"{row[0]} at {row[1]:.1f}" for row in tied)
    print()
    print(f"best console mean: {best[2]:.4f} / {best[3]:.4f} at {plateau}")
    kept = load_main()  # fresh, so the sweep's own assignments do not leak in
    print(f"kept in main.py: DEAD_AIR_REPAIR = {kept.DEAD_AIR_REPAIR!r}, "
          f"DEAD_AIR_THRESHOLD = {kept.DEAD_AIR_THRESHOLD}")

    if args.detail:
        print()
        for repair, threshold in (("none", 0.0), (best[0], best[1])):
            flagged = run(cases, repair, threshold)[6]
            print(f"--- {repair} at {threshold:.1f}: {len(flagged)} flagged")
            for name, reason in flagged:
                print(f"  {name[:45]:45} {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
