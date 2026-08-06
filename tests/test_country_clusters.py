from src.geography.country_clusters import build_country_clusters
from src.geography.country_neighbors import load_country_neighbors


def test_small_country_joins_largest_contiguous_neighbor():
    neighbors = {
        **load_country_neighbors(),
        "OM": ["AE", "QA", "SA"],
        "EC": ["CO", "PE"],
        "PE": ["BR", "CO", "EC"],
        "CO": ["BR", "EC", "PE", "VE"],
    }
    counts = {"SA": 40, "AE": 12, "QA": 6, "OM": 1, "PE": 18, "CO": 30, "EC": 2}
    centroids = {
        "SA": (24.0, 45.0),
        "AE": (24.0, 54.0),
        "QA": (25.5, 51.5),
        "OM": (21.0, 57.0),
        "PE": (-9.0, -75.0),
        "CO": (4.0, -74.0),
        "EC": (-1.8, -78.0),
    }
    _, mapping = build_country_clusters(
        counts,
        centroids,
        min_size=3,
        neighbors=neighbors,
    )
    assert mapping["OM"] == mapping["SA"]
    assert mapping["EC"] == mapping["CO"]


def test_small_country_stays_within_continent():
    neighbors = {
        **load_country_neighbors(),
        "FJ": ["VU"],
        "VU": ["FJ"],
        "WS": ["WS"],
        "OM": ["AE", "SA"],
        "NG": ["CM"],
        "MH": [],
    }
    counts = {
        "US": 100,
        "AU": 80,
        "CM": 12,
        "FJ": 1,
        "VU": 1,
        "WS": 1,
        "OM": 1,
        "NG": 1,
        "MH": 1,
        "SA": 20,
    }
    centroids = {
        "US": (39.0, -98.0),
        "AU": (-25.0, 133.0),
        "CM": (6.0, 12.0),
        "FJ": (-18.0, 178.0),
        "VU": (-16.0, 167.0),
        "WS": (-14.0, -172.0),
        "OM": (21.0, 57.0),
        "NG": (9.6, 8.1),
        "MH": (7.0, 171.0),
        "SA": (24.0, 45.0),
    }
    _, mapping = build_country_clusters(
        counts,
        centroids,
        min_size=3,
        neighbors=neighbors,
    )
    assert mapping["OM"] == mapping["SA"]
    assert mapping["MH"] == mapping["AU"]
    assert mapping["FJ"] == mapping["AU"]
    assert mapping["NG"] == mapping["CM"]
    assert mapping["NG"] != mapping["OM"]


def test_anchor_country_keeps_own_cluster():
    counts = {"US": 100, "CA": 50, "MX": 20}
    centroids = {
        "US": (39.0, -98.0),
        "CA": (56.0, -96.0),
        "MX": (23.0, -102.0),
    }
    clusters, mapping = build_country_clusters(counts, centroids, min_size=3)
    assert mapping["US"] == "cluster-US"
    assert mapping["MX"] == "cluster-MX"
    assert all(cluster["attendee_count"] >= 3 for cluster in clusters)
