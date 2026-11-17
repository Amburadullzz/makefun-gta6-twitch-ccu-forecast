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
3. each comparable is weighted by recency (`0.75 ** |year difference|`) and by
   how close its first hour was to this case's (`exp(-|ln v1 - ln p|)`);
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

## Run it

```
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

The grader runs `python3 -P -s /bot/main.py` with one case per sandbox, at most
8 seconds per case; four practice cases take about 0.1 s in total.

<sub>Entered on [make.fun](https://make.fun/?ref=k2b4xjp7&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
