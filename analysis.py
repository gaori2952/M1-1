"""Reproduce the Instagram analysis: python analysis.py (Python >= 3.10)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
from string import Template

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

METRICS = {
    "views": ("Views.csv", "Views", "Views", "조회수"),
    "viewers": ("Viewers.csv", "Viewers", "Viewers", "시청자 지표"),
    "interactions": ("Interactions.csv", "Content interactions", "Interactions", "상호작용"),
    "visits": ("Visits.csv", "Instagram profile visits", "Profile visits", "프로필 방문"),
    "follows": ("Follows.csv", "Instagram follows", "Follows", "팔로우"),
    "link_clicks": ("Link clicks.csv", "Instagram link clicks", "Link clicks", "링크 클릭"),
}
CORE = ["views", "interactions", "visits", "follows"]
EVENT_START = pd.Timestamp("2026-09-23")
EVENT_END = pd.Timestamp("2026-09-24")
COLORS = {"views": "#27739a", "interactions": "#218577", "visits": "#bd7c28", "follows": "#85569c"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
KO_DAYS = ["월", "화", "수", "목", "금", "토", "일"]


def read_metric(path: Path, name: str) -> pd.Series:
    """Read Meta's UTF-16 export; fail visibly on ambiguous or invalid inputs."""
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    lines = raw.decode(encoding).splitlines()
    if lines and lines[0].strip().lower() == "sep=,":
        lines = lines[1:]
    if not lines or next(csv.reader([lines[0]])) != [METRICS[name][1]]:
        raise ValueError(f"{path.name}: unexpected metric title")
    reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))
    if reader.fieldnames != ["Date", "Primary"]:
        raise ValueError(f"{path.name}: expected Date,Primary columns")
    rows = list(reader)
    if not rows or any(set(row) != {"Date", "Primary"} or row["Primary"] is None for row in rows):
        raise ValueError(f"{path.name}: empty or malformed CSV")
    dates = pd.to_datetime([row["Date"] for row in rows], errors="raise")
    if dates.isna().any() or dates.tz is not None or (dates != dates.normalize()).any():
        raise ValueError(f"{path.name}: expected timezone-naive daily midnight dates")
    if dates.duplicated().any():
        raise ValueError(f"{path.name}: duplicate dates")
    values = pd.to_numeric(pd.Series([row["Primary"].strip() for row in rows]).replace("", np.nan), errors="raise")
    present = values.dropna()
    if not np.isfinite(present).all() or (present < 0).any() or (present % 1 != 0).any():
        raise ValueError(f"{path.name}: counts must be finite nonnegative integers")
    result = pd.Series(values.to_numpy(dtype=float), index=dates, name=name).sort_index()
    result.index.name = "date"
    return result


def join_daily(series: list[pd.Series]) -> pd.DataFrame:
    frame = pd.concat(series, axis=1).sort_index()
    frame = frame.reindex(pd.date_range(frame.index.min(), frame.index.max(), freq="D"))
    frame.index.name = "date"
    return frame


def percent_change(series: pd.Series) -> pd.Series:
    previous = series.shift(1)
    return (series - previous).div(previous.where(previous.ne(0))) * 100


def lag_pairs(frame: pd.DataFrame, target: str, lag: int, exclude_event: bool = False) -> pd.DataFrame:
    """Pair views(t) with target(t+lag), never with the next available row."""
    y = frame[target].copy()
    y.index = y.index - pd.Timedelta(days=lag)
    pairs = pd.concat([frame["views"].rename("x"), y.rename("y")], axis=1).dropna()
    if exclude_event:
        source_in_event = (pairs.index >= EVENT_START) & (pairs.index <= EVENT_END)
        outcome_date = pairs.index + pd.Timedelta(days=lag)
        outcome_in_event = (outcome_date >= EVENT_START) & (outcome_date <= EVENT_END)
        pairs = pairs.loc[~(source_in_event | outcome_in_event)]
    return pairs


