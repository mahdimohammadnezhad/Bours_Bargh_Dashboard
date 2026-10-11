from datetime import datetime, timedelta, timezone

import pytest

from app.analytics import anomalies as anomaly_detectors
from app.analytics.decision_support import build_insights
from app.analytics.regime import classify_regime
from app.analytics.stats import (
    descriptive_stats,
    percentile_rank,
    pct_change,
    rolling_mean,
    rolling_std,
    zscore_of_latest,
)
from app.models.market import MarketQuote
from app.services import analytics_service


def _times(n: int) -> list[datetime]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [base + timedelta(minutes=i) for i in range(n)]


# ---- stats.py ----------------------------------------------------------


def test_descriptive_stats_basic():
    stats = descriptive_stats([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats.count == 5
    assert stats.mean == 3.0
    assert stats.median == 3.0
    assert stats.minimum == 1.0
    assert stats.maximum == 5.0
    assert stats.coefficient_of_variation is not None


def test_descriptive_stats_rejects_empty():
    with pytest.raises(ValueError):
        descriptive_stats([])


def test_descriptive_stats_zero_mean_has_no_cv():
    stats = descriptive_stats([-1.0, 0.0, 1.0])
    assert stats.mean == 0.0
    assert stats.coefficient_of_variation is None


def test_percentile_rank_of_max_is_100():
    series = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_rank(50.0, series) == 100.0
    assert percentile_rank(10.0, series) == 20.0


def test_rolling_mean_aligns_and_fills_none():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    means = rolling_mean(values, window=3)
    assert means[:2] == [None, None]
    assert means[2] == 2.0  # mean(1,2,3)
    assert means[4] == 4.0  # mean(3,4,5)


def test_rolling_std_of_flat_series_is_zero():
    values = [5.0] * 10
    stds = rolling_std(values, window=4)
    assert all(s == 0.0 for s in stds[3:])


def _jittered_baseline(n: int) -> list[float]:
    """A baseline with small, realistic variation - not a perfectly flat
    series, so std-dev based detectors have something to measure against."""
    pattern = [10.0, 10.3, 9.7, 10.1, 9.9]
    return [pattern[i % len(pattern)] for i in range(n)]


def test_zscore_of_latest_flags_spike():
    values = _jittered_baseline(20) + [100.0]
    z = zscore_of_latest(values, window=20)
    assert z is not None
    assert z > 5


def test_zscore_of_latest_none_when_insufficient_history():
    assert zscore_of_latest([1.0, 2.0], window=20) is None


def test_pct_change_handles_zero_previous():
    assert pct_change(5.0, 0.0) is None
    assert pct_change(11.0, 10.0) == pytest.approx(0.1)


# ---- anomalies.py -------------------------------------------------------


def test_rolling_zscore_detects_injected_spike():
    values = _jittered_baseline(25) + [500.0]
    ts = _times(len(values))
    found = anomaly_detectors.rolling_zscore_anomalies(ts, values, "price", "tsetmc")
    assert len(found) == 1
    assert found[0].observed_value == 500.0
    assert found[0].severity is not None


def test_flat_series_has_no_zscore_anomalies():
    values = [100.0] * 30
    ts = _times(len(values))
    assert anomaly_detectors.rolling_zscore_anomalies(ts, values, "price", "tsetmc") == []


def test_iqr_detects_outlier():
    values = [10.0, 11.0, 9.0, 10.5, 9.5, 10.0, 11.0, 9.0, 10.5, 200.0]
    ts = _times(len(values))
    found = anomaly_detectors.iqr_anomalies(ts, values, "price", "tsetmc")
    assert any(a.observed_value == 200.0 for a in found)


def test_robust_zscore_detects_outlier_with_resistant_series():
    # a couple of pre-existing mild outliers shouldn't blind the MAD-based
    # detector to the much larger spike at the end.
    values = _jittered_baseline(10) + [15.0, -5.0] + _jittered_baseline(5) + [500.0]
    ts = _times(len(values))
    found = anomaly_detectors.robust_zscore_anomalies(ts, values, "price", "tsetmc")
    assert any(a.observed_value == 500.0 for a in found)


def test_percentile_anomalies_needs_minimum_points():
    values = [1.0, 2.0, 3.0]
    ts = _times(len(values))
    assert anomaly_detectors.percentile_anomalies(ts, values, "price", "tsetmc") == []


def test_detect_all_merges_methods():
    values = _jittered_baseline(25) + [1000.0]
    ts = _times(len(values))
    found = anomaly_detectors.detect_all(ts, values, "price", "tsetmc")
    methods = {a.method for a in found}
    assert "rolling_zscore" in methods
    assert all(a.metric == "price" and a.source == "tsetmc" for a in found)


# ---- regime.py ------------------------------------------------------------


def test_classify_regime_flags_high_price_at_series_max():
    prices = [float(i) for i in range(1, 101)]  # latest (100) is the max -> 100th percentile
    result = classify_regime(prices, None, None, None)
    assert "high_price" in result.labels
    assert "abnormal_price" in result.labels


def test_classify_regime_normal_for_flat_series():
    prices = [50.0] * 30
    result = classify_regime(prices, None, None, None)
    assert result.labels == ["normal"]


def test_classify_regime_includes_volume_percentile_when_available():
    prices = [50.0] * 30
    volumes = [100.0] * 29 + [1000.0]
    result = classify_regime(prices, volumes, None, None)
    assert "volume_percentile" in result.observed
    assert "high_volume" in result.labels


# ---- decision_support.py ---------------------------------------------------


def test_build_insights_price_percentile_present():
    prices = [float(i) for i in range(1, 30)]
    insights = build_insights(prices, None, "the last 29 observations")
    assert any("percentile" in i.text for i in insights)


def test_build_insights_flags_weak_confirmation():
    prices = [10.0, 11.0]  # price went up
    volumes = [100.0, 50.0]  # volume went down
    insights = build_insights(prices, volumes, "the last 2 observations", volume_zscore_window=1)
    assert any("weak confirmation" in i.text for i in insights)


def test_build_insights_empty_for_too_little_data():
    insights = build_insights([1.0, 2.0], None, "n/a")
    # fewer than 5 points -> no percentile insight generated
    assert insights == []


# ---- analytics_service.py (DB-backed) --------------------------------------


async def _seed_quotes(db_session, n: int, source_id="tsetmc", symbol="IR-ELEC-001", spike_at: int | None = None):
    # Anchored to "now" (not a fixed date): analytics_service queries a
    # rolling lookback window ending at datetime.now(), so fixture data must
    # actually fall inside it.
    base = datetime.now(timezone.utc) - timedelta(days=1)
    for i in range(n):
        price = 100.0 + (i % 5)
        if spike_at is not None and i == spike_at:
            price = 900.0
        db_session.add(
            MarketQuote(
                observed_at=base + timedelta(minutes=i),
                source_id=source_id,
                source_symbol=symbol,
                last_price=price,
                volume=1000.0 + i,
                transaction_count=10,
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_overview_insufficient_data(db_session):
    await _seed_quotes(db_session, n=5)
    out = await analytics_service.get_overview(db_session, "tsetmc", "IR-ELEC-001")
    assert out.status == "insufficient_data"
    assert out.available_points == 5


@pytest.mark.asyncio
async def test_get_overview_ok_with_enough_data(db_session):
    await _seed_quotes(db_session, n=40)
    out = await analytics_service.get_overview(db_session, "tsetmc", "IR-ELEC-001")
    assert out.status == "ok"
    assert out.available_points == 40
    assert out.price_stats is not None
    assert out.regime is not None
    assert len(out.insights) >= 1


@pytest.mark.asyncio
async def test_get_anomalies_ok_detects_seeded_spike(db_session):
    await _seed_quotes(db_session, n=40, spike_at=35)
    out = await analytics_service.get_anomalies(db_session, "tsetmc", "IR-ELEC-001")
    assert out.status == "ok"
    assert any(a.observed_value == 900.0 for a in out.anomalies)


@pytest.mark.asyncio
async def test_get_overview_scoped_to_source_and_symbol(db_session):
    await _seed_quotes(db_session, n=40, source_id="tsetmc", symbol="IR-ELEC-001")
    await _seed_quotes(db_session, n=3, source_id="iee_new", symbol="OTHER")
    out = await analytics_service.get_overview(db_session, "iee_new", "OTHER")
    assert out.status == "insufficient_data"
    assert out.available_points == 3
