"""Forecast hour-by-hour Twitch concurrent viewers for a launch day.

The entry reads one case per file (``<id>.in``) from the input directory and
writes ``<id>.out`` with five quantiles for each of the hours 2..24 of the
release day.  The score is the mean pinball loss on the log scale, so what
matters is where each quantile sits in log space, not the raw viewer count.

The model borrows the shape of past big launches: every comparable's release
day is normalised to its own first hour, the resulting log-ratios are weighted
by how recent the launch is, how close its first hour was to this case's first
hour, and how close its platforms are to the target's (console-only, no PC at
launch), pooled over neighbouring hours to thicken the sample, and read off
as weighted empirical quantiles that are scaled back up from this case's hour-1
print.  When a case has too few weighted observations for an hour the house
baseline takes over: the first hour's print, with a log spread that widens like
a random walk's.

Python 3.13, standard library only, no network, no randomness, no clock: two
runs over the same case write byte-identical files.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# The quantile levels the contest scores, in the order a row lists them.
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
# The standard normal's quantile at each level, in the same order.
Z = (
    -1.6448536269514722,
    -0.6744897501960817,
    0.0,
    0.6744897501960817,
    1.6448536269514722,
)

FIRST_HOUR = 1  # hour 1 is given: it is the case's `known` print
LAST_HOUR = 24  # the release day's last scored hour
FORECAST_HOURS = tuple(range(2, 25))  # the 23 hours to forecast

# Pooling weights for the neighbouring hours, keyed by their offset from h.
POOL_WEIGHTS = ((-1, 0.8), (0, 1.0), (1, 0.4))

MIN_SAMPLES = 6  # fewer weighted observations than this: use the baseline
RECENCY_DECAY = 0.75  # per year of distance from the case's own launch year
SCALE_DECAY = 1.0  # exponent on the |ln v1 - ln p| scale penalty
SIGMA_FLOOR = 0.02  # the pooled spread never collapses below this
BASELINE_SIGMA = 0.15  # the house baseline's log spread per sqrt hour

# The target's platforms are console-only: Grand Theft Auto VI ships on PS5 and
# Xbox Series X|S with no PC version at launch, single-player, unlocking at
# midnight local time country by country.  That is the prior the platform
# weight encodes, and it is deliberately NOT read from the case: a case's
# `comparables` name whatever they name, and the practice cases are other games
# entirely.
TARGET_PLATFORMS = "PS5, Xbox Series X|S"

# Platform-similarity scores, closest to the target first.  A launch naming
# PlayStation or Xbox and no PC scores highest; one naming consoles and PC
# together sits in between; one that is PC-only, or lists PC ahead of the
# consoles (a PC-first launch, whose hour 1 is often dead air before a store
# unlock), scores lowest; a console of another family (Switch) sits low too.
SIM_CONSOLE_ONLY = 1.0
SIM_CONSOLE_AND_PC = 0.4
SIM_OTHER_CONSOLE = 0.15
SIM_PC_LEAD = 0.08
SIM_UNKNOWN = 0.3  # no usable `platforms` string: neither endorsed nor damned

# Exponent on the platform weight; 0 disables it, 1 is the similarity itself.
# Swept with the leave-one-out harness in tools/loo_sweep.py: the console
# launches' mean pinball loss falls from 0.3166 at 0.0 to 0.2727 at 0.5 and
# rises again past it (0.2775 at 1.0, 0.2902 at 2.0), while the whole pool --
# which is mostly the PC-led launches this weight deliberately demotes -- pays
# a little (0.4135 to 0.4434).  0.5 is where the console pool is best.
PLATFORM_EXPONENT = 0.5

LOWEST = 1.0  # no quantile may sit below one viewer
HIGHEST = 1e9  # ... nor above a billion
ROUND_PLACES = 2  # decimals kept in the output


# --------------------------------------------------------------------------
# Small, defensive helpers
# --------------------------------------------------------------------------


def as_number(value):
    """`value` as a finite float, or None when it is not a usable number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:  # an integer too large for a float
            return None
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (ValueError, OverflowError):
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def parse_instant(text):
    """An ISO-8601 instant in UTC, or None when it cannot be read."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw[-1] in "Zz":
        raw = raw[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    try:
        return stamp.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def clamp(value):
    """A finite number inside the contest's [1, 1e9] window."""
    if value is None or not math.isfinite(value):
        return LOWEST
    if value < LOWEST:
        return LOWEST
    if value > HIGHEST:
        return HIGHEST
    return value


