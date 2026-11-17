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
2. every curve is normalised to its own first hour, giving a ratio per hour --
   except a comparable whose hour 1 is dead air (`v1 < 0.3 * max(v2..v5)`: the
   store had not unlocked, or only a pre-load stream was live), which is
   re-anchored instead: normalised on the first hour at or above 60% of its
   release-day peak, and shifted so that anchor lands on the target's hour 1
   (the last ratio is carried forward past hour 24);
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
it reproduces the pool's own numbers: mean 0.4448 / median 0.2829 over all 37
scorable comparables, and 0.2672 / 0.1967 over the 17 console launches when the
pool is the whole remaining pool.  Sweeping `PLATFORM_EXPONENT` (with the
dead-air repair in place):

```
  exp |  all mean  all med    n | console mean console med    n
 0.00 |    0.4200   0.2630  148 |       0.3012      0.2323   68
 0.50 |    0.4448   0.2829  148 |       0.2672      0.1967   68   <- kept
 1.00 |    0.5268   0.2787  148 |       0.2761      0.2064   68
 2.00 |    0.6685   0.2825  148 |       0.2908      0.2277   68
```

`tools/dead_air_sweep.py` scores the dead-air repair the way the final is
scored -- leave-one-out, pool = the whole remaining pool, mean and median
pinball over the 15 console launches and over all 37 launches.  Its `none` row
reproduces the unrepaired program's 0.2875 / 0.2112 (console) and 0.4434 /
0.2851 (pool) to four decimals before any comparison counts:

```
  repair  thr | console mean console med   n | pool mean pool med   n | flagged
    none    - |       0.2875      0.2112  60 |    0.4434   0.2851 148 |       0
    drop  0.2 |       0.2829      0.2008  60 |    0.4460   0.2864 148 |       1
    drop  0.3 |       0.2829      0.2008  60 |    0.4460   0.2864 148 |       1
    drop  0.4 |       0.2857      0.2001  60 |    0.4713   0.2859 148 |       2
    drop  0.5 |       0.2857      0.2001  60 |    0.4713   0.2859 148 |       2
    drop  0.6 |       0.2865      0.2027  60 |    0.4723   0.2874 148 |       3
reanchor  0.2 |       0.2816      0.2001  60 |    0.4448   0.2829 148 |       1
reanchor  0.3 |       0.2816      0.2001  60 |    0.4448   0.2829 148 |       1   <- kept
reanchor  0.4 |       0.2852      0.1988  60 |    0.4700   0.2772 148 |       2
reanchor  0.5 |       0.2852      0.1988  60 |    0.4700   0.2772 148 |       2
reanchor  0.6 |       0.2849      0.1998  60 |    0.4696   0.2779 148 |       3
```

Re-anchoring at 0.3 is what is kept: on the console launches it takes the mean
from 0.2875 to 0.2816 and the median from 0.2112 to 0.2001, and on the pool the
median from 0.2851 to 0.2829 while the mean pays 0.0014, because the launches
with the most extreme curves lose the evidence of the one comparable the test
flags.  9 of the 15 console launches improve; a paired bootstrap over them puts
the mean gain at [-0.0128, -0.0004] (95%), so the sign is solid and the size is
small.  0.2 and 0.3 flag the same single comparable and measure identically;
0.4 and up flag a second one and cost the pool 0.027 of mean loss against the
unrepaired 0.4434.

`tools/check_contract.py` re-checks written `<id>.out` files against the rules.

## Run it

```
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

The grader runs `python3 -P -s /bot/main.py` with one case per sandbox, at most
8 seconds per case; four practice cases take about 0.1 s in total.

<sub>Entered on [make.fun](https://make.fun/?ref=k2b4xjp7&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
