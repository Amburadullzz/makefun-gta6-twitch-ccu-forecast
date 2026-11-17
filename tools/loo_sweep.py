"""Leave-one-out sweep over the platform-similarity exponent.

Hold each comparable of a case out, rebuild the pool without it, forecast its
own release day from the rest exactly as `main.py` does (the held-out launch
supplies both the hour-1 print and the truth for hours 2..24), and score the
forecast with the contest's pinball loss:

    item loss = 2 * max(tau * d, (tau - 1) * d),  d = ln(y) - ln(q)

over every scored hour (2..24 that the comparable has a print for) and every
level.  The sweep reports mean and median loss over the whole pool and over the
console launches alone, for a range of PLATFORM_EXPONENT settings.

Two pool conventions are reported for the console scope:

  --pool all       the pool the program actually sees: every other comparable
                   (this is what a change to main.py really does)
  --pool console   the console launches only, the convention the brief's
                   baseline numbers were measured under (it reproduces them)

Usage:
    python3 tools/loo_sweep.py                       # whole pool, exp sweep
    python3 tools/loo_sweep.py --pool console        # console-only pool
    python3 tools/loo_sweep.py --exponents 0,0.5,1,2 --detail
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
# about a 23-hour shape; the brief's console pool is the 15 that clear it.
MIN_TARGET_HOURS = 12


def load_main():
    spec = importlib.util.spec_from_file_location("entry_main", ENTRY / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAIN = load_main()


# --------------------------------------------------------------------------
# Which comparables count as console launches
# --------------------------------------------------------------------------

def is_console_launch(comparable, rule="clean"):
    """PlayStation or Xbox named, PC not leading and not listed ahead.

    This is the console pool the brief measures against: a launch whose
    `platforms` string names PlayStation or Xbox and neither starts with PC nor
    carries a PC mid-list.  The GTA VI category's own pre-release history rides
    in every case as a comparable; it is a category, not a launch, so it is not
    a target here.

    `rule="brief"` narrows the match to the brief's own string test, which
    reads "PlayStation" or "PS5" but not "PS4", and so leaves the two PS4-only
    launches (The Last of Us Part II, Ghost of Tsushima) out: that is the 15
    whose baseline the brief quotes.
    """
    name = (comparable.get("name") or "").lower()
    if "before release" in name:
        return False
    text = (comparable.get("platforms") or "").lower()
    if rule == "brief":
        console = "playstation" in text or "ps5" in text or "xbox" in text
    else:
        console = MAIN.names_playstation(text) or MAIN.names_xbox(text)
    return console and "pc," not in text and not text.startswith("pc")


# --------------------------------------------------------------------------
# One leave-one-out forecast
# --------------------------------------------------------------------------

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
        hour = row["hour"]
        actual = truth.get(hour)
        if actual is None or actual <= 0:
            continue
        y = math.log(actual)
        for tau, q in zip(MAIN.LEVELS, row["q"]):
            d = y - math.log(q)
            total += 2.0 * max(tau * d, (tau - 1.0) * d)
            items += 1
    return total / items if items else None


def score_case(case, exponent, pool_mode, console_rule="clean"):
    """(name, loss, comparable) for every comparable that can be held out."""
    MAIN.PLATFORM_EXPONENT = exponent
    pool = case.get("comparables") or []
    if pool_mode == "console":
        pool = [comparable for comparable in pool
                if is_console_launch(comparable, console_rule)]
    scored = []
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
        if loss is not None:
            scored.append((held.get("name") or "?", loss, held))
    return scored


def summarise(losses):
    values = [loss for _, loss, _ in losses]
    if not values:
        return None
    return statistics.mean(values), statistics.median(values), len(values)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", default=str(ENTRY.parent.parent /
                        "kits/gta6-twitch-ccu-forecast-01-kit/input"))
    parser.add_argument("--exponents", default="0,0.5,1,2,3")
    parser.add_argument("--pool", default="all", choices=("all", "console"))
    parser.add_argument("--console-rule", default="clean", choices=("clean", "brief"))
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args(argv)

    exponents = [float(part) for part in args.exponents.split(",")]
    cases = [json.loads(path.read_text(encoding="utf-8"))
             for path in sorted(Path(args.inputs).glob("*.in"))]
    if not cases:
        raise SystemExit(f"no *.in under {args.inputs}")

    console_rule = args.console_rule
    per_case = [sum(is_console_launch(c, console_rule) for c in case["comparables"])
                for case in cases]
    print(f"cases {len(cases)}, pool {args.pool}, comparables per case "
          f"{[len(case.get('comparables') or []) for case in cases]}, "
          f"console launches per case {per_case}, console rule {console_rule}")
    print()
    header = (f"{'exp':>5} | {'all mean':>9} {'all med':>8} {'n':>4} | "
              f"{'console mean':>12} {'console med':>11} {'n':>4}")
    print(header)
    print("-" * len(header))

    for exponent in exponents:
        all_losses, console_losses = [], []
        for case in cases:
            scored = score_case(case, exponent, args.pool, console_rule)
            all_losses.extend(scored)
            console_losses.extend(item for item in scored
                                  if is_console_launch(item[2], console_rule))
        whole = summarise(all_losses)
        console = summarise(console_losses)
        print(f"{exponent:>5.2f} | {whole[0]:>9.4f} {whole[1]:>8.4f} {whole[2]:>4d} | "
              f"{console[0]:>12.4f} {console[1]:>11.4f} {console[2]:>4d}")

    if args.detail:
        print()
        for case in cases:
            print(f"--- {case.get('id')} ({case.get('game', {}).get('name')})")
            scored = score_case(case, exponents[0], args.pool, console_rule)
            for name, loss, comp in sorted(scored, key=lambda item: -item[1]):
                flag = ("console" if is_console_launch(comp, console_rule) else "       ")
                print(f"  {flag} {loss:8.4f}  {name}  [{comp.get('platforms')}]")


if __name__ == "__main__":
    sys.exit(main())
