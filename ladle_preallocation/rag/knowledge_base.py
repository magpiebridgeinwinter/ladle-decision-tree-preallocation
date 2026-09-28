"""Lightweight RAG knowledge base for scheduler domain knowledge.

Uses local sentence embeddings + cosine similarity for retrieval.
Designed to ingest enterprise scheduling experience documents and
domain rule specifications once obtained.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KnowledgeChunk:
    """A piece of knowledge with its embedding."""

    id: str
    text: str
    source: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SimpleEmbedder:
    """Simple TF-IDF based embedder (no external dependency needed)."""

    def __init__(self):
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}

    def fit(self, documents: list[str]) -> None:
        """Build vocabulary and IDF from documents."""
        from collections import Counter

        doc_count = len(documents)
        df: Counter[str] = Counter()
        all_terms = set()

        for doc in documents:
            terms = set(self._tokenize(doc))
            df.update(terms)
            all_terms.update(terms)

        self._vocab = {term: i for i, term in enumerate(sorted(all_terms))}
        self._idf = {
            term: math.log((doc_count + 1) / (df[term] + 1)) + 1
            for term in all_terms
        }

    def _tokenize(self, text: str) -> list[str]:
        """Simple Chinese text tokenizer (character bigrams + words)."""
        import re
        # Remove punctuation, keep Chinese chars and alphanumeric
        cleaned = re.sub(r"[^\u4e00-\u9fff\w]", " ", text.lower())
        tokens = []
        # Add individual words
        tokens.extend(cleaned.split())
        # Add character bigrams for Chinese text
        chinese = re.findall(r"[\u4e00-\u9fff]+", text)
        for segment in chinese:
            for i in range(len(segment) - 1):
                tokens.append(segment[i : i + 2])
        return tokens

    def encode(self, text: str) -> list[float]:
        """Encode text into a sparse TF-IDF vector."""
        tokens = self._tokenize(text)
        if not self._vocab:
            return [0.0]
        vec = [0.0] * len(self._vocab)
        for token in tokens:
            if token in self._vocab:
                idx = self._vocab[token]
                vec[idx] += self._idf.get(token, 1.0)
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class KnowledgeBase:
    """Retrieval-augmented knowledge base for scheduler domain knowledge.

    Usage:
        kb = KnowledgeBase()
        kb.add_chunk("规则1: 行车不能同时吊运两个钢包", source="操作规程")
        kb.add_chunk("规则2: 钢包浇注后需冷却30分钟", source="工艺手册")
        results = kb.search("行车吊运约束", top_k=3)
    """

    def __init__(self, embedder: SimpleEmbedder | None = None):
        self._chunks: list[KnowledgeChunk] = []
        self._embedder = embedder or SimpleEmbedder()

    def add_chunk(
        self,
        text: str,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a knowledge chunk to the base.

        Returns the chunk ID.
        """
        chunk_id = f"kb_{len(self._chunks):04d}"
        chunk = KnowledgeChunk(
            id=chunk_id,
            text=text,
            source=source,
            metadata=metadata or {},
        )
        self._chunks.append(chunk)
        # Re-fit embedder with all texts
        self._embedder.fit([c.text for c in self._chunks])
        # Re-encode all chunks
        for c in self._chunks:
            c.embedding = self._embedder.encode(c.text)
        return chunk_id

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Search for relevant knowledge chunks.

        Args:
            query: Natural language query.
            top_k: Number of top results to return.
            min_similarity: Minimum cosine similarity threshold.

        Returns:
            List of dicts with keys: id, text, source, similarity, metadata.
        """
        if not self._chunks:
            return []

        query_vec = self._embedder.encode(query)

        scored = []
        for chunk in self._chunks:
            if chunk.embedding is None:
                continue
            sim = _cosine_similarity(query_vec, chunk.embedding)
            if sim >= min_similarity:
                scored.append((sim, chunk))

        scored.sort(key=lambda x: -x[0])

        return [
            {
                "id": chunk.id,
                "text": chunk.text,
                "source": chunk.source,
                "similarity": round(sim, 4),
                "metadata": chunk.metadata,
            }
            for sim, chunk in scored[:top_k]
        ]

    def build_context_for_llm(
        self,
        query: str,
        top_k: int = 5,
    ) -> str:
        """Build a context string for LLM prompting.

        Args:
            query: The natural language query.
            top_k: Number of relevant chunks to retrieve.

        Returns:
            A formatted string with relevant knowledge for inclusion in prompts.
        """
        results = self.search(query, top_k=top_k)
        if not results:
            return ""

        lines = ["## 相关知识库条目（仅供参考）\n"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"{i}. [{r['source']}] {r['text']} "
                f"(相似度: {r['similarity']:.2f})"
            )
        return "\n".join(lines)

    @property
    def size(self) -> int:
        return len(self._chunks)

    def seed_default_rules(self) -> None:
        """Seed with default steelmaking scheduling rules."""
        defaults = [
            (
                "行车安全规程：同一跨内的两台行车之间必须保持至少10米的安全距离，"
                "以避免吊运过程中的碰撞风险。",
                "安全规程",
            ),
            (
                "钢包等级匹配原则：炉次的钢种等级要求应优先匹配相同或更高等级的钢包。"
                "等级以字母数字表示，字母越接近越理想，等级不足时可按就低匹配但需记录。",
                "工艺规范",
            ),
            (
                "行车负载限制：每台行车有最大载重限制，行车当前吊运负载加上钢包空包重量"
                "不得超过该限制。如超载需排到后续或切换行车。",
                "操作规程",
            ),
            (
                "钢包运行区间约束：钢包放置位置必须在行车可运行的物理区间内，"
                "超出区间的钢包该行车无法吊运。",
                "操作规程",
            ),
            (
                "时间窗约束：行车到达钢包位置并完成吊运的时间必须早于或等于window_end。"
                "到达时间 = 炉次开始时间 + 行车移动时间。",
                "调度规范",
            ),
            (
                "扰动响应优先级：预配包仍由决策树完成；扰动进入LLM Workflow。"
                "剩余预算不足时不阻塞生产，直接Frozen+呼叫人工；预算充足时由LLM提出方案，"
                "通过统一硬约束校验后才可执行，失败则Frozen+告警。",
                "调度规范",
            ),
            (
                "钢包状态检查：离线(offline)、不可用(unavailable)、维修(maintenance)、"
                "报废(scrapped)的钢包不可分配。",
                "操作规程",
            ),
            (
                "钢包大修禁忌：进行大修(major)或全面检修(full)的钢包禁止分配。",
                "操作规程",
            ),
        ]
        for text, source in defaults:
            self.add_chunk(text, source=source)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
