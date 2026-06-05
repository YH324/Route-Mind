"""
语义搜索模块
- 加载 POI embedding 和 id 映射
- 提供 query -> top-k POI 的语义搜索
- 集成到路线规划引擎中
"""
import json
import os
import urllib.request
import numpy as np

from config import GLM_API_KEY, DATA_DIR

EMBEDDING_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"


class SemanticIndex:
    """语义搜索索引"""
    
    def __init__(self, emb_path=None, ids_path=None, desc_path=None):
        self.emb_path = emb_path or os.path.join(DATA_DIR, "poi_embeddings.npy")
        self.ids_path = ids_path or os.path.join(DATA_DIR, "poi_embedding_ids.json")
        self.desc_path = desc_path or os.path.join(DATA_DIR, "poi_descriptions.json")
        
        self.embeddings = None
        self.poi_ids = []
        self.id_to_idx = {}
        self.descriptions = {}
        self._loaded = False
    
    def load(self):
        """加载 embedding 和索引"""
        if self._loaded:
            return
        
        if not os.path.exists(self.emb_path):
            raise FileNotFoundError(f"Embedding file not found: {self.emb_path}")
        if not os.path.exists(self.ids_path):
            raise FileNotFoundError(f"IDs file not found: {self.ids_path}")
        
        print("[SemanticIndex] Loading embeddings...")
        self.embeddings = np.load(self.emb_path)
        with open(self.ids_path, "r", encoding="utf-8") as f:
            self.poi_ids = json.load(f)
        
        self.id_to_idx = {pid: i for i, pid in enumerate(self.poi_ids)}
        
        # 归一化 embedding（余弦相似度）
        self.norms = np.linalg.norm(self.embeddings, axis=1, keepdims=True)
        self.norms[self.norms == 0] = 1  # 避免除零
        self.embeddings_normed = self.embeddings / self.norms
        
        # 加载描述（可选）
        if os.path.exists(self.desc_path):
            with open(self.desc_path, "r", encoding="utf-8") as f:
                self.descriptions = json.load(f)
        
        self._loaded = True
        print(f"[SemanticIndex] Loaded {len(self.poi_ids)} POIs, dim={self.embeddings.shape[1]}")
    
    def _get_query_embedding(self, query):
        """调用 GLM API 获取查询文本的 embedding"""
        if not GLM_API_KEY:
            raise RuntimeError("GLM_API_KEY not configured.")
        req = urllib.request.Request(
            EMBEDDING_URL,
            data=json.dumps({"model": "embedding-2", "input": query}).encode(),
            headers={
                "Authorization": f"Bearer {GLM_API_KEY}",
                "Content-Type": "application/json"
            }
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        emb = np.array(data["data"][0]["embedding"], dtype=np.float32)
        # 归一化
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb
    
    def search(self, query, top_k=20, filter_ids=None):
        """
        语义搜索：返回最相关的 POI ID 列表
        
        Args:
            query: 查询文本（如"想吃点辣的"）
            top_k: 返回数量
            filter_ids: 可选，只在这些 POI ID 中搜索
        
        Returns:
            [(poi_id, similarity, description), ...]
        """
        q_emb = self._get_query_embedding(query)
        if not self._loaded:
            self.load()
        
        # 计算余弦相似度
        sims = self.embeddings_normed @ q_emb
        
        # 如果有 filter_ids，只考虑这些
        if filter_ids is not None:
            filter_set = set(filter_ids)
            mask = np.array([pid in filter_set for pid in self.poi_ids])
            sims = sims * mask - 999 * (~mask)
        
        # 取 top-k
        top_indices = np.argsort(sims)[-top_k:][::-1]
        results = []
        for idx in top_indices:
            pid = self.poi_ids[idx]
            desc = self.descriptions.get(pid, "")
            results.append((pid, float(sims[idx]), desc))
        
        return results
    
    def rerank_candidates(self, query, candidates, top_k=None):
        """
        对已有候选 POI 进行语义重排序
        
        Args:
            query: 查询文本
            candidates: [(poi_id, score), ...] 或 [poi_id, ...]
            top_k: 返回数量，None 表示全部
        
        Returns:
            [(poi_id, semantic_score), ...]
        """
        q_emb = self._get_query_embedding(query)
        if not self._loaded:
            self.load()
        
        # 提取 POI IDs
        if candidates and isinstance(candidates[0], tuple):
            candidate_ids = [c[0] for c in candidates]
        else:
            candidate_ids = list(candidates)
        
        # 获取候选索引
        indices = [self.id_to_idx[pid] for pid in candidate_ids if pid in self.id_to_idx]
        if not indices:
            return []
        
        cand_embs = self.embeddings_normed[indices]
        sims = cand_embs @ q_emb
        
        sorted_pairs = sorted(zip(candidate_ids, sims), key=lambda x: -x[1])
        if top_k:
            sorted_pairs = sorted_pairs[:top_k]
        
        return [(pid, float(score)) for pid, score in sorted_pairs]


# 全局单例
_semantic_index = None

def get_semantic_index():
    global _semantic_index
    if _semantic_index is None:
        _semantic_index = SemanticIndex()
        _semantic_index.load()
    return _semantic_index
