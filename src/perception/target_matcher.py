"""三级目标匹配器模块。

将用户的自然语言描述与屏幕 UI 元素进行多级匹配：
1. 精确匹配：文本完全相等（忽略大小写/空格）
2. 模糊匹配：基于编辑距离/子串包含
3. 语义匹配：基于语义相似度（关键词匹配 + 同义词扩展）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.perception.target_cache import TargetCache, TargetInfo


class MatchLevel(Enum):
    """三级匹配等级。"""

    EXACT = "exact"  # 精确匹配：文本完全一致
    FUZZY = "fuzzy"  # 模糊匹配：文本相似度 > 阈值
    SEMANTIC = "semantic"  # 语义匹配：基于语义相似度


@dataclass
class MatchResult:
    """匹配结果。"""

    target: TargetInfo  # 匹配到的目标
    level: MatchLevel  # 匹配等级
    score: float  # 匹配分数 0.0-1.0
    confidence: float  # 置信度 0.0-1.0


class TargetMatcher:
    """三级目标匹配器。

    将用户的自然语言描述与屏幕 UI 元素进行多级匹配：
    1. 精确匹配：文本完全相等（忽略大小写/空格）
    2. 模糊匹配：基于编辑距离/子串包含
    3. 语义匹配：基于语义相似度（关键词匹配 + 同义词扩展）
    """

    def __init__(
        self,
        cache: TargetCache,
        fuzzy_threshold: float = 0.6,
        semantic_threshold: float = 0.4,
    ) -> None:
        self._cache = cache
        self._fuzzy_threshold = fuzzy_threshold
        self._semantic_threshold = semantic_threshold

    # ── 主匹配入口 ────────────────────────────────────

    def match(
        self,
        query: str,
        target_type: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Optional[MatchResult]:
        """对 query 进行三级匹配，返回最佳匹配结果。

        按 exact -> fuzzy -> semantic 顺序尝试，找到即返回。
        """
        result = self.exact_match(query, target_type, region)
        if result is not None:
            return result

        result = self.fuzzy_match(query, target_type, region)
        if result is not None:
            return result

        result = self.semantic_match(query, target_type, region)
        return result

    def match_all(
        self,
        query: str,
        target_type: Optional[str] = None,
        region: Optional[str] = None,
    ) -> list[MatchResult]:
        """返回所有匹配结果（按 score 降序），不过滤低分结果。"""
        results: list[MatchResult] = []
        seen_ids: set[str] = set()

        targets = self._get_targets(target_type, region)

        # 精确匹配
        query_norm = query.strip().lower()
        for t in targets:
            if t.target_id in seen_ids:
                continue
            if t.text.strip().lower() == query_norm:
                score = 1.0
                results.append(
                    MatchResult(
                        target=t,
                        level=MatchLevel.EXACT,
                        score=score,
                        confidence=self._compute_confidence(MatchLevel.EXACT, score),
                    )
                )
                seen_ids.add(t.target_id)

        # 模糊匹配
        for t in targets:
            if t.target_id in seen_ids:
                continue
            ratio = self._levenshtein_ratio(query_norm, t.text.strip().lower())
            if ratio >= self._fuzzy_threshold:
                results.append(
                    MatchResult(
                        target=t,
                        level=MatchLevel.FUZZY,
                        score=ratio,
                        confidence=self._compute_confidence(MatchLevel.FUZZY, ratio),
                    )
                )
                seen_ids.add(t.target_id)

        # 语义匹配
        for t in targets:
            if t.target_id in seen_ids:
                continue
            sem_score = self._semantic_score(query_norm, t.text.strip().lower())
            if sem_score >= self._semantic_threshold:
                results.append(
                    MatchResult(
                        target=t,
                        level=MatchLevel.SEMANTIC,
                        score=sem_score,
                        confidence=self._compute_confidence(MatchLevel.SEMANTIC, sem_score),
                    )
                )
                seen_ids.add(t.target_id)

        # 按 score 降序排列
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ── 精确匹配 ──────────────────────────────────────

    def exact_match(
        self,
        query: str,
        target_type: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Optional[MatchResult]:
        """精确匹配：query 与 target.text 完全相等（忽略大小写和首尾空格）。"""
        targets = self._get_targets(target_type, region)
        query_norm = query.strip().lower()

        for t in targets:
            if t.text.strip().lower() == query_norm:
                score = 1.0
                return MatchResult(
                    target=t,
                    level=MatchLevel.EXACT,
                    score=score,
                    confidence=self._compute_confidence(MatchLevel.EXACT, score),
                )
        return None

    # ── 模糊匹配 ──────────────────────────────────────

    def fuzzy_match(
        self,
        query: str,
        target_type: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Optional[MatchResult]:
        """模糊匹配：使用编辑距离计算相似度，取最高分且超过阈值的。"""
        targets = self._get_targets(target_type, region)
        query_norm = query.strip().lower()

        best: Optional[MatchResult] = None
        best_score = 0.0

        for t in targets:
            ratio = self._levenshtein_ratio(query_norm, t.text.strip().lower())
            if ratio >= self._fuzzy_threshold and ratio > best_score:
                best_score = ratio
                best = MatchResult(
                    target=t,
                    level=MatchLevel.FUZZY,
                    score=ratio,
                    confidence=self._compute_confidence(MatchLevel.FUZZY, ratio),
                )
        return best

    @staticmethod
    def _levenshtein_ratio(s1: str, s2: str) -> float:
        """计算两个字符串的 Levenshtein 相似度比率 (0.0-1.0)。

        基于 Levenshtein 编辑距离：
        ratio = 1 - (edit_distance / max(len(s1), len(s2)))
        """
        if not s1 and not s2:
            return 1.0
        max_len = max(len(s1), len(s2))
        if max_len == 0:
            return 1.0

        # 计算 Levenshtein 编辑距离
        dist = TargetMatcher._levenshtein_distance(s1, s2)
        return 1.0 - (dist / max_len)

    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int:
        """计算 Levenshtein 编辑距离。"""
        m, n = len(s1), len(s2)
        # 使用一维数组优化空间
        prev = list(range(n + 1))
        curr = [0] * (n + 1)

        for i in range(1, m + 1):
            curr[0] = i
            for j in range(1, n + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                curr[j] = min(
                    prev[j] + 1,  # 删除
                    curr[j - 1] + 1,  # 插入
                    prev[j - 1] + cost,  # 替换
                )
            prev, curr = curr, prev

        return prev[n]

    # ── 语义匹配 ──────────────────────────────────────

    def semantic_match(
        self,
        query: str,
        target_type: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Optional[MatchResult]:
        """语义匹配：基于关键词提取 + 子串包含 + 常见同义词表。

        不依赖外部 NLP 模型，使用规则方法实现。
        """
        targets = self._get_targets(target_type, region)
        query_norm = query.strip().lower()

        best: Optional[MatchResult] = None
        best_score = 0.0

        for t in targets:
            score = self._semantic_score(query_norm, t.text.strip().lower())
            if score >= self._semantic_threshold and score > best_score:
                best_score = score
                best = MatchResult(
                    target=t,
                    level=MatchLevel.SEMANTIC,
                    score=score,
                    confidence=self._compute_confidence(MatchLevel.SEMANTIC, score),
                )
        return best

    def _semantic_score(self, query: str, target_text: str) -> float:
        """计算语义匹配分数。

        综合考虑：
        1. 子串包含关系
        2. 关键词重叠
        3. 同义词匹配
        """
        if not query or not target_text:
            return 0.0

        score = 0.0

        # 1. 子串包含：query 是 target 的子串，或反过来
        if query in target_text:
            overlap_ratio = len(query) / len(target_text)
            score = max(score, 0.4 + 0.6 * overlap_ratio)
        if target_text in query:
            overlap_ratio = len(target_text) / len(query)
            score = max(score, 0.4 + 0.6 * overlap_ratio)

        # 2. 关键词重叠
        query_chars = set(query)
        target_chars = set(target_text)
        if query_chars and target_chars:
            char_overlap = len(query_chars & target_chars) / len(
                query_chars | target_chars
            )
            score = max(score, char_overlap * 0.7)

        # 3. 同义词匹配
        syn_score = self._synonym_match_score(query, target_text)
        score = max(score, syn_score)

        return min(score, 1.0)

    def _synonym_match_score(self, query: str, target_text: str) -> float:
        """基于同义词表计算匹配分数。"""
        # 提取 query 中的每个词，检查是否与 target_text 有同义词关系
        # 对中文按字符粒度拆分（2-gram），对英文按空格拆分
        query_words = self._extract_words(query)
        target_words = self._extract_words(target_text)

        if not query_words or not target_words:
            return 0.0

        match_count = 0
        total = len(query_words)

        for qw in query_words:
            # 直接包含
            if any(qw in tw or tw in qw for tw in target_words):
                match_count += 1
                continue
            # 同义词匹配
            synonyms = self._get_synonyms(qw)
            for syn in synonyms:
                if any(syn in tw or tw in syn for tw in target_words):
                    match_count += 1
                    break

        return match_count / total if total > 0 else 0.0

    @staticmethod
    def _extract_words(text: str) -> list[str]:
        """从文本中提取词语。

        简单策略：按空格拆分 + 2-gram（中文）。
        """
        words: list[str] = []
        # 按空格拆分
        parts = text.split()
        words.extend(parts)

        # 对中文做 2-gram（如果连续中文字符超过 2 个）
        i = 0
        chinese_buffer = ""
        while i <= len(text):
            if i < len(text) and "\u4e00" <= text[i] <= "\u9fff":
                chinese_buffer += text[i]
            else:
                if len(chinese_buffer) >= 2:
                    # 生成 2-gram
                    for j in range(len(chinese_buffer) - 1):
                        words.append(chinese_buffer[j : j + 2])
                chinese_buffer = ""
            i += 1

        return list(set(words)) if words else []

    # ── 同义词 ─────────────────────────────────────────

    @staticmethod
    def _get_synonyms(word: str) -> set[str]:
        """获取常见 UI 操作同义词。

        内置一组常见 UI 动作词和名词的同义词映射。
        """
        # 同义词组：每组内的词互为同义词
        synonym_groups: list[list[str]] = [
            # 动作：点击
            ["点击", "单击", "按下", "点", "按", "click"],
            # 动作：关闭
            ["关闭", "关掉", "退出", "关", "close"],
            # 动作：打开
            ["打开", "开启", "open"],
            # 动作：删除
            ["删除", "移除", "去掉", "delete", "remove"],
            # 动作：搜索
            ["搜索", "查找", "查询", "search"],
            # 动作：确认
            ["确认", "确定", "ok", "ok"],
            # 动作：取消
            ["取消", "放弃", "cancel"],
            # 动作：保存
            ["保存", "save"],
            # 动作：编辑
            ["编辑", "修改", "edit"],
            # 动作：发送
            ["发送", "send", "发"],
            # 动作：复制
            ["复制", "copy"],
            # 动作：粘贴
            ["粘贴", "paste"],
            # 名词：按钮
            ["按钮", "按键", "button", "btn"],
            # 名词：菜单
            ["菜单", "menu"],
            # 名词：链接
            ["链接", "超链接", "link"],
            # 名词：输入框
            ["输入框", "文本框", "input", "textbox"],
            # 名词：窗口
            ["窗口", "window", "弹窗"],
            # 名词：设置
            ["设置", "setting", "配置"],
            # 名词：图标
            ["图标", "icon"],
        ]

        result: set[str] = set()
        for group in synonym_groups:
            if word in group:
                result.update(group)
        # 移除自身
        result.discard(word)
        return result

    # ── 分数计算 ──────────────────────────────────────

    @staticmethod
    def _compute_confidence(level: MatchLevel, score: float) -> float:
        """根据匹配等级和分数计算置信度。

        - EXACT: confidence = score (通常 1.0)
        - FUZZY: confidence = score * 0.8
        - SEMANTIC: confidence = score * 0.6
        """
        multipliers = {
            MatchLevel.EXACT: 1.0,
            MatchLevel.FUZZY: 0.8,
            MatchLevel.SEMANTIC: 0.6,
        }
        return score * multipliers.get(level, 1.0)

    # ── 内部工具 ──────────────────────────────────────

    def _get_targets(
        self,
        target_type: Optional[str] = None,
        region: Optional[str] = None,
    ) -> list[TargetInfo]:
        """根据过滤条件获取目标列表。"""
        if target_type is not None:
            targets = self._cache.find_by_type(target_type)
        elif region is not None:
            targets = self._cache.find_by_region(region)
        else:
            # 返回所有目标
            targets = list(self._cache._targets.values())

        # 如果同时指定了 type 和 region，再做一次过滤
        if target_type is not None and region is not None:
            targets = [t for t in targets if t.screen_region == region]

        return targets