def round_half_up(value, places):
    """`value` rounded half away from zero at `places` decimals."""
    scale = 10 ** places
    scaled = value * scale
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    return whole / scale


def tidy_row(values):
    """The five quantiles as the contract wants them: clamped, rounded, sorted."""
    row = []
    previous = LOWEST
    for value in values:
        shaped = round_half_up(clamp(value), ROUND_PLACES)
        if shaped < previous:
            shaped = previous
        shaped = clamp(shaped)
        row.append(float(shaped))
        previous = shaped
    return row


# --------------------------------------------------------------------------
# Step 1: each comparable's release-day curve
# --------------------------------------------------------------------------


def release_day_curve(comparable):
    """The comparable's release-day viewers, keyed by hour 1..24.

    Only points whose `from` falls on the same UTC date as `day_start` belong
    to the release day.  A point at UTC hour H is hour H + 1, so T00 is hour 1
    and T23 is hour 24.  Points with a null or unreadable `viewers` are
    skipped, which leaves holes in the curve; a repeated hour is averaged.
    """
    if not isinstance(comparable, dict):
        return {}
    start = parse_instant(comparable.get("day_start"))
    if start is None:
        return {}
    release_date = start.date()
    hourly = comparable.get("hourly")
    if not isinstance(hourly, list):
        return {}

    totals = {}
    counts = {}
    for point in hourly:
        if not isinstance(point, dict):
            continue
        stamp = parse_instant(point.get("from"))
        if stamp is None or stamp.date() != release_date:
            continue
        viewers = as_number(point.get("viewers"))
        if viewers is None:
            continue
        hour = stamp.hour + 1
        if not FIRST_HOUR <= hour <= LAST_HOUR:
            continue
        totals[hour] = totals.get(hour, 0.0) + viewers
        counts[hour] = counts.get(hour, 0) + 1

    return {hour: totals[hour] / counts[hour] for hour in totals}


# --------------------------------------------------------------------------
# Step 2: normalise to hour 1
# --------------------------------------------------------------------------


def normalised_ratios(curve):
    """v[h] / v[1] for every hour 2..24 the curve has above zero.

    A comparable whose first hour is missing or not above zero has no ratios:
    there is nothing to normalise against.
    """
    base = curve.get(FIRST_HOUR)
    if base is None or base <= 0:
        return {}
    ratios = {}
    for hour in FORECAST_HOURS:
        viewers = curve.get(hour)
        if viewers is not None and viewers > 0:
            ratios[hour] = viewers / base
    return ratios


# --------------------------------------------------------------------------
# Step 3: weight each comparable three times
# --------------------------------------------------------------------------


def names_playstation(text):
    """True when a lowercase platform string names a PlayStation console."""
    return "playstation" in text or re.search(r"\bps[0-9]", text) is not None


def names_xbox(text):
    """True when a lowercase platform string names an Xbox console."""
    return "xbox" in text


def names_pc(text):
    """True when a lowercase platform string names the PC as a platform."""
    return re.search(r"\bpc\b", text) is not None


def platform_similarity(platforms):
    """How close a comparable's platforms are to the console-only target.

    A launch that names PlayStation or Xbox and no PC scores highest.  One
    that names both a console and the PC, with the PC not leading, scores in
    between.  One that is PC-only, or that lists the PC before the consoles (a
    PC-first launch), scores lowest, and so does a console of another family.
    The tiers encode TARGET_PLATFORMS; they are never read from the case.
    """
    if not isinstance(platforms, str) or not platforms.strip():
        return SIM_UNKNOWN
    text = platforms.lower()
    pc_at = _first_position(text, r"\bpc\b")
    console_at = _first_position(text, r"playstation|\bps[0-9]|xbox")
    if pc_at is None:
        if console_at is None:
            return SIM_OTHER_CONSOLE  # a console, but neither PlayStation nor Xbox
        return SIM_CONSOLE_ONLY
    if console_at is None:
        return SIM_PC_LEAD  # PC only
    return SIM_PC_LEAD if pc_at < console_at else SIM_CONSOLE_AND_PC


def _first_position(text, pattern):
    """Where `pattern` first matches in `text`, or None when it never does."""
    match = re.search(pattern, text)
    return match.start() if match is not None else None