def correlations(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for target in ["visits", "follows"]:
        for lag in [0, 1]:
            for sample in ["all", "exclude_event", "daily_difference"]:
                source = frame.diff() if sample == "daily_difference" else frame
                pairs = lag_pairs(source, target, lag, exclude_event=sample == "exclude_event")
                pearson = pairs.x.corr(pairs.y) if len(pairs) > 2 else np.nan
                # Pearson correlation of average ranks is Spearman; no SciPy dependency.
                spearman = pairs.x.rank().corr(pairs.y.rank()) if len(pairs) > 2 else np.nan
                records.append([target, lag, sample, len(pairs), pearson, spearman])
    return pd.DataFrame(records, columns=["target", "lag_days", "sample", "n", "pearson", "spearman"])


def event_windows(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for days in [7, 14]:
        windows = {
            "before": (EVENT_START - pd.Timedelta(days=days), EVENT_START - pd.Timedelta(days=1)),
            "after": (EVENT_END + pd.Timedelta(days=1), EVENT_END + pd.Timedelta(days=days)),
        }
        for period, (start, end) in windows.items():
            for metric in frame.columns:
                values = frame.loc[start:end, metric]
                if values.count() != days:
                    raise ValueError(f"Incomplete {days}-day {period} event window for {metric}")
                records.append([days, period, metric, str(start.date()), str(end.date()),
                                int(values.count()), values.mean(), values.median(), values.sum()])
    return pd.DataFrame(records, columns=["days", "period", "metric", "start", "end", "n", "mean", "median", "sum"]).set_index(["days", "period", "metric"])


def analyze() -> dict:
    series, audit = [], []
    for name, (filename, title, _, _) in METRICS.items():
        path = ROOT / "data/raw" / filename
        values = read_metric(path, name)
        q1, q3 = values.quantile([.25, .75])
        threshold = q3 + 1.5 * (q3 - q1)
        expected_days = (values.index.max() - values.index.min()).days + 1
        audit.append(dict(metric=name, file=filename, title=title, rows=len(values),
                          valid_values=int(values.count()), blank_values=int(values.isna().sum()),
                          start=str(values.index.min().date()), end=str(values.index.max().date()),
                          missing_dates_inside_range=expected_days-len(values), zero_days=int(values.eq(0).sum()),
                          iqr_upper=threshold, flagged_high_days=int(values.gt(threshold).sum()),
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        series.append(values)
    daily = join_daily(series)
    # Preserve calendar gaps when comparing dates; never silently compress a time series.
    complete = daily.dropna()
    if len(complete) < 100:
        raise ValueError("Fewer than 100 complete dates; do not pad missing records with zeros.")
    common = daily.loc[complete.index.min():complete.index.max()]
    if common.isna().any().any():
        raise ValueError("Internal missing values in the comparison period require an explicit decision.")
    derived = daily.copy()
    for name in METRICS:
        derived[f"{name}_ma7"] = daily[name].rolling(7, min_periods=7).mean()
        derived[f"{name}_change_pct"] = percent_change(daily[name])
        threshold = next(a["iqr_upper"] for a in audit if a["metric"] == name)
        derived[f"{name}_high_flag"] = daily[name].gt(threshold).where(daily[name].notna())
    for name in ["visits", "follows", "interactions"]:
        derived[f"{name}_per_1000_views"] = daily[name].div(daily.views.where(daily.views.ne(0))) * 1000
    monthly = common.groupby(common.index.to_period("M")).agg(["count", "sum", "mean", "median"])
    weekday = common.groupby(common.index.dayofweek).agg(["count", "mean", "median"])
    corr = correlations(common)
    periods = event_windows(common)
    summary = {"overall_start": str(daily.index.min().date()), "overall_end": str(daily.index.max().date()),
               "overall_days": len(daily), "common_start": str(common.index.min().date()),
               "common_end": str(common.index.max().date()), "common_days": len(common), "metrics": {}}
    for metric in METRICS:
        values = common[metric]
        summary["metrics"][metric] = dict(
            daily_sum=float(values.sum()), mean=float(values.mean()), median=float(values.median()),
            peak=float(values.max()), peak_date=str(values.idxmax().date()),
            first28_mean=float(values.iloc[:28].mean()), last28_mean=float(values.iloc[-28:].mean()),
            last28_without_event_mean=float(values.iloc[-28:].drop(pd.date_range(EVENT_START, EVENT_END), errors="ignore").mean()),
            top5_share_pct=float(values.nlargest(5).sum() / values.sum() * 100) if values.sum() else None)
    return dict(daily=daily, common=common, derived=derived, audit=pd.DataFrame(audit), monthly=monthly,
                weekday=weekday, correlations=corr, periods=periods, summary=summary)


def save_tables(result: dict) -> None:
    out = ROOT / "data/processed"
    out.mkdir(parents=True, exist_ok=True)
    for name in ["daily", "common", "derived", "audit", "monthly", "weekday", "correlations", "periods"]:
        table = result[name].copy()
        if name in ["monthly", "weekday"]:
            table.columns = ["_".join(column) for column in table.columns]
            table.index.name = "month" if name == "monthly" else "weekday_0_Mon_6_Sun"
        table.to_csv(out / f"{name}.csv", index=name not in ["audit", "correlations"], encoding="utf-8-sig", float_format="%.8f")
    (out / "summary.json").write_text(json.dumps(result["summary"], ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def compact_number(value, _=None):
    return f"{value/1000:g}k" if abs(value) >= 1000 else f"{value:g}"


def chart_style():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 12,
                        "figure.facecolor": "#f7f8fa", "axes.facecolor": "white", "axes.spines.top": False,
                        "axes.spines.right": False, "axes.edgecolor": "#c3cad2", "grid.color": "#e2e6eb",
                        "axes.labelcolor": "#3b4553", "text.color": "#1e2b3b", "savefig.dpi": 160})


def finish_chart(fig, filename, title, note):
    fig.suptitle(title, x=.075, y=.985, ha="left", fontsize=18, fontweight="bold")
    fig.text(.075, .935, note, ha="left", fontsize=10, color="#596577")
    fig.subplots_adjust(top=.86, bottom=.10, hspace=.42, wspace=.26, left=.075, right=.97)
    fig.savefig(ROOT / "images" / filename, facecolor=fig.get_facecolor())
    plt.close(fig)


def make_charts(result: dict):
    chart_style()
    (ROOT / "images").mkdir(exist_ok=True)
    common = result["common"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for ax, name in zip(axes.flat, CORE):
        values = common[name]
        ax.plot(values.index, values, color=COLORS[name], alpha=.32, lw=1.1, label="Daily")
        ax.plot(values.index, values.rolling(7, min_periods=7).mean(), color=COLORS[name], lw=2.1, label="7-day trailing mean")
        ax.axvspan(EVENT_START, EVENT_END + pd.Timedelta(days=1), color="#d75c40", alpha=.17, label="Sep 23-24")
        ax.set(title=METRICS[name][2], ylabel="Daily count", ylim=(0, None))
        ax.yaxis.set_major_formatter(FuncFormatter(compact_number))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.grid(axis="y", alpha=.6)
        ax.legend(loc="upper left", frameon=False, fontsize=8)
    finish_chart(fig, "01_daily_trends.png", "01  |  Daily activity and the underlying trend",
                 "2026-05-29 to 2026-10-13  /  138 complete days  /  Each panel uses its own linear count scale")

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for row, target in enumerate(["visits", "follows"]):
        for col, lag in enumerate([0, 1]):
            ax = axes[row, col]
            pairs = lag_pairs(common, target, lag)
            outcome_dates = pairs.index + pd.Timedelta(days=lag)
            highlighted = ((pairs.index >= EVENT_START) & (pairs.index <= EVENT_END)) | ((outcome_dates >= EVENT_START) & (outcome_dates <= EVENT_END))
            ax.scatter(pairs.x[~highlighted], pairs.y[~highlighted], s=22, color=COLORS[target], alpha=.55, edgecolors="none")
            ax.scatter(pairs.x[highlighted], pairs.y[highlighted], s=48, color="#d75c40", edgecolors="white", linewidth=.6, label="Touches Sep 23-24")
            r = pairs.x.corr(pairs.y)
            ax.set(title=f"{METRICS[target][2]} | {'same day' if lag == 0 else 'next day'}", xlabel="Views on day t", ylabel=f"{METRICS[target][2]} on day t{' + 1' if lag else ''}", xlim=(0,None), ylim=(0,None))
            ax.text(.04, .92, f"Pearson r = {r:.3f}   |   n = {len(pairs)}", transform=ax.transAxes, fontsize=10)
            ax.xaxis.set_major_formatter(FuncFormatter(compact_number))
            ax.yaxis.set_major_formatter(FuncFormatter(compact_number))
            ax.grid(alpha=.4)
            ax.legend(loc="lower right", fontsize=8, frameon=False)
    finish_chart(fig, "02_views_and_actions.png", "02  |  Views move with visits and follows",
                 "Calendar-aligned daily pairs  /  Shared trends and large peaks can inflate correlations  /  Association is not attribution")

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    periods = result["periods"]
    for ax, name in zip(axes.flat, CORE):
        before = [periods.loc[(d, "before", name), "mean"] for d in [7,14]]
        after = [periods.loc[(d, "after", name), "mean"] for d in [7,14]]
        x = np.arange(2)
        for bars in [ax.bar(x-.18, before, width=.34, color="#bcc8d6", label="Before"),
                     ax.bar(x+.18, after, width=.34, color=COLORS[name], label="After")]:
            ax.bar_label(bars, labels=[f"{v:,.0f}" for v in bars.datavalues], padding=5, fontsize=10)
        ax.set(title=METRICS[name][2], ylabel="Mean daily count", xticks=x, xticklabels=["7-day windows", "14-day windows"])
        ax.set_ylim(0, max(before+after)*1.23)
        ax.yaxis.set_major_formatter(FuncFormatter(compact_number))
        ax.grid(axis="y", alpha=.4)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=9)
    finish_chart(fig, "03_event_windows.png", "03  |  Activity before and after the September peak",
                 "Sep 23-24 excluded  /  Before ends Sep 22; after starts Sep 25  /  7- and 14-day windows overlap and are descriptive")

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    weekday = result["weekday"]
    for ax, name in zip(axes.flat, CORE):
        means = weekday[(name, "mean")].reindex(range(7))
        medians = weekday[(name, "median")].reindex(range(7))
        counts = weekday[(name, "count")].reindex(range(7))
        ax.bar(range(7), means, color=COLORS[name], alpha=.68, width=.62, label="Mean")
        ax.scatter(range(7), medians, color="#1e2b3b", marker="D", s=28, label="Median", zorder=3)
        ax.set(title=METRICS[name][2], ylabel="Daily count", xticks=range(7), xticklabels=[f"{d}\nn={int(n)}" for d,n in zip(WEEKDAYS,counts)], ylim=(0,None))
        ax.yaxis.set_major_formatter(FuncFormatter(compact_number))
        ax.grid(axis="y", alpha=.4)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=9)
    finish_chart(fig, "04_weekday_patterns.png", "04  |  Weekday averages hide large differences",
                 "2026-05-29 to 2026-10-13  /  Means, medians and sample sizes  /  Not an estimate of the best posting day")


def markdown_table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"] +
                     ["| " + " | ".join(str(value) for value in row) + " |" for row in rows])


def build_report(result: dict):
    summary = result["summary"]
    metrics = summary["metrics"]
    periods = result["periods"]
    common = result["common"]
    corr = result["correlations"]
    f = lambda x: f"{x:,.1f}"
    fields = dict(summary)
    fields["coverage_table"] = markdown_table(["원본", "기간", "행 수", "빈 값", "0인 날", "높은 값 표시*"],
        [[a.file, f"{a.start}~{a.end}", a.rows, a.blank_values, a.zero_days, a.flagged_high_days] for a in result["audit"].itertuples()])
    fields["main_table"] = markdown_table(["지표", "공통 기간 합계", "일평균", "중앙값", "최고 기록 (날짜)"],
        [[METRICS[k][3], f"{metrics[k]['daily_sum']:,.0f}", f(metrics[k]["mean"]), f(metrics[k]["median"]),
          f"{metrics[k]['peak']:,.0f} ({metrics[k]['peak_date']})"] for k in CORE])
    fields["trend_table"] = markdown_table(["지표", "첫 28일 평균", "마지막 28일 평균", "평균 비율", "마지막 28일 중 급증 2일 제외 평균 (26일)"],
        [[METRICS[k][3], f(metrics[k]["first28_mean"]), f(metrics[k]["last28_mean"]),
          f"{metrics[k]['last28_mean']/metrics[k]['first28_mean']:.2f}배", f(metrics[k]["last28_without_event_mean"])] for k in CORE])
    sample_names = {"all":"전체", "exclude_event":"9/23~24 관련 쌍 제외", "daily_difference":"전일 대비 증감량"}
    fields["correlation_table"] = markdown_table(["대상", "시차", "자료", "쌍 수", "Pearson r", "Spearman ρ"],
        [[METRICS[r.target][3], f"{r.lag_days}일", sample_names[r.sample], r.n, f"{r.pearson:.3f}", f"{r.spearman:.3f}"] for r in corr.itertuples()])
    fields["event_table"] = markdown_table(["지표", "기간 길이", "직전 일평균", "직후 일평균", "직후/직전", "변화율"],
        [[METRICS[k][3], f"{d}일", f(periods.loc[(d,"before",k),"mean"]), f(periods.loc[(d,"after",k),"mean"]),
          f"{periods.loc[(d,'after',k),'mean']/periods.loc[(d,'before',k),'mean']:.2f}배",
          f"{(periods.loc[(d,'after',k),'mean']/periods.loc[(d,'before',k),'mean']-1)*100:+.1f}%"] for d in [7,14] for k in CORE])
    fields["weekday_table"] = markdown_table(["요일", "일수", "조회수 평균", "조회수 중앙값", "팔로우 평균", "팔로우 중앙값"],
        [[KO_DAYS[d], int(result["weekday"].loc[d,("views","count")]), f(result["weekday"].loc[d,("views","mean")]),
          f(result["weekday"].loc[d,("views","median")]), f(result["weekday"].loc[d,("follows","mean")]),
          f(result["weekday"].loc[d,("follows","median")])] for d in range(7)])
    fields["monthly_table"] = markdown_table(["월", "포함 일수", "조회수 일평균", "방문 일평균", "팔로우 일평균"],
        [[str(month), int(row[("views","count")]), f(row[("views","mean")]), f(row[("visits","mean")]), f(row[("follows","mean")])] for month,row in result["monthly"].iterrows()])
    fields["click_table"] = markdown_table(["날짜", "클릭 수"], [[str(d.date()), int(v)] for d,v in result["daily"].link_clicks.items() if v > 0])
    fields["views_top5_pct"] = f"{metrics['views']['top5_share_pct']:.1f}"
    fields["views_last_first"] = f"{metrics['views']['last28_mean']/metrics['views']['first28_mean']:.2f}"
    fields["views_after14_ratio"] = f"{periods.loc[(14,'after','views'),'mean']/periods.loc[(14,'before','views'),'mean']:.2f}"
    fields["follows_after14_ratio"] = f"{periods.loc[(14,'after','follows'),'mean']/periods.loc[(14,'before','follows'),'mean']:.2f}"
    fields["follows_before14"] = f(periods.loc[(14,"before","follows"),"mean"])
    fields["follows_after14"] = f(periods.loc[(14,"after","follows"),"mean"])
    for target in ["visits", "follows"]:
        for lag in [0,1]:
            fields[f"{target}_r{lag}"] = f"{corr.loc[(corr.target==target)&(corr.lag_days==lag)&(corr['sample']=='all'),'pearson'].iloc[0]:.3f}"
    fields["follows_r0_without_event"] = f"{corr.loc[(corr.target=='follows')&(corr.lag_days==0)&(corr['sample']=='exclude_event'),'pearson'].iloc[0]:.3f}"
    fields["follows_diff_r1"] = f"{corr.loc[(corr.target=='follows')&(corr.lag_days==1)&(corr['sample']=='daily_difference'),'pearson'].iloc[0]:.3f}"
    fields["follows_ratio_first28"] = f"{common.follows.iloc[:28].sum()/common.views.iloc[:28].sum()*1000:.2f}"
    fields["follows_ratio_last28"] = f"{common.follows.iloc[-28:].sum()/common.views.iloc[-28:].sum()*1000:.2f}"
    weekday = result["weekday"]
    winner = int(weekday[("views", "mean")].idxmax())
    median_winner = int(weekday[("views", "median")].idxmax())
    fields.update(weekday_mean_winner=KO_DAYS[winner], weekday_median_winner=KO_DAYS[median_winner],
                  weekday_winner_mean=f(weekday.loc[winner,("views","mean")]),
                  weekday_winner_median=f(weekday.loc[winner,("views","median")]))
    template = Template((ROOT / "templates/REPORT.template.md").read_text(encoding="utf-8"))
    (ROOT / "REPORT.md").write_text(template.substitute(fields), encoding="utf-8")


def main():
    result = analyze()
    save_tables(result)
    make_charts(result)
    build_report(result)
    print(f"OK: {len(result['daily'])} calendar days; {len(result['common'])} complete comparison days.")
    print("Generated 4 PNG charts, processed tables and REPORT.md.")
    print("Original files in data/raw were read only.")


if __name__ == "__main__":
    main()
