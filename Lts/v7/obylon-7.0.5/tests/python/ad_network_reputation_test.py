from pathlib import Path
from ad_network_reputation import AdNetworkReputationDB

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "assets" / "data" / "obylon_ad_networks.json"


def test_database_loads_and_matches_known_domains():
    db = AdNetworkReputationDB(DB_PATH)
    assert db.load() is True
    match = db.lookup("www.trafficjunky.com")
    assert match is not None
    assert match.network_id == "trafficjunky"
    assert match.contextual_score > 0.0


def test_domain_boundary_prevents_false_positive():
    db = AdNetworkReputationDB(DB_PATH)
    assert db.load() is True
    assert db.lookup("nottrafficjunky.com") is None
    assert db.lookup("trafficjunky.com.evil.example") is None


def test_subdomains_and_url_inputs_match():
    db = AdNetworkReputationDB(DB_PATH)
    assert db.load() is True
    assert db.lookup("sub.realsrv.com").network_id == "exoclick"
    assert db.lookup("https://trafficfactory.com/path?q=1").network_id == "trafficfactory"


def test_mixed_usage_is_preserved():
    db = AdNetworkReputationDB(DB_PATH)
    assert db.load() is True
    match = db.lookup("ads.propellerads.com")
    assert match is not None
    assert match.mixed_usage is True
    assert match.automatic_block is False


def test_invalid_database_fails_closed_to_no_extra_signal(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version": 999, "networks": []}', encoding='utf-8')
    db = AdNetworkReputationDB(path)
    assert db.load() is False
    assert db.lookup("trafficjunky.com") is None
