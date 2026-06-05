#!/usr/bin/env python3
"""
POI-KNN 懒加载缓存图

核心思路：
1. 第一次调用某起点的路网距离时，走 Dijkstra 并缓存结果
2. 后续再遇到同一起点，直接读缓存，零 Dijkstra
3. 默认读取 poi_knn_cache.json；设置 persist=True 时才把新增距离写回磁盘

请求内重复距离会直接命中缓存；需要跨进程更新缓存时开启 PERSIST_KNN_CACHE=1。
"""
import json
import os
import time
import uuid

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "poi_knn_cache.json")


class PoiKnnGraph:
    """POI 路网距离缓存图"""

    def __init__(self, network, cache_path=CACHE_PATH, max_cache_size_mb=200, persist=False):
        self.network = network
        self.cache_path = cache_path
        self._cache = {}  # {from_id: {to_id: {"dist_m": x, "time_min": y}}}
        self._hit = 0
        self._miss = 0
        self._max_size_mb = max_cache_size_mb
        self._persist = persist
        self._dirty = False
        self._load()

    def _load(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                size_mb = os.path.getsize(self.cache_path) / (1024 * 1024)
                print("[KNN] Loaded cache: {} entries, {:.1f} MB".format(
                    sum(len(v) for v in self._cache.values()), size_mb))
            except Exception as e:
                print("[KNN] Cache load failed:", e)
                self._cache = {}
        else:
            self._cache = {}

    def save(self):
        if not self._persist or not self._dirty:
            return
        cache_dir = os.path.dirname(self.cache_path)
        os.makedirs(cache_dir, exist_ok=True)
        tmp_path = "{}.{}.tmp".format(self.cache_path, uuid.uuid4().hex)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, self.cache_path)
            size_mb = os.path.getsize(self.cache_path) / (1024 * 1024)
            print("[KNN] Saved cache: {} entries, {:.1f} MB".format(
                sum(len(v) for v in self._cache.values()), size_mb))
            self._dirty = False
        except OSError as e:
            print("[KNN] Cache save skipped:", e)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def get_distance(self, from_id, to_id, mode="walk"):
        """获取两点间路网距离，优先读缓存，未命中则走 Dijkstra"""
        if from_id == to_id:
            return 0.0, 0.0

        # 查缓存
        row = self._cache.get(from_id)
        if row and to_id in row:
            self._hit += 1
            d = row[to_id]
            return d["dist_m"], d["time_min"]

        # 未命中：走 Dijkstra
        self._miss += 1
        dist_m, time_min, _ = self.network.get_route_between(from_id, to_id, mode)

        if dist_m is not None:
            # 双向缓存（路网是无向图）
            if from_id not in self._cache:
                self._cache[from_id] = {}
            if to_id not in self._cache:
                self._cache[to_id] = {}
            self._cache[from_id][to_id] = {"dist_m": round(dist_m, 2), "time_min": round(time_min, 2)}
            self._cache[to_id][from_id] = {"dist_m": round(dist_m, 2), "time_min": round(time_min, 2)}
            self._dirty = True

        return dist_m, time_min

    def get_neighbors(self, from_id, candidate_ids, mode="walk", top_k=20):
        """
        获取 from_id 到 candidate_ids 中各点的距离，返回 [(to_id, dist_m, time_min), ...]
        按距离排序，只返回 top_k
        """
        results = []
        for cid in candidate_ids:
            if cid == from_id:
                continue
            dist_m, time_min = self.get_distance(from_id, cid, mode)
            if dist_m is not None:
                results.append((cid, dist_m, time_min))
        results.sort(key=lambda x: x[1])
        return results[:top_k]

    def stats(self):
        total = self._hit + self._miss
        if total == 0:
            return "KNN: no queries"
        hit_rate = self._hit / total * 100
        return "KNN: hit={} miss={} total={} hit_rate={:.1f}%".format(
            self._hit, self._miss, total, hit_rate)
