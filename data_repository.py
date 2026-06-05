"""
Process-level local data repository.

The project uses local generated data for the competition, but the service
should still treat those files like a production data source: load once,
validate required assets, expose readiness, and keep request code away from
raw file IO.
"""
import json
import os
import threading
import time

from mock_api import MockApiClient


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "output")


REQUIRED_ASSETS = {
    "pois": os.path.join(BASE_DIR, "wuhou_jinjiang_pois.json"),
    "business_hours": os.path.join(BASE_DIR, "poi_business_hours.json"),
    "road_network": os.path.join(BASE_DIR, "chengdu_road_network.json"),
    "gt_index": os.path.join(DATA_DIR, "gt_index.json"),
    "type_index": os.path.join(DATA_DIR, "type_index.json"),
    "spatial_index": os.path.join(DATA_DIR, "spatial_index.json"),
}

OPTIONAL_ASSETS = {
    "poi_knn_cache": os.path.join(DATA_DIR, "poi_knn_cache.json"),
    "poi_embeddings": os.path.join(DATA_DIR, "poi_embeddings.npy"),
    "poi_embedding_ids": os.path.join(DATA_DIR, "poi_embedding_ids.json"),
}


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _file_info(path):
    exists = os.path.exists(path)
    info = {"path": path, "exists": exists}
    if exists:
        stat = os.stat(path)
        info.update({
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "mtime": int(stat.st_mtime),
        })
    return info


class RepositoryError(Exception):
    pass


class LocalDataRepository:
    def __init__(self):
        self._lock = threading.RLock()
        self._clients = {}
        self._gt_index = None
        self._type_index = None
        self._spatial_index = None
        self._started_at = time.time()
        self._warmup_ms = None

    def check_assets(self):
        assets = {}
        missing = []
        for name, path in REQUIRED_ASSETS.items():
            info = _file_info(path)
            assets[name] = info
            if not info["exists"]:
                missing.append(name)
        for name, path in OPTIONAL_ASSETS.items():
            assets[name] = _file_info(path)
        return assets, missing

    def assert_ready(self):
        _, missing = self.check_assets()
        if missing:
            raise RepositoryError("Missing required data assets: {}".format(", ".join(missing)))

    def warmup(self):
        """Load core indexes and POI data once for stable first-request latency."""
        started = time.time()
        with self._lock:
            self.assert_ready()
            client = self.get_client("chengdu")
            client._load_pois()
            self.gt_index
            self.type_index
            self.spatial_index
            self._warmup_ms = round((time.time() - started) * 1000)
            return self._warmup_ms

    def get_client(self, city):
        city_key = str(city or "chengdu")
        with self._lock:
            client = self._clients.get(city_key)
            if client is None:
                client = MockApiClient(city=city_key, simulate_latency_ms=0, simulate_quota=False)
                self._clients[city_key] = client
            return client

    @property
    def gt_index(self):
        with self._lock:
            if self._gt_index is None:
                self._gt_index = _read_json(REQUIRED_ASSETS["gt_index"])
            return self._gt_index

    @property
    def type_index(self):
        with self._lock:
            if self._type_index is None:
                self._type_index = _read_json(REQUIRED_ASSETS["type_index"])
            return self._type_index

    @property
    def spatial_index(self):
        with self._lock:
            if self._spatial_index is None:
                self._spatial_index = _read_json(REQUIRED_ASSETS["spatial_index"])
            return self._spatial_index

    def search_pois(self, city, center_lng, center_lat, radius, page_size=10000):
        client = self.get_client(city)
        return client.search_pois(
            center_lng,
            center_lat,
            radius=radius,
            page=1,
            page_size=page_size,
        )

    def status(self):
        assets, missing = self.check_assets()
        loaded_clients = {}
        for city, client in self._clients.items():
            loaded_clients[city] = {
                "pois_loaded": client._pois is not None,
                "poi_count": len(client._pois) if client._pois is not None else 0,
            }
        return {
            "ready": not missing,
            "missing": missing,
            "uptime_s": round(time.time() - self._started_at, 1),
            "warmup_ms": self._warmup_ms,
            "indexes_loaded": {
                "gt_index": self._gt_index is not None,
                "type_index": self._type_index is not None,
                "spatial_index": self._spatial_index is not None,
            },
            "clients": loaded_clients,
            "assets": assets,
        }


repository = LocalDataRepository()
