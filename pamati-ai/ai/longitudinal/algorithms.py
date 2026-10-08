import math
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from statistics import mean, stdev

from ai.longitudinal.interface import TrackingConfig

LIMITATIONS = [
    "Experimental descriptive research indicators, not empirically validated clinical assessments.",
    "Negative sentiment does not establish mental illness or crisis; no universal mental-health score is defined.",
    "Missing observations and refusal are not neutral sentiment; availability can bias trends.",
    "Model drift, language, culture, context and correlated measurement errors can change estimates.",
]


def validate_config(config):
    for name, low, high in (("baseline_days", 1, 180), ("minimum_baseline_interactions", 2, 500),
                           ("minimum_baseline_days", 2, 180), ("trajectory_days", 2, 60),
                           ("minimum_trajectory_days", 2, 60), ("persistence_days", 2, 30)):
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError("Invalid research history configuration")
    if (config.minimum_baseline_days > config.baseline_days
            or config.minimum_trajectory_days > config.trajectory_days
            or isinstance(config.change_threshold, bool) or not math.isfinite(config.change_threshold)
            or not 0 < config.change_threshold <= 2):
        raise ValueError("Invalid research thresholds")


def day_start(value):
    if value.tzinfo is None:
        raise ValueError("Use timezone-aware UTC observations")
    return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def dispersion(values):
    return stdev(values) if len(values) >= 2 else None


def slope(points):
    origin = points[0][0]
    xs = [(day - origin).total_seconds() / 86400 for day, _ in points]
    ys = [value for _, value in points]
    xbar, ybar = mean(xs), mean(ys)
    denominator = sum((x - xbar) ** 2 for x in xs)
    return sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys, strict=True)) / denominator if denominator else None


class DescriptiveTracking:
    identifier = "descriptive-personal-trends"
    version = "1"

    def summarize(self, observations, start, end, config=None, *, sessions=()):
        config = config or TrackingConfig()
        validate_config(config)
        start, end = day_start(start), day_start(end)
        if not 1 <= (end - start).days <= 366:
            raise ValueError("Use a one-to-366-day half-open calendar window")
        if len({o.id for o in observations}) != len(observations):
            raise ValueError("Observation IDs must be unique")
        grouped = defaultdict(list)
        for observation in observations:
            if (isinstance(observation.score, bool) or not math.isfinite(observation.score)
                    or not -1 <= observation.score <= 1):
                raise ValueError("Invalid normalized observation score")
            day = day_start(observation.timestamp)
            if start - timedelta(days=config.baseline_days) <= day < end:
                grouped[(observation.session_id, day)].append(observation)
        interactions = []
        by_day = defaultdict(list)
        for (session_id, day), records in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
            scores = [r.score for r in records]
            segment = {"session_id": session_id, "day": day.date().isoformat(), "mean": mean(scores),
                       "observation_count": len(records), "source_observation_ids": [r.id for r in records],
                       "uncertainty": {"method": "descriptive_source_dispersion", "standard_deviation": dispersion(scores),
                                       "confidence_available_count": sum(r.confidence is not None for r in records),
                                       "source_uncertainty_available_count": sum(r.uncertainty is not None for r in records),
                                       "calibrated": False}}
            interactions.append(segment)
            by_day[day].append(segment)
        values_by_day = {day: mean(s["mean"] for s in segments) for day, segments in by_day.items()}
        frequency = defaultdict(set)
        for session_id, timestamp in sessions:
            frequency[day_start(timestamp)].add(session_id)
        daily, run, previous_delta, previous_day = [], 0, None, None
        previous_value, previous_baseline = None, None
        for index in range((end - start).days):
            day = start + timedelta(days=index)
            segments = by_day.get(day, [])
            values = [s["mean"] for s in segments]
            historical = [(d, v) for d, v in sorted(values_by_day.items())
                          if day - timedelta(days=config.baseline_days) <= d < day]
            history_segments = [s for s in interactions
                                if (day - timedelta(days=config.baseline_days)).date().isoformat() <= s["day"] < day.date().isoformat()]
            enough = (len(history_segments) >= config.minimum_baseline_interactions
                      and len(historical) >= config.minimum_baseline_days)
            baseline = mean(v for _, v in historical) if enough else None
            value = mean(values) if values else None
            delta = value - baseline if value is not None and baseline is not None else None
            direction = "above_baseline" if delta is not None and delta >= config.change_threshold else (
                "below_baseline" if delta is not None and delta <= -config.change_threshold else None)
            prior_direction = daily[-1]["change_direction"] if daily else None
            run = run + 1 if direction and direction == prior_direction and previous_day == day - timedelta(days=1) else (1 if direction else 0)
            recovery = bool(delta is not None and previous_delta is not None
                            and abs(previous_delta) >= config.change_threshold
                            and previous_value is not None and previous_baseline is not None
                            and abs(value - previous_baseline) < abs(previous_value - previous_baseline))
            points = [(d, v) for d, v in sorted(values_by_day.items())
                      if day - timedelta(days=config.trajectory_days - 1) <= d <= day]
            trajectory = slope(points) if value is not None and len(points) >= config.minimum_trajectory_days else None
            daily.append({"day": day.date().isoformat(), "mean": value,
                          "interaction_count": len(segments), "observation_count": sum(s["observation_count"] for s in segments),
                          "recorded_session_starts": len(frequency.get(day, set())),
                          "baseline": {"status": "available" if enough else "insufficient_history",
                                       "mean": baseline, "interaction_count": len(history_segments), "day_count": len(historical),
                                       "standard_deviation": dispersion([v for _, v in historical]) if enough else None},
                          "delta_from_baseline": delta, "slope_per_day": trajectory,
                          "trajectory_day_count": len(points), "change_direction": direction,
                          "consecutive_change_days": run, "persistent_pattern": run >= config.persistence_days,
                          "returning_toward_baseline": recovery,
                          "uncertainty": {"standard_deviation": dispersion(values), "calibrated": False,
                                          "method": "descriptive_interaction_dispersion", "missing": not bool(values)}})
            previous_delta, previous_day = delta, day
            previous_value, previous_baseline = value, baseline
        weeks = defaultdict(list)
        for row in daily:
            date = datetime.fromisoformat(row["day"])
            monday = (date - timedelta(days=date.weekday())).date().isoformat()
            weeks[monday].append(row)
        weekly = []
        for monday, rows in sorted(weeks.items()):
            observed = [r["mean"] for r in rows if r["mean"] is not None]
            week_end = (datetime.fromisoformat(monday) + timedelta(days=7)).date().isoformat()
            session_ids = {s["session_id"] for s in interactions if monday <= s["day"] < week_end
                           and start.date().isoformat() <= s["day"] < end.date().isoformat()}
            weekly.append({"week_start": monday, "mean": mean(observed) if observed else None,
                           "observed_days": len(observed), "included_days": len(rows), "missing_days": len(rows) - len(observed),
                           "partial_week": len(rows) != 7, "interaction_count": len(session_ids),
                           "uncertainty": {"standard_deviation": dispersion(observed), "calibrated": False}})
        return {"schema_version": "longitudinal-observation-v1", "experimental": True,
                "algorithm": {"identifier": self.identifier, "version": self.version}, "configuration": asdict(config),
                "window_start": start.isoformat(), "window_end": end.isoformat(), "timezone": "UTC",
                "interactions": [s for s in interactions if start.date().isoformat() <= s["day"] < end.date().isoformat()],
                "daily": daily, "weekly": weekly, "source_observation_ids": [r.id for records in grouped.values() for r in records],
                "limitations": LIMITATIONS, "clinical_interpretation": "not_supported"}