def platform_weight(platforms):
    """The similarity raised to PLATFORM_EXPONENT, always above zero."""
    return platform_similarity(platforms) ** PLATFORM_EXPONENT


def comparable_weight(day_start, first_hour, case_year, p, platforms=None):
    """Recency times scale times platform weight; zero when unusable."""
    if first_hour is None or first_hour <= 0 or p <= 0:
        return 0.0
    start = parse_instant(day_start)
    if start is not None and case_year is not None:
        recency = RECENCY_DECAY ** abs(start.year - case_year)
    else:
        recency = 1.0
    scale = math.exp(-SCALE_DECAY * abs(math.log(first_hour) - math.log(p)))
    weight = recency * scale * platform_weight(platforms)
    return weight if math.isfinite(weight) and weight > 0 else 0.0


def build_profiles(case, p):
    """One (log-ratios, weight) pair per comparable that has a usable curve.

    A comparable whose release day has no first hour above zero, or no other
    hour above zero, cannot speak for this case's shape and is dropped.
    """
    comparables = case.get("comparables")
    if not isinstance(comparables, list):
        return []
    case_year = case_year_of(case)
    profiles = []
    for comparable in comparables:
        curve = release_day_curve(comparable)
        ratios = normalised_ratios(curve)
        if not ratios:
            continue
        weight = comparable_weight(
            comparable.get("day_start"), curve.get(FIRST_HOUR), case_year, p,
            comparable.get("platforms"),
        )
        if weight <= 0:
            continue
        log_ratios = {}
        for hour, ratio in ratios.items():
            value = math.log(ratio)
            if math.isfinite(value):
                log_ratios[hour] = value
        if not log_ratios:
            continue
        profiles.append((log_ratios, weight))
    return profiles


# --------------------------------------------------------------------------
# Step 4: pool across neighbouring hours
# --------------------------------------------------------------------------


def pooled_samples(profiles, hour):
    """The weighted log-ratios that speak for `hour`.

    Every comparable contributes at hours h-1, h and h+1, the neighbours at
    0.8 and 0.4 of their own weight; neighbours outside 2..24 are skipped.
    """
    samples = []
    for offset, factor in POOL_WEIGHTS:
        source = hour + offset
        if not FIRST_HOUR < source <= LAST_HOUR:
            continue
        for log_ratios, weight in profiles:
            value = log_ratios.get(source)
            if value is None:
                continue
            samples.append((value, weight * factor))
    return samples


# --------------------------------------------------------------------------
# Step 5: weighted empirical quantiles and spread
# --------------------------------------------------------------------------


def weighted_quantile(samples, tau):
    """The smallest value whose cumulative weight reaches tau of the total."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    total = math.fsum(weight for _, weight in ordered)
    if total <= 0:
        return ordered[0][0]
    target = tau * total
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= target - 1e-12 * total:
            return value
    return ordered[-1][0]


def weighted_spread(samples, centre):
    """The weighted standard deviation around `centre`, floored."""
    total = math.fsum(weight for _, weight in samples)
    if total <= 0:
        return SIGMA_FLOOR
    variance = math.fsum(weight * (value - centre) ** 2 for value, weight in samples)
    spread = math.sqrt(max(variance / total, 0.0))
    if not math.isfinite(spread):
        return SIGMA_FLOOR
    return max(spread, SIGMA_FLOOR)


# --------------------------------------------------------------------------
# Step 6: scale back up
# --------------------------------------------------------------------------


def shaped_row(p, samples):
    """Five quantiles around this case's hour-1 print, from the pooled sample."""
    median = weighted_quantile(samples, 0.5)
    spread = weighted_spread(samples, median)
    return [p * math.exp(median + z * spread) for z in Z]


# --------------------------------------------------------------------------
# Step 7: the house baseline, for hours too thin to model
# --------------------------------------------------------------------------


def baseline_row(p, hour):
    """The house baseline: the first hour's print, spread like a random walk."""
    sigma = BASELINE_SIGMA * math.sqrt(max(hour - 1, 0))
    return [p * math.exp(z * sigma) for z in Z]


# --------------------------------------------------------------------------
# The case
# --------------------------------------------------------------------------


def case_year_of(case):
    """The year of the case's release day, for the recency weight."""
    start = parse_instant(case.get("day_start"))
    if start is not None:
        return start.year
    known = case.get("known")
    rows = known if isinstance(known, list) else [known]
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = parse_instant(row.get("from"))
        if stamp is not None:
            return stamp.year
    return None


