"""Explainable statistical anomaly detection for hourly weather series (Roadmap P7).

Pure functions on numpy arrays — no network, no database — so every method is unit-testable.
Input of every detector: an hourly series `values` (float array, NaN = missing) and, where a
calendar is needed, `times` as numpy datetime64 in UTC. Output: a `Detection` holding, per
point, a flag, a score, the baseline the point was compared with, and a human-readable reason.

Methods (project rule: no ML / DL):
  threshold_detect   fixed meteorological limit (e.g. temperature >= 35 °C)
  global_zscore      z against the mean/std of the whole series (negative control)
  climate_zscore     z against the same local month + local hour of the OTHER years
                     (leave-one-year-out, so an event never inflates its own baseline)
  persistent_climate_zscore
                     trailing 168 h mean of the climate z (sustained events, e.g. heatwaves)
  iqr_detect         Tukey fences Q1 - k*IQR / Q3 + k*IQR, optionally per group and on a
                     reference subset (e.g. wet periods only for zero-inflated rainfall)
  rolling_zscore     z against the trailing window (24 h / 168 h) BEFORE the point
  pressure_tendency  pressure change over the last N hours (rapid fall = approaching storm)
  stuck_detect       runs of identical values (sensor/feed stuck)

Plus helpers to derive series (rolling_sum), inject synthetic anomalies with labels, and
compute evaluation metrics (confusion, event_metrics).
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

HIGH, LOW, BOTH = "high", "low", "both"
VN_UTC_OFFSET_HOURS = 7  # Viet Nam: UTC+7, no daylight saving time


@dataclass(frozen=True)
class Detection:
    """Result of one detector on one series. All arrays have the length of the input."""

    method: str
    flags: np.ndarray       # bool
    scores: np.ndarray      # float: z-score, exceedance, change...; NaN = not computable
    baseline: np.ndarray    # float: value/limit/fence the point was compared with; NaN = none
    explanation: str        # template, see reason()
    observed: Optional[np.ndarray] = None  # derived value actually evaluated (e.g. 168 h mean); None = raw value

    def value_at(self, i: int, raw_value: float) -> float:
        """The value the method evaluated at point i (derived series if any, else the raw value)."""
        return float(self.observed[i]) if self.observed is not None else float(raw_value)

    def reason(self, i: int, value: float, unit: str = "") -> str:
        """Human-readable answer to 'why was point i flagged?'."""
        return self.explanation.format(
            value=self.value_at(i, value), unit=unit, score=self.scores[i], baseline=self.baseline[i]
        )

    @property
    def count(self) -> int:
        return int(self.flags.sum())


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _as_float(values) -> np.ndarray:
    return np.asarray(values, dtype=float)


def _directional_flags(scores: np.ndarray, k: float, direction: str) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        if direction == HIGH:
            flags = scores >= k
        elif direction == LOW:
            flags = scores <= -k
        elif direction == BOTH:
            flags = np.abs(scores) >= k
        else:
            raise ValueError(f"direction must be one of {HIGH}, {LOW}, {BOTH}")
    return flags & ~np.isnan(scores)


def local_calendar(times_utc: np.ndarray, utc_offset_hours: int = VN_UTC_OFFSET_HOURS
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(year, month 1-12, hour 0-23) in local time for datetime64 UTC timestamps."""
    local = np.asarray(times_utc, dtype="datetime64[s]") + np.timedelta64(utc_offset_hours, "h")
    years = local.astype("datetime64[Y]").astype(int) + 1970
    months = local.astype("datetime64[M]").astype(int) % 12 + 1
    hours = local.astype("datetime64[h]").astype(int) % 24
    return years, months, hours


