# makefun-gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Amburadullzz/makefun-gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Amburadullzz/makefun-gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecast GTA VI's launch-day Twitch viewers hour by hour

## What it does

`main.py` (Python 3.13, standard library only, no network, no randomness, no
clock) reads every `*.in` case file in `$MAKEFUN_INPUT_DIR` (default `/input`)
and writes, for each, `<id>.out` to `$MAKEFUN_OUTPUT_DIR` (default `/output`):
five quantiles of the Grand Theft Auto VI category's concurrent Twitch viewers
for each of the hours 2 to 24 of release day, given the hour-1 print.

The forecast borrows the shape of past big launches, rescaled to this case:

1. each comparable's release-day curve is read off its hourly points on the
   same UTC date as its `day_start`, hour `h` being UTC hour `h - 1`;
2. every curve is normalised to its own first hour, giving a ratio per hour;
3. each comparable is weighted by recency (`0.75 ** |year difference|`), by
   how close its first hour was to this case's (`exp(-|ln v1 - ln p|)`), and by
   how close its `platforms` are to the target's console-only, no-PC-at-launch
   shape (`platform_similarity(platforms) ** PLATFORM_EXPONENT`: PlayStation or
   Xbox and no PC 1.0, consoles and PC together 0.4, PC-first or PC-only 0.08,
   another console 0.15, unknown 0.3; the exponent is 0.5, swept on the
   leave-one-out harness in `tools/loo_sweep.py`);
4. for hour `h` the weighted log-ratios of hours `h-1`, `h` and `h+1` are
   pooled (neighbours at 0.8 and 0.4 of their weight) so the tail has a sample;
5. the weighted median and weighted standard deviation (floored at 0.02) come
   from that pooled sample;
6. the quantiles are `p * exp(median + z * sd)` at the five levels, clamped to
   `[1, 1e9]` and made non-decreasing;
7. an hour with fewer than six weighted observations, a case with no usable
   comparables, or a missing hour-1 print falls back to the house baseline
   `p * exp(z * 0.15 * sqrt(h - 1))`, with `p` at least 1.

Before anything is written the forecast is checked against the output contract
(exactly 23 rows, hours 2..24 once each, five finite non-decreasing quantiles
per row in `(0, 1e9]`); a case that somehow fails it is written as the baseline.

## Measured

`tools/loo_sweep.py` holds each comparable out in turn, rebuilds the pool
without it, forecasts that launch's own release day from the rest through
`forecast_case`, and scores it with the competition's pinball loss
(`2 x max(tau*d, (tau-1)*d)`, `d = ln(y) - ln(q)`).  On the four practice cases
it reproduces the pool's own numbers: mean 0.4135 / median 0.2642 over all 37
scorable comparables, and 0.3212 / 0.2431 over the 15 console launches when the
pool is the console launches only.  Sweeping `PLATFORM_EXPONENT`:

```
  exp |  all mean  all med    n | console mean console med    n
 0.00 |    0.4135   0.2642  148 |       0.3166      0.2494   68
 0.50 |    0.4434   0.2851  148 |       0.2727      0.2096   68   <- kept
 1.00 |    0.5216   0.2823  148 |       0.2775      0.2163   68
 2.00 |    0.6662   0.2820  148 |       0.2902      0.2277   68
```

`tools/check_contract.py` re-checks written `<id>.out` files against the rules.

## Run it

```
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

The grader runs `python3 -P -s /bot/main.py` with one case per sandbox, at most
8 seconds per case; four practice cases take about 0.1 s in total.

<sub>Entered on [make.fun](https://make.fun/?ref=k2b4xjp7&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