def hour_one_print(case):
    """The case's hour-1 viewers, at least 1; 1 when it is missing."""
    known = case.get("known")
    if isinstance(known, dict):
        rows = [known]
    elif isinstance(known, list):
        rows = known
    else:
        rows = []

    fallback = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        viewers = as_number(row.get("viewers"))
        if viewers is None:
            continue
        if fallback is None:
            fallback = viewers
        if as_number(row.get("hour")) == FIRST_HOUR:
            return clamp(max(viewers, LOWEST))
    if fallback is None:
        return LOWEST
    return clamp(max(fallback, LOWEST))


def forecast_case(case):
    """The 23 rows for one case: hours 2..24, five quantiles each."""
    p = hour_one_print(case)
    profiles = build_profiles(case, p)

    rows = []
    for hour in FORECAST_HOURS:
        if profiles:
            samples = pooled_samples(profiles, hour)
        else:
            samples = []
        if len(samples) < MIN_SAMPLES:
            values = baseline_row(p, hour)
        else:
            values = shaped_row(p, samples)
        if len(values) != len(LEVELS):
            raise ValueError(f"hour {hour} produced {len(values)} quantiles")
        rows.append({"hour": hour, "q": tidy_row(values)})
    return {"hours": rows}


def baseline_forecast(case):
    """The whole-day house baseline, the answer when nothing else can be built."""
    p = hour_one_print(case)
    return {"hours": [{"hour": hour, "q": tidy_row(baseline_row(p, hour))}
                      for hour in FORECAST_HOURS]}


def contract_holds(forecast):
    """True when `forecast` is exactly the shape the contest accepts.

    The grader scores an out-of-shape file as invalid, which disqualifies the
    entry, so the last thing done before writing is to check the shape here and
    fall back to the baseline when it does not hold.
    """
    if not isinstance(forecast, dict) or set(forecast) != {"hours"}:
        return False
    rows = forecast["hours"]
    if not isinstance(rows, list) or len(rows) != len(FORECAST_HOURS):
        return False
    hours = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"hour", "q"}:
            return False
        hour = row["hour"]
        if not isinstance(hour, int) or isinstance(hour, bool):
            return False
        hours.append(hour)
        values = row["q"]
        if not isinstance(values, list) or len(values) != len(LEVELS):
            return False
        previous = LOWEST
        for value in values:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
            if not math.isfinite(value) or not LOWEST <= value <= HIGHEST:
                return False
            if value < previous:
                return False
            previous = value
    return sorted(hours) == list(FORECAST_HOURS)


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def directory_from_env(name, default):
    """The directory named by `name`, or `default` when it is unset or blank."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return Path(default)
    return Path(value)


def read_case(path):
    """The case in `path` as a dict, or an empty dict when it is unreadable.

    Anything at all can be in a case file: a directory, a broken encoding, a
    deeply nested document.  None of it should stop the other cases, so the
    read swallows every failure and hands back an empty case, which the
    forecast turns into the house baseline.
    """
    try:
        case = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return case if isinstance(case, dict) else {}


def write_forecast(path, forecast):
    """Write one forecast file: compact, ASCII-only UTF-8 JSON."""
    text = json.dumps(forecast, separators=(",", ":"), allow_nan=False, ensure_ascii=True)
    path.write_text(text + "\n", encoding="utf-8")


def case_paths(source):
    """Every `*.in` file in `source`, in name order.

    A missing or unreadable input directory yields no cases rather than an
    exception: there is nothing to forecast, and the run should still end ok.
    """
    try:
        found = list(source.glob("*.in"))
    except OSError:
        return []
    return sorted((path for path in found if path.is_file()), key=lambda path: path.name)


def main():
    source = directory_from_env("MAKEFUN_INPUT_DIR", "/input")
    target = directory_from_env("MAKEFUN_OUTPUT_DIR", "/output")
    target.mkdir(parents=True, exist_ok=True)

    for path in case_paths(source):
        case = read_case(path)
        try:
            forecast = forecast_case(case)
        except Exception:
            forecast = None
        if not contract_holds(forecast):
            # One unreadable case must not cost the others their forecast: the
            # house baseline over hours 2..24 is always a valid answer.
            forecast = baseline_forecast(case)
        write_forecast(target / (path.stem + ".out"), forecast)


if __name__ == "__main__":
    main()
