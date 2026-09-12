from scan_pressure import ScanPressure, ScanPressureController


def test_unknown_host_normal():
    c = ScanPressureController()
    d = c.update(reputation=0.0, monetization=0.0, telemetry_age_sec=float('inf'))
    assert d.state is ScanPressure.NORMAL
    assert d.interval_sec == 1.0


def test_reputation_alone_only_elevates_at_most():
    c = ScanPressureController()
    d = c.update(reputation=1.0, monetization=0.0, telemetry_age_sec=1.0)
    assert d.state in (ScanPressure.NORMAL, ScanPressure.ELEVATED)
    assert d.state is not ScanPressure.AGGRESSIVE


def test_reputation_plus_independent_signal_goes_aggressive():
    c = ScanPressureController()
    d = c.update(reputation=1.0, monetization=0.8, lexical=0.75, dom=0.35, telemetry_age_sec=1.0)
    assert d.state is ScanPressure.AGGRESSIVE
    assert d.interval_sec == 0.35
    assert d.ocr_due
    assert d.evidence_due


def test_stale_reputation_does_not_escalate():
    c = ScanPressureController()
    d = c.update(reputation=1.0, monetization=1.0, lexical=0.0, dom=0.0, telemetry_age_sec=30.0)
    assert d.state is ScanPressure.NORMAL
    assert d.score == 0.2
    d2 = c.update(reputation=1.0, monetization=0.0, lexical=0.0, dom=0.0, telemetry_age_sec=30.0)
    assert d2.state is ScanPressure.NORMAL


def test_hysteresis_and_decay():
    c = ScanPressureController()
    now = 100.0
    d = c.update(reputation=0.8, monetization=0.8, lexical=0.8, dom=0.5, telemetry_age_sec=1.0, now=now)
    assert d.state is ScanPressure.AGGRESSIVE
    for i in range(1, 5):
        d = c.update(now=now + 5 + i, telemetry_age_sec=float('inf'))
    assert d.state is ScanPressure.ELEVATED
    for i in range(1, 5):
        d = c.update(now=now + 15 + i, telemetry_age_sec=float('inf'))
    assert d.state is ScanPressure.NORMAL


def test_mixed_usage_is_honored_by_input_value():
    c = ScanPressureController()
    d = c.update(reputation=0.25, monetization=0.25, lexical=0.1, telemetry_age_sec=1.0)
    assert d.state is ScanPressure.NORMAL


def test_bounds_never_below_minimum():
    c = ScanPressureController()
    d = c.update(reputation=1.0, monetization=1.0, lexical=1.0, dom=1.0, telemetry_age_sec=1.0)
    assert d.interval_sec >= c.MIN_INTERVAL
