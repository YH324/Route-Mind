#!/usr/bin/env python3
"""
路网工具模块
- 加载路网图
- Dijkstra最短路径（带前驱记录，支持路径重构）
- 缓存常用路径
"""
import json
import heapq
import os
from functools import lru_cache

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NETWORK_PATH = os.path.join(MODULE_DIR, "chengdu_road_network.json")


def _resolve_network_path(network_path):
    if not network_path:
        return DEFAULT_NETWORK_PATH
    if os.path.isabs(network_path):
        return network_path
    return os.path.join(MODULE_DIR, network_path)


class RoadNetwork:
    def __init__(self, network_path):
        with open(network_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.nodes = data["nodes"]
        self.edges = data["edges"]
        self.metadata = data.get("metadata", {})
        self._cache = {}  # (start_id, mode) -> {target_id: (dist, time, prev)}
        
        # 构建邻接表
        self.adj = {}
        for e in self.edges:
            s, t = e["source"], e["target"]
            if s not in self.adj:
                self.adj[s] = []
            if t not in self.adj:
                self.adj[t] = []
            self.adj[s].append({
                "target": t,
                "dist": e["actual_dist_m"],
                "walk_time": e.get("walk_time_min", e["actual_dist_m"] / 83.3),
                "bike_time": e.get("bike_time_min"),
                "drive_time": e.get("drive_time_min"),
                "road_type": e["road_type"],
            })
            # 无向图，反向也加
            self.adj[t].append({
                "target": s,
                "dist": e["actual_dist_m"],
                "walk_time": e.get("walk_time_min", e["actual_dist_m"] / 83.3),
                "bike_time": e.get("bike_time_min"),
                "drive_time": e.get("drive_time_min"),
                "road_type": e["road_type"],
            })
        print(f"[RoadNetwork] Loaded {len(self.nodes)} nodes, {len(self.edges)} edges")

    def dijkstra_all(self, start_id, mode="walk"):
        """
        单源Dijkstra：计算start_id到所有可达节点的距离、时间和前驱节点
        返回: {node_id: (dist_m, time_min, prev_id)}
        """
        if start_id not in self.adj:
            return {}

        time_key = {"walk": "walk_time", "bike": "bike_time", "drive": "drive_time"}.get(mode, "walk_time")

        dist = {start_id: 0.0}
        time = {start_id: 0.0}
        prev = {start_id: None}
        pq = [(0.0, start_id)]
        visited = set()

        while pq:
            cur_time, cur = heapq.heappop(pq)
            if cur in visited:
                continue
            visited.add(cur)

            for edge in self.adj.get(cur, []):
                nxt = edge["target"]
                if nxt in visited:
                    continue
                edge_time = edge.get(time_key)
                if edge_time is None:
                    continue
                new_time = time[cur] + edge_time
                new_dist = dist[cur] + edge["dist"]
                if nxt not in time or new_time < time[nxt]:
                    time[nxt] = new_time
                    dist[nxt] = new_dist
                    prev[nxt] = cur
                    heapq.heappush(pq, (new_time, nxt))

        return {nid: (dist[nid], time[nid], prev[nid]) for nid in dist}

    def get_route_between(self, start_id, target_id, mode="walk"):
        """
        获取两点之间的距离、时间和路径节点ID列表
        返回: (dist_m, time_min, path_ids) 或 (None, None, None)
        """
        if start_id == target_id:
            return 0, 0, [start_id]
        if start_id not in self.adj or target_id not in self.adj:
            return None, None, None
        
        cache_key = (start_id, mode)
        if cache_key not in self._cache:
            self._cache[cache_key] = self.dijkstra_all(start_id, mode)
        
        all_dists = self._cache[cache_key]
        if target_id not in all_dists:
            return None, None, None
        
        dist_m, time_min, _ = all_dists[target_id]
        
        # 重构路径
        path = []
        cur = target_id
        while cur is not None:
            path.append(cur)
            if cur == start_id:
                break
            cur = all_dists.get(cur, (None, None, None))[2]
        
        if not path or path[-1] != start_id:
            return dist_m, time_min, []
        
        path.reverse()
        return dist_m, time_min, path

    def get_path_coords(self, path_ids):
        """将路径节点ID列表转为 [lat, lng] 坐标列表（Leaflet格式）"""
        coords = []
        for nid in path_ids:
            node = self.nodes.get(nid)
            if node:
                coords.append([node["lat"], node["lng"]])
        return coords

    def is_connected(self, poi_id):
        """检查POI是否在路网中且有连接"""
        return poi_id in self.adj and len(self.adj[poi_id]) > 0


# 全局单例，按路径隔离，避免未来加载多城市路网时误复用
_networks = {}

def get_network(network_path=None):
    resolved_path = _resolve_network_path(network_path)
    if resolved_path not in _networks:
        _networks[resolved_path] = RoadNetwork(resolved_path)
    return _networks[resolved_path]
