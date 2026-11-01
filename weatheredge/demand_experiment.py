#!/usr/bin/env python3
"""Does weather beat a calendar baseline at predicting daily electricity demand?

This is the first RealityOS test. It reads ONE CSV that YOU assemble, with one
row per day, joining an Eskom demand series to weather for the same place.
Column names are set on the command line because I have not seen the Eskom
Data Portal file layout.

    python -m weatheredge.demand_experiment --csv daily.csv \\
        --date-col date --y-col peak_gw --tmax-col tmax --tmin-col tmin \\
        [--holidays holidays.txt] [--out report.md]

Method (walk-forward, no look-ahead):
  For each day t after the first `--min-train` days, every model is fitted only
  on days before t and predicts day t.
  Baselines : same weekday last week; mean of the same weekday over the last 4 weeks.
  Calendar  : linear model on weekday (and holiday) only.
  Weather   : the same plus heating and cooling degree terms.
Key comparison: Weather vs Calendar (does weather add anything?) and vs the best naive baseline.
Verdicts use a block-bootstrap CI on the loss difference (see evaluation.compare).

LIMITS, stated up front:
- If you feed OBSERVED weather this measures how much weather explains demand,
  which is an upper bound on what FORECAST weather can deliver. Re-run with
  forecast temperatures (from forecast_history_multi) for the real test.
- Heating/cooling base temperatures are assumptions (defaults 15 and 24 C); change them
  with --hdd-base / --cdd-base and report how the verdict moves.
- Load shedding, strikes, and structural change (rooftop solar growth) are not modelled.
"""

import argparse
import csv
from datetime import date

from . import evaluation as ev

WEEKDAY_COLS = 6  # Monday is the reference level


def load_rows(path, date_col, y_col, tmax_col, tmin_col):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                d = date.fromisoformat(r[date_col].strip()[:10])
                y = float(r[y_col])
                tmax = float(r[tmax_col])
                tmin = float(r[tmin_col])
            except (KeyError, ValueError, AttributeError):
                continue  # skip rows with missing or unparseable fields
            rows.append({"date": d, "y": y, "tmax": tmax, "tmin": tmin})
    rows.sort(key=lambda r: r["date"])
    seen, out = set(), []
    for r in rows:
        if r["date"] not in seen:
            seen.add(r["date"])
            out.append(r)
    return out


def load_holidays(path):
    if not path:
        return set()
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.add(date.fromisoformat(line[:10]))
    return out


def features(row, holidays, use_weather, hdd_base, cdd_base):
    wd = row["date"].weekday()
    x = [1.0] + [1.0 if wd == k else 0.0 for k in range(1, 7)]
    x.append(1.0 if row["date"] in holidays else 0.0)
    if use_weather:
        mean_t = (row["tmax"] + row["tmin"]) / 2
        x.append(max(0.0, hdd_base - mean_t))
        x.append(max(0.0, mean_t - cdd_base))
    return x


def weekday_last_week(rows, t):
    return rows[t - 7]["y"] if t >= 7 and (rows[t]["date"] - rows[t - 7]["date"]).days == 7 else None


def weekday_mean_4w(rows, t):
    vals = [rows[t - 7 * k]["y"] for k in range(1, 5)
            if t - 7 * k >= 0 and (rows[t]["date"] - rows[t - 7 * k]["date"]).days == 7 * k]
    return sum(vals) / len(vals) if vals else None


def walk_forward(rows, holidays, min_train=365, refit_every=7, hdd_base=15.0, cdd_base=24.0,
                 interval=(0.1, 0.9), resid_window=90, resid_min=30):
    """Return aligned prediction records for each day t >= min_train."""
    cal_coef = wx_coef = None
    cal_resid, wx_resid = [], []
    recs = []
    for t in range(min_train, len(rows)):
        if cal_coef is None or (t - min_train) % refit_every == 0:
            train = rows[:t]
            ys = [r["y"] for r in train]
            cal_coef = ev.fit_ridge([features(r, holidays, False, hdd_base, cdd_base) for r in train], ys)
            wx_coef = ev.fit_ridge([features(r, holidays, True, hdd_base, cdd_base) for r in train], ys)
        r = rows[t]
        base1, base4 = weekday_last_week(rows, t), weekday_mean_4w(rows, t)
        if base1 is None or base4 is None:
            continue
        cal_p = ev.predict(cal_coef, features(r, holidays, False, hdd_base, cdd_base))
        wx_p = ev.predict(wx_coef, features(r, holidays, True, hdd_base, cdd_base))
        # Interval from the model's own recent OUT-OF-SAMPLE errors (no in-sample optimism).
        lo = hi = None
        if len(wx_resid) >= resid_min:
            s = sorted(wx_resid[-resid_window:])
            lo = wx_p + s[int(interval[0] * (len(s) - 1))]
            hi = wx_p + s[int(interval[1] * (len(s) - 1))]
        recs.append({"y": r["y"], "naive1": base1, "naive4": base4, "cal": cal_p, "wx": wx_p, "lo": lo, "hi": hi})
        cal_resid.append(r["y"] - cal_p)
        wx_resid.append(r["y"] - wx_p)
    return recs


