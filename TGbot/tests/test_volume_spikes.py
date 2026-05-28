import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitor.volume_spikes import detect_spikes


def test_spike_above_threshold():
    prev = {"BTC": 1_000_000_000, "ETH": 500_000_000}
    curr = {"BTC": 1_600_000_000, "ETH": 520_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert len(results) == 1
    assert results[0]["coin"] == "BTC"
    assert abs(results[0]["pct"] - 60.0) < 0.01
    assert results[0]["vol_prev"] == 1_000_000_000
    assert results[0]["vol_curr"] == 1_600_000_000


def test_spike_below_threshold_excluded():
    prev = {"BTC": 1_000_000_000}
    curr = {"BTC": 1_300_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []


def test_spike_below_min_volume_excluded():
    prev = {"SMALL": 5_000_000}
    curr = {"SMALL": 10_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []


def test_spike_zero_prev_volume_skipped():
    prev = {"BTC": 0}
    curr = {"BTC": 1_000_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []


def test_spike_coin_missing_from_prev_skipped():
    prev = {}
    curr = {"BTC": 1_000_000_000}
    settings = {"threshold_pct": 50, "min_volume_m": 10}
    results = detect_spikes(prev, curr, settings)
    assert results == []