def rolling_sum(values, window: int) -> np.ndarray:
    """Trailing sum over `window` points INCLUDING the current one (e.g. 24 h rainfall).

    NaN if the window is incomplete or contains a missing value.
    """
    x = _as_float(values)
    if window < 1:
        raise ValueError("window must be >= 1")
    filled = np.concatenate([[0.0], np.cumsum(np.nan_to_num(x))])
    missing = np.concatenate([[0], np.cumsum(np.isnan(x))])
    out = np.full(x.shape, np.nan)
    if len(x) >= window:
        idx = np.arange(window - 1, len(x))
        sums = filled[idx + 1] - filled[idx + 1 - window]
        gaps = missing[idx + 1] - missing[idx + 1 - window]
        out[idx] = np.where(gaps == 0, sums, np.nan)
    return out


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def threshold_detect(values, limit: float, direction: str = HIGH, label: str = "") -> Detection:
    """Flag values at/over a fixed limit (HIGH) or at/under it (LOW). score = distance past the limit."""
    x = _as_float(values)
    if direction == HIGH:
        scores = x - limit
    elif direction == LOW:
        scores = limit - x
    else:
        raise ValueError("threshold_detect supports direction 'high' or 'low'")
    with np.errstate(invalid="ignore"):
        flags = (scores >= 0) & ~np.isnan(x)
    word = "≥" if direction == HIGH else "≤"
    suffix = f" ({label})" if label else ""
    return Detection(
        method="threshold",
        flags=flags,
        scores=scores,
        baseline=np.full(x.shape, float(limit)),
        explanation="{value:.1f}{unit} " + word + " ngưỡng {baseline:.1f}{unit}" + suffix,
    )


def global_zscore(values, k: float = 3.0, direction: str = BOTH) -> Detection:
    """z = (x - mean) / std over the whole series. Ignores daily and seasonal cycles on purpose."""
    x = _as_float(values)
    mean, std = np.nanmean(x), np.nanstd(x, ddof=1)
    scores = (x - mean) / std if std > 0 else np.full(x.shape, np.nan)
    return Detection(
        method="global_zscore",
        flags=_directional_flags(scores, k, direction),
        scores=scores,
        baseline=np.full(x.shape, mean),
        explanation="{value:.1f}{unit} lệch {score:+.1f}σ so với trung bình toàn chuỗi {baseline:.1f}{unit}",
    )


def climate_zscore(times_utc, values, k: float = 3.0, direction: str = BOTH,
                   min_samples: int = 20, utc_offset_hours: int = VN_UTC_OFFSET_HOURS) -> Detection:
    """z against the same local (month, hour) cell computed from the OTHER years only.

    Leave-one-year-out: for a point in year Y, mean/std come from all points of the same
    month and hour in every year except Y. Cells with < min_samples other-year values -> NaN.
    """
    x = _as_float(values)
    years, months, hours = local_calendar(times_utc, utc_offset_hours)
    cell = (months - 1) * 24 + hours                      # 0 .. 287
    year_ids, year_idx = np.unique(years, return_inverse=True)
    valid = ~np.isnan(x)
    shape = (288, len(year_ids))
    n = np.zeros(shape)
    s = np.zeros(shape)
    ss = np.zeros(shape)
    # center by the series mean to keep sums of squares numerically small
    center = np.nanmean(x) if valid.any() else 0.0
    xc = np.where(valid, x - center, 0.0)
    np.add.at(n, (cell, year_idx), valid.astype(float))
    np.add.at(s, (cell, year_idx), xc)
    np.add.at(ss, (cell, year_idx), xc * xc)

    n_other = n.sum(axis=1)[cell] - n[cell, year_idx]
    s_other = s.sum(axis=1)[cell] - s[cell, year_idx]
    ss_other = ss.sum(axis=1)[cell] - ss[cell, year_idx]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_c = s_other / n_other
        var = (ss_other - n_other * mean_c ** 2) / (n_other - 1)
        std = np.sqrt(np.clip(var, 0, None))
        scores = (xc - mean_c) / std
    usable = (n_other >= min_samples) & (std > 0) & valid
    scores = np.where(usable, scores, np.nan)
    return Detection(
        method="climate_zscore",
        flags=_directional_flags(scores, k, direction),
        scores=scores,
        baseline=np.where(usable, mean_c + center, np.nan),
        explanation="{value:.1f}{unit} lệch {score:+.1f}σ so với TB cùng tháng, cùng giờ "
                    "các năm khác ({baseline:.1f}{unit})",
    )