def evaluate(recs, block=7, n_boot=2000, seed=0):
    y = [r["y"] for r in recs]
    abs_err = {k: [abs(r["y"] - r[k]) for r in recs] for k in ("naive1", "naive4", "cal", "wx")}
    out = {
        "n": len(recs),
        "mae": {k: sum(v) / len(v) for k, v in abs_err.items()},
        "vs_calendar": ev.compare(abs_err["wx"], abs_err["cal"], block, n_boot, seed),
        "vs_naive_weekday_last_week": ev.compare(abs_err["wx"], abs_err["naive1"], block, n_boot, seed),
        "vs_naive_weekday_mean_4w": ev.compare(abs_err["wx"], abs_err["naive4"], block, n_boot, seed),
        "interval_80_coverage": ev.interval_coverage([r["lo"] for r in recs], [r["hi"] for r in recs], y),
        "interval_n": sum(1 for r in recs if r["lo"] is not None),
    }
    return out


def report(res, args):
    def line(name, c):
        if c["verdict"] == "insufficient_data":
            return f"- {name}: insufficient data (n={c['n']})"
        return (f"- {name}: mean MAE change {c['mean_diff']:+.4f} "
                f"(95% CI {c['ci_lo']:+.4f} to {c['ci_hi']:+.4f}) -> **{c['verdict']}**")
    cov = res["interval_80_coverage"]
    md = [
        "# Weather vs calendar: daily demand walk-forward test", "",
        f"Days scored: {res['n']} (first {args.min_train} days used only for training).",
        f"Heating base {args.hdd_base} C, cooling base {args.cdd_base} C (assumptions).", "",
        "## Mean absolute error (same units as the demand column)",
    ]
    names = {"naive1": "Same weekday last week", "naive4": "Same weekday, 4-week mean",
             "cal": "Calendar model", "wx": "Weather model"}
    for k in ("naive1", "naive4", "cal", "wx"):
        md.append(f"- {names[k]}: {res['mae'][k]:.4f}")
    md += ["", "## Does the weather model beat each baseline? (negative = better)",
           line("Weather vs calendar model", res["vs_calendar"]),
           line("Weather vs same weekday last week", res["vs_naive_weekday_last_week"]),
           line("Weather vs same weekday 4-week mean", res["vs_naive_weekday_mean_4w"]), "",
           "## Stated 80% interval",
           (f"- Observed coverage {cov:.1%} over {res['interval_n']} days (target about 80%)."
            if cov is not None else "- Not enough out-of-sample history to build intervals yet."), "",
           "A 'model_better' verdict needs the whole CI below zero. Anything else is 'no difference detected'.",
           "If observed (not forecast) weather was used, this is an upper bound on forecast skill."]
    return "\n".join(md)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", required=True)
    p.add_argument("--date-col", default="date")
    p.add_argument("--y-col", required=True)
    p.add_argument("--tmax-col", default="tmax")
    p.add_argument("--tmin-col", default="tmin")
    p.add_argument("--holidays")
    p.add_argument("--min-train", type=int, default=365)
    p.add_argument("--hdd-base", type=float, default=15.0)
    p.add_argument("--cdd-base", type=float, default=24.0)
    p.add_argument("--boot", type=int, default=2000)
    p.add_argument("--out")
    args = p.parse_args(argv)
    rows = load_rows(args.csv, args.date_col, args.y_col, args.tmax_col, args.tmin_col)
    if len(rows) <= args.min_train + 30:
        print(f"Only {len(rows)} usable rows; need more than {args.min_train + 30}. Lower --min-train or add data.")
        return 2
    recs = walk_forward(rows, load_holidays(args.holidays), args.min_train, hdd_base=args.hdd_base, cdd_base=args.cdd_base)
    text = report(evaluate(recs, n_boot=args.boot), args)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
