#!/usr/bin/env python3
"""
POI 路网生成器

策略：基于POI的k近邻稀疏路网
- 每个POI作为图节点
- 每个POI连接最近8-12个邻居（2000m范围内）
- 边权重 = 直线距离 × 道路系数（估计实际道路绕行）
- 道路系数取决于区域密度和道路类型

输出：chengdu_road_network.json
{
  "nodes": {poi_id: {name, lng, lat, type}},
  "edges": [{"source": id, "target": id, "distance_m": float, "road_type": str, "walk_time_min": float}]
}
"""
import json
import math
import sys
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)


def haversine(lng1, lat1, lng2, lat2):
    """米"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_grid_index(pois, cell_size_m=500):
    """将POI按网格索引，加速最近邻搜索"""
    # 约111km/度纬度，约100km/度经度(成都)
    lat_cell = cell_size_m / 111000
    lng_cell = cell_size_m / 100000

    grid = defaultdict(list)
    for p in pois:
        cell_x = int(p["longitude"] / lng_cell)
        cell_y = int(p["latitude"] / lat_cell)
        grid[(cell_x, cell_y)].append(p)
    return grid, lng_cell, lat_cell


def get_neighbors_grid(poi, grid, lng_cell, lat_cell, radius_m=2000):
    """通过网格索引获取radius_m范围内的候选邻居"""
    px, py = int(poi["longitude"] / lng_cell), int(poi["latitude"] / lat_cell)
    # 计算需要搜索的网格数
    n_cells = int(radius_m / 500) + 1
    candidates = []
    for dx in range(-n_cells, n_cells + 1):
        for dy in range(-n_cells, n_cells + 1):
            candidates.extend(grid.get((px + dx, py + dy), []))
    return [c for c in candidates if c["poi_id"] != poi["poi_id"]]


def decide_road_type(poi_a, poi_b, density_a, density_b):
    """根据POI特征决定道路类型"""
    avg_density = (density_a + density_b) / 2
    dist = haversine(poi_a["longitude"], poi_a["latitude"],
                     poi_b["longitude"], poi_b["latitude"])

    mix = "{}:{}".format(poi_a["poi_id"], poi_b["poi_id"])
    bucket = stable_bucket(mix + ":road", 100)

    # 高密度区域更可能是小巷/步行街，低密度区域更可能是主干道。
    if avg_density >= 30:
        if dist < 300:
            return "步行街" if bucket < 58 else "小巷"
        return "次干道" if bucket < 55 else "小巷"
    elif avg_density >= 15:
        if dist < 400:
            return "次干道" if bucket < 62 else "步行街"
        return "主干道" if bucket < 60 else "次干道"
    return "主干道" if bucket < 72 else "快速路"


def stable_bucket(value, modulo):
    text = str(value)
    acc = 2166136261
    for ch in text:
        acc ^= ord(ch)
        acc = (acc * 16777619) & 0xFFFFFFFF
    return acc % modulo


def road_coefficient_for_edge(road_type, source_id, target_id):
    """Deterministic detour coefficient for a road segment."""
    coeffs = {
        "快速路": (1.15, 1.30),
        "主干道": (1.20, 1.40),
        "次干道": (1.30, 1.55),
        "步行街": (1.40, 1.70),
        "小巷": (1.50, 1.90),
    }
    lo, hi = coeffs.get(road_type, (1.3, 1.6))
    ratio = stable_bucket("{}:{}:{}".format(source_id, target_id, road_type), 1000) / 999.0
    return lo + (hi - lo) * ratio


def speed_kmh(road_type, mode):
    """不同出行方式在不同道路上的速度"""
    base = {
        "walk": {"快速路": 4, "主干道": 5, "次干道": 5, "步行街": 4, "小巷": 3},
        "bike": {"快速路": 0, "主干道": 12, "次干道": 10, "步行街": 0, "小巷": 8},
        "drive": {"快速路": 40, "主干道": 25, "次干道": 20, "步行街": 0, "小巷": 10},
        "bus": {"快速路": 30, "主干道": 20, "次干道": 15, "步行街": 0, "小巷": 0},
    }
    return base.get(mode, {}).get(road_type, 0)


def generate_network(poi_path, out_path, k_neighbors=10, max_radius_m=2000):
    with open(poi_path, "r", encoding="utf-8") as f:
        pois = json.load(f)

    print(f"Loaded {len(pois)} POIs")
    print("Building spatial index...")
    grid, lng_cell, lat_cell = build_grid_index(pois, cell_size_m=1000)

    nodes = {}
    edges = []
    edge_set = set()  # 避免重复边

    print(f"Generating edges (k={k_neighbors}, max_radius={max_radius_m}m)...")
    # Pre-build POI lookup
    poi_lookup = {p["poi_id"]: p for p in pois}
    
    for i, poi in enumerate(pois, 1):
        pid = poi["poi_id"]
        nodes[pid] = {
            "name": poi["name"],
            "lng": poi["longitude"],
            "lat": poi["latitude"],
            "type": infer_real_type(poi),
        }

        # 找候选邻居（限制搜索范围）
        candidates = get_neighbors_grid(poi, grid, lng_cell, lat_cell, radius_m=max_radius_m)

        # 快速距离过滤（用近似平方距离避免haversine）
        px, py = poi["longitude"], poi["latitude"]
        filtered = []
        for c in candidates:
            # 快速拒绝：经纬度差超过阈值
            dx = abs(c["longitude"] - px)
            dy = abs(c["latitude"] - py)
            if dx > 0.02 or dy > 0.018:  # 约2000m
                continue
            d = haversine(px, py, c["longitude"], c["latitude"])
            if d <= max_radius_m:
                filtered.append((c, d))

        filtered.sort(key=lambda x: x[1])
        selected = filtered[:k_neighbors]

        density = poi.get("grid_density", 1)
        for neighbor, straight_dist in selected:
            nid = neighbor["poi_id"]
            key = tuple(sorted([pid, nid]))
            if key in edge_set:
                continue
            edge_set.add(key)

            road_type = decide_road_type(poi, neighbor, density, neighbor.get("grid_density", 1))
            coeff = road_coefficient_for_edge(road_type, pid, nid)
            actual_dist = straight_dist * coeff
            walk_time = actual_dist / (speed_kmh(road_type, "walk") * 1000 / 60)
            bike_time = actual_dist / (speed_kmh(road_type, "bike") * 1000 / 60) if speed_kmh(road_type, "bike") > 0 else None
            drive_time = actual_dist / (speed_kmh(road_type, "drive") * 1000 / 60) if speed_kmh(road_type, "drive") > 0 else None

            edges.append({
                "source": pid, "target": nid,
                "straight_dist_m": round(straight_dist, 1),
                "actual_dist_m": round(actual_dist, 1),
                "road_type": road_type,
                "coefficient": round(coeff, 2),
                "walk_time_min": round(walk_time, 1),
                "bike_time_min": round(bike_time, 1) if bike_time else None,
                "drive_time_min": round(drive_time, 1) if drive_time else None,
            })

        if i % 10000 == 0:
            elapsed = i / (i / max(1, i))  # dummy
            print(f"  {i}/{len(pois)} POIs, {len(edges)} edges")

    result = {
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "avg_degree": round(len(edges) * 2 / len(nodes), 1),
            "max_radius_m": max_radius_m,
            "k_neighbors": k_neighbors,
        },
        "nodes": nodes,
        "edges": edges,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))

    print(f"\nSaved to {out_path}")
    print(f"Nodes: {len(nodes)}, Edges: {len(edges)}")
    print(f"Avg degree: {result['metadata']['avg_degree']}")

    # 统计道路类型
    road_type_dist = defaultdict(int)
    for e in edges:
        road_type_dist[e["road_type"]] += 1
    print("\nRoad type distribution:")
    for rt, c in sorted(road_type_dist.items(), key=lambda x: -x[1]):
        print(f"  {rt}: {c} ({c/len(edges)*100:.1f}%)")

    # 统计距离
    actual_dists = [e["actual_dist_m"] for e in edges]
    print(f"\nActual distance stats:")
    print(f"  Min: {min(actual_dists):.0f}m, Max: {max(actual_dists):.0f}m")
    print(f"  Avg: {sum(actual_dists)/len(actual_dists):.0f}m, Median: {sorted(actual_dists)[len(actual_dists)//2]:.0f}m")

    # 统计绕行系数
    coeffs = [e["coefficient"] for e in edges]
    print(f"\nCoefficient stats:")
    print(f"  Avg: {sum(coeffs)/len(coeffs):.2f}, Median: {sorted(coeffs)[len(coeffs)//2]:.2f}")


# 需要导入infer_real_type
from ugc_type_profiles import infer_real_type


if __name__ == "__main__":
    generate_network("wuhou_jinjiang_pois.json", "chengdu_road_network.json")