def persistent_climate_zscore(times_utc, values, window: int = 168, threshold: float = 1.0,
                              direction: str = HIGH, min_samples: int = 20,
                              utc_offset_hours: int = VN_UTC_OFFSET_HOURS) -> Detection:
    """Sustained anomaly: trailing mean (incl. current hour) of the hourly climate z-score.

    Catches long events such as heatwaves, whose individual hours are only mildly unusual
    (≈ +2σ) but stay unusual for days. The window must be complete and gap-free.
    observed = trailing mean of the values; baseline = trailing mean of the climate normal.
    """
    hourly = climate_zscore(times_utc, values, k=np.inf, direction=BOTH,
                            min_samples=min_samples, utc_offset_hours=utc_offset_hours)
    mean_z = rolling_sum(hourly.scores, window) / window
    return Detection(
        method="persistent_climate_zscore",
        flags=_directional_flags(mean_z, threshold, direction),
        scores=mean_z,
        baseline=rolling_sum(hourly.baseline, window) / window,
        observed=rolling_sum(values, window) / window,
        explanation="TB " + str(window) + " giờ qua {value:.1f}{unit} so với chuẩn khí hậu "
                    "{baseline:.1f}{unit}: z trung bình {score:+.2f} (ngưỡng " + f"{threshold:g}" + ")",
    )


def iqr_detect(values, k: float = 3.0, direction: str = HIGH,
               reference_mask: Optional[np.ndarray] = None,
               groups: Optional[np.ndarray] = None, min_reference: int = 30) -> Detection:
    """Tukey fences. Quartiles come from `reference_mask` points (default: all non-NaN),
    computed separately for each value of `groups` (default: one group).

    score = (x - Q3) / IQR for HIGH, (Q1 - x) / IQR for LOW, so a flag means score >= k.
    """
    if direction not in (HIGH, LOW):
        raise ValueError("iqr_detect supports direction 'high' or 'low'")
    x = _as_float(values)
    valid = ~np.isnan(x)
    ref = valid if reference_mask is None else (valid & np.asarray(reference_mask, dtype=bool))
    grp = np.zeros(x.shape, dtype=int) if groups is None else np.asarray(groups)
    scores = np.full(x.shape, np.nan)
    baseline = np.full(x.shape, np.nan)
    for g in np.unique(grp):
        in_group = grp == g
        sample = x[in_group & ref]
        if len(sample) < min_reference:
            continue
        q1, q3 = np.percentile(sample, [25, 75])
        iqr = q3 - q1
        if iqr <= 0:
            continue
        target = in_group & valid
        if direction == LOW:
            scores[target] = (q1 - x[target]) / iqr
            baseline[target] = q1 - k * iqr
        else:
            scores[target] = (x[target] - q3) / iqr
            baseline[target] = q3 + k * iqr
    word = "dưới" if direction == LOW else "vượt"
    return Detection(
        method="iqr",
        flags=_directional_flags(scores, k, HIGH),
        scores=scores,
        baseline=baseline,
        explanation="{value:.1f}{unit} " + word + " hàng rào IQR {baseline:.1f}{unit} "
                    "({score:.1f} × IQR tính từ Q3/Q1)",
    )


def rolling_zscore(values, window: int, k: float = 3.0, direction: str = BOTH,
                   min_periods: Optional[int] = None, min_std: float = 1e-6) -> Detection:
    """z against mean/std of the `window` points strictly BEFORE each point (trailing, causal)."""
    x = _as_float(values)
    if window < 2:
        raise ValueError("window must be >= 2")
    min_periods = window if min_periods is None else min_periods
    valid = ~np.isnan(x)
    center = np.nanmean(x) if valid.any() else 0.0
    xc = np.where(valid, x - center, 0.0)
    c_n = np.concatenate([[0.0], np.cumsum(valid)])
    c_s = np.concatenate([[0.0], np.cumsum(xc)])
    c_ss = np.concatenate([[0.0], np.cumsum(xc * xc)])
    idx = np.arange(len(x))
    lo = np.clip(idx - window, 0, None)
    n = c_n[idx] - c_n[lo]                  # points in [i - window, i)
    s = c_s[idx] - c_s[lo]
    ss = c_ss[idx] - c_ss[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_c = s / n
        std = np.sqrt(np.clip((ss - n * mean_c ** 2) / (n - 1), 0, None))
        scores = (xc - mean_c) / std
    usable = (n >= min_periods) & (std > min_std) & valid
    scores = np.where(usable, scores, np.nan)
    return Detection(
        method=f"rolling_{window}h",
        flags=_directional_flags(scores, k, direction),
        scores=scores,
        baseline=np.where(usable, mean_c + center, np.nan),
        explanation="{value:.1f}{unit} lệch {score:+.1f}σ so với TB " + str(window)
                    + " giờ trước đó ({baseline:.1f}{unit})",
    )


def pressure_tendency(values, hours: int = 3, threshold: float = -3.0) -> Detection:
    """Flag a pressure fall of at least |threshold| hPa over the last `hours` hours."""
    x = _as_float(values)
    previous = np.full(x.shape, np.nan)
    previous[hours:] = x[:-hours]
    change = x - previous
    with np.errstate(invalid="ignore"):
        flags = (change <= threshold) & ~np.isnan(change)
    return Detection(
        method=f"tendency_{hours}h",
        flags=flags,
        scores=change,
        baseline=previous,
        explanation="áp suất {value:.1f}{unit} giảm {score:+.1f}{unit} trong " + str(hours)
                    + " giờ (từ {baseline:.1f}{unit}; ngưỡng " + f"{threshold:+.1f}" + ")",
    )


def stuck_detect(values, min_run: int = 6, tolerance: float = 0.0) -> Detection:
    """Flag every point of a run of >= min_run consecutive (near-)identical values.

    Retrospective: the whole run is flagged once it is long enough. score = run length.
    """
    x = _as_float(values)
    run_length = np.zeros(len(x))
    flags = np.zeros(len(x), dtype=bool)
    start = 0
    for i in range(1, len(x) + 1):
        same = (i < len(x) and not np.isnan(x[i]) and not np.isnan(x[i - 1])
                and abs(x[i] - x[i - 1]) <= tolerance)
        if not same:
            length = i - start
            run_length[start:i] = length
            if length >= min_run and not np.isnan(x[start]):
                flags[start:i] = True
            start = i
    return Detection(
        method="stuck",
        flags=flags,
        scores=run_length,
        baseline=np.where(flags, x, np.nan),
        explanation="giá trị {value:.1f}{unit} không đổi {score:.0f} giờ liên tiếp",
    )


# ---------------------------------------------------------------------------
# Severity labels (meteorological categories; cross-check with NCHMF criteria in the report)
# ---------------------------------------------------------------------------

# Beaufort scale lower bounds in m/s, used in Vietnamese warnings as "cấp gió"
BEAUFORT_LOWER_MS = ((6, 10.8), (7, 13.9), (8, 17.2), (9, 20.8), (10, 24.5), (11, 28.5),
                     (12, 32.7), (13, 37.0), (14, 41.5), (15, 46.2), (16, 51.0), (17, 56.1))


def beaufort_level(speed_ms: float) -> int:
    """Beaufort level (6..17) of a wind/gust speed; 0 below level 6."""
    level = 0
    for lvl, lower in BEAUFORT_LOWER_MS:
        if speed_ms >= lower:
            level = lvl
    return level


def gust_severity(speed_ms: float) -> str:
    level = beaufort_level(speed_ms)
    return f"gió giật cấp {level}" if level else "gió giật dưới cấp 6"


def rain_24h_severity(total_mm: float) -> str:
    """24 h rainfall category: mưa nhỏ < 16 <= mưa vừa < 50 <= mưa to < 100 <= mưa rất to."""
    if total_mm >= 100:
        return "mưa rất to"
    if total_mm >= 50:
        return "mưa to"
    if total_mm >= 16:
        return "mưa vừa"
    return "mưa nhỏ"


def heat_severity(tmax_c: float) -> str:
    """Heat category from the maximum temperature: 35 / 37 / 39 °C."""
    if tmax_c >= 39:
        return "nắng nóng đặc biệt gay gắt"
    if tmax_c >= 37:
        return "nắng nóng gay gắt"
    if tmax_c >= 35:
        return "nắng nóng"
    return "ấm bất thường kéo dài"


def zscore_severity(score: float) -> str:
    """Strength of a z-score deviation: vừa (< 4σ), mạnh (4-6σ), rất mạnh (>= 6σ)."""
    magnitude = abs(score)
    if magnitude >= 6:
        return "rất mạnh"
    if magnitude >= 4:
        return "mạnh"
    return "vừa"


def rolling_max(values, window: int) -> np.ndarray:
    """Trailing maximum over `window` points including the current one (NaN if incomplete)."""
    x = _as_float(values)
    out = np.full(x.shape, np.nan)
    if len(x) >= window:
        out[window - 1:] = np.lib.stride_tricks.sliding_window_view(x, window).max(axis=1)
    return out


# ---------------------------------------------------------------------------
# Synthetic anomalies and evaluation metrics
# ---------------------------------------------------------------------------

def inject_anomalies(values, seed: int, n_spikes: int, spike_range: Tuple[float, float],
                     n_stuck: int, stuck_length: int, min_gap: int = 250,
                     spike_sign: str = BOTH, margin: int = 200
                     ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (modified copy, label mask, kind array) with spikes and stuck runs injected.

    Spikes add ±U(spike_range) to one point. A stuck run copies the value at position p into
    p+1 .. p+stuck_length. Events are at least `min_gap` points apart (so a 168 h window never
    contains a previous injection) and `margin` points away from both ends.
    kind: 0 = clean, 1 = spike, 2 = stuck.
    """
    x = _as_float(values).copy()
    rng = np.random.default_rng(seed)
    n_events = n_spikes + n_stuck
    usable = len(x) - 2 * margin - stuck_length
    if usable < n_events * min_gap:
        raise ValueError("series too short for the requested number of injections")
    # spread events: random offsets inside equal slots of width >= min_gap
    slot = usable // n_events
    positions = margin + np.arange(n_events) * slot + rng.integers(0, slot - min_gap + 1, n_events)
    kinds_order = rng.permutation(np.array([1] * n_spikes + [2] * n_stuck))
    labels = np.zeros(len(x), dtype=bool)
    kind = np.zeros(len(x), dtype=int)
    for p, k in zip(positions, kinds_order):
        if k == 1:
            magnitude = rng.uniform(*spike_range)
            if spike_sign == BOTH:
                magnitude *= rng.choice([-1.0, 1.0])
            elif spike_sign == LOW:
                magnitude = -magnitude
            x[p] += magnitude
            labels[p] = True
            kind[p] = 1
        else:
            x[p + 1:p + 1 + stuck_length] = x[p]
            labels[p + 1:p + 1 + stuck_length] = True
            kind[p + 1:p + 1 + stuck_length] = 2
    return x, labels, kind


def confusion(flags: np.ndarray, labels: np.ndarray) -> Dict[str, float]:
    """Point-wise precision / recall / F1 of flags against ground-truth labels."""
    flags = np.asarray(flags, dtype=bool)
    labels = np.asarray(labels, dtype=bool)
    tp = int((flags & labels).sum())
    fp = int((flags & ~labels).sum())
    fn = int((~flags & labels).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def count_episodes(flags: np.ndarray, max_gap: int = 6) -> int:
    """Number of alarm episodes: flagged points separated by <= max_gap points form one episode."""
    idx = np.flatnonzero(np.asarray(flags, dtype=bool))
    if len(idx) == 0:
        return 0
    return int(1 + (np.diff(idx) > max_gap).sum())


def event_metrics(times_utc, flags: np.ndarray, start, end, peak=None,
                  utc_offset_hours: int = VN_UTC_OFFSET_HOURS) -> Dict[str, object]:
    """How a detector behaved inside an event window [start, end) (datetime64 UTC).

    lead_hours: hours between the first flag in the window and `peak` (positive = before peak).
    flagged_days: distinct local days in the window with at least one flag.
    """
    t = np.asarray(times_utc, dtype="datetime64[s]")
    start, end = np.datetime64(start, "s"), np.datetime64(end, "s")
    in_window = (t >= start) & (t < end)
    hits = np.asarray(flags, dtype=bool) & in_window
    first = t[hits][0] if hits.any() else None
    lead = None
    if first is not None and peak is not None:
        lead = float((np.datetime64(peak, "s") - first) / np.timedelta64(1, "h"))
    local_days = (t[hits] + np.timedelta64(utc_offset_hours, "h")).astype("datetime64[D]")
    return {
        "detected": bool(hits.any()),
        "flagged_hours": int(hits.sum()),
        "window_hours": int(in_window.sum()),
        "flagged_days": int(len(np.unique(local_days))),
        "first_flag": first,
        "lead_hours": lead,
    }
