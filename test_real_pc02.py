"""T-PC-02 实操测试：目标缓存存取。

验证 TargetCache 的核心功能：
1. 添加/批量添加目标
2. 按 ID / 文字 / 类型 / 区域 / bbox 查询
3. find_nearest 最近目标查找
4. TTL 过期淘汰
5. 容量限制淘汰
6. 统计信息
"""

import importlib
import importlib.util
import sys
import time
import traceback
import types

# 直接加载 target_cache 模块，跳过 perception/__init__.py 的重量级导入
# 将模块注册为顶层模块而非 perception 子模块
_spec = importlib.util.spec_from_file_location(
    "target_cache",
    "src/perception/target_cache.py",
)
_mod = types.ModuleType("target_cache")
_mod.__spec__ = _spec
_mod.__file__ = _spec.origin
sys.modules["target_cache"] = _mod
_spec.loader.exec_module(_mod)

TargetCache = _mod.TargetCache
TargetInfo = _mod.TargetInfo
determine_screen_region = _mod.determine_screen_region


def make_target(
    text: str,
    bbox: tuple[int, int, int, int],
    element_type: str,
    confidence: float,
    target_id: str | None = None,
    created_at: float | None = None,
) -> TargetInfo:
    """构造 TargetInfo 辅助函数。"""
    x, y, w, h = bbox
    center = (x + w // 2, y + h // 2)
    region = determine_screen_region(center)
    return TargetInfo(
        target_id=target_id or f"t-{text}-{int(time.time()*1000)}",
        text=text,
        bbox=bbox,
        center=center,
        element_type=element_type,
        confidence=confidence,
        screen_region=region,
        created_at=created_at or time.time(),
    )


class TestResult:
    """简单测试结果收集器。"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: list[str] = []

    def check(self, name: str, condition: bool, detail: str = ""):
        status = "PASS" if condition else "FAIL"
        msg = f"  [{status}] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        if condition:
            self.passed += 1
        else:
            self.failed += 1
            self.errors.append(name)

    def summary(self) -> bool:
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"测试结果: {self.passed}/{total} PASSED, {self.failed} FAILED")
        if self.errors:
            print(f"失败项: {', '.join(self.errors)}")
        print(f"{'='*60}")
        return self.failed == 0


def test_basic_add_get(tr: TestResult):
    """测试1：基本添加和按 ID 获取。"""
    print("\n--- 测试1：基本添加和按 ID 获取 ---")
    cache = TargetCache()

    t1 = make_target("打开文件", (100, 200, 120, 40), "button", 0.95)
    cache.add(t1)

    tr.check("缓存大小为1", cache.size == 1, f"size={cache.size}")
    
    found = cache.get_by_id(t1.target_id)
    tr.check("按ID找到目标", found is not None)
    if found:
        tr.check("text一致", found.text == "打开文件", f"text={found.text}")
        tr.check("bbox一致", found.bbox == (100, 200, 120, 40), f"bbox={found.bbox}")
        tr.check("center一致", found.center == (160, 220), f"center={found.center}")
        tr.check("element_type一致", found.element_type == "button")
        tr.check("confidence一致", found.confidence == 0.95)
        tr.check("screen_region非空", found.screen_region != "")
    
    not_found = cache.get_by_id("nonexistent-id")
    tr.check("不存在的ID返回None", not_found is None)


def test_batch_add(tr: TestResult):
    """测试2：批量添加。"""
    print("\n--- 测试2：批量添加 ---")
    cache = TargetCache()

    targets = [
        make_target("文件", (10, 10, 80, 30), "menu_item", 0.9),
        make_target("编辑", (100, 10, 80, 30), "menu_item", 0.88),
        make_target("帮助", (300, 10, 80, 30), "menu_item", 0.85),
        make_target("确定", (500, 500, 100, 40), "button", 0.92),
        make_target("取消", (620, 500, 100, 40), "button", 0.91),
    ]
    cache.add_batch(targets)

    tr.check("批量添加后大小为5", cache.size == 5, f"size={cache.size}")


def test_find_by_text(tr: TestResult):
    """测试3：按文字查找。"""
    print("\n--- 测试3：按文字查找 ---")
    cache = TargetCache()

    t1 = make_target("保存文件", (100, 100, 100, 30), "button", 0.9)
    t2 = make_target("另存为文件", (100, 150, 120, 30), "button", 0.88)
    t3 = make_target("关闭窗口", (100, 200, 100, 30), "button", 0.85)
    cache.add_batch([t1, t2, t3])

    # 包含匹配
    results = cache.find_by_text("文件")
    tr.check("包含匹配'文件'找到2个", len(results) == 2, f"找到{len(results)}个")

    # 精确匹配
    exact = cache.find_by_text("保存文件", exact=True)
    tr.check("精确匹配找到1个", len(exact) == 1, f"找到{len(exact)}个")
    if exact:
        tr.check("精确匹配内容正确", exact[0].text == "保存文件")

    # 无匹配
    no_match = cache.find_by_text("不存在的内容")
    tr.check("无匹配返回空列表", len(no_match) == 0)


def test_find_by_type(tr: TestResult):
    """测试4：按类型查找。"""
    print("\n--- 测试4：按类型查找 ---")
    cache = TargetCache()

    targets = [
        make_target("按钮1", (100, 100, 80, 30), "button", 0.9),
        make_target("按钮2", (200, 100, 80, 30), "button", 0.88),
        make_target("标签1", (100, 200, 80, 30), "label", 0.85),
        make_target("链接1", (100, 300, 80, 30), "link", 0.92),
        make_target("图标1", (100, 400, 40, 40), "icon", 0.8),
    ]
    cache.add_batch(targets)

    buttons = cache.find_by_type("button")
    tr.check("button类型找到2个", len(buttons) == 2, f"找到{len(buttons)}个")

    labels = cache.find_by_type("label")
    tr.check("label类型找到1个", len(labels) == 1)

    no_type = cache.find_by_type("nonexistent")
    tr.check("不存在类型返回空", len(no_type) == 0)


def test_find_by_region(tr: TestResult):
    """测试5：按屏幕区域查找。"""
    print("\n--- 测试5：按屏幕区域查找 ---")
    cache = TargetCache()

    # 左上角 (100, 50) -> top_left
    t1 = make_target("左上", (50, 25, 100, 50), "button", 0.9)
    # 右下角 (1500, 800) -> bottom_right
    t2 = make_target("右下", (1450, 775, 100, 50), "button", 0.88)
    # 中心 (960, 540) -> center
    t3 = make_target("中心", (910, 515, 100, 50), "button", 0.85)

    cache.add_batch([t1, t2, t3])

    tr.check("左上目标region=top_left", t1.screen_region == "top_left", f"region={t1.screen_region}")
    tr.check("右下目标region=bottom_right", t2.screen_region == "bottom_right", f"region={t2.screen_region}")
    tr.check("中心目标region=center", t3.screen_region == "center", f"region={t3.screen_region}")

    tl = cache.find_by_region("top_left")
    tr.check("top_left区域找到1个", len(tl) == 1, f"找到{len(tl)}个")

    center = cache.find_by_region("center")
    tr.check("center区域找到1个", len(center) == 1)


def test_find_by_bbox(tr: TestResult):
    """测试6：按位置区域查找。"""
    print("\n--- 测试6：按位置区域查找 ---")
    cache = TargetCache()

    t1 = make_target("目标A", (100, 100, 80, 40), "button", 0.9)
    t2 = make_target("目标B", (500, 500, 80, 40), "button", 0.88)
    cache.add_batch([t1, t2])

    # 查询目标A附近 (center = 140, 120)
    near_a = cache.find_by_bbox((95, 95, 90, 50), tolerance=20)
    tr.check("bbox查询找到附近目标", len(near_a) >= 1, f"找到{len(near_a)}个")

    # 查询远处
    far = cache.find_by_bbox((900, 900, 80, 40), tolerance=5)
    tr.check("远处bbox查询无结果", len(far) == 0)


def test_find_nearest(tr: TestResult):
    """测试7：最近目标查找。"""
    print("\n--- 测试7：最近目标查找 ---")
    cache = TargetCache()

    t1 = make_target("近处", (100, 100, 80, 40), "button", 0.9)  # center=(140, 120)
    t2 = make_target("远处", (800, 600, 80, 40), "label", 0.88)  # center=(840, 620)
    cache.add_batch([t1, t2])

    nearest = cache.find_nearest(150, 130)
    tr.check("最近目标是'近处'", nearest is not None and nearest.text == "近处",
             f"nearest={nearest.text if nearest else None}")

    nearest_with_type = cache.find_nearest(850, 630, element_type="label")
    tr.check("按类型找最近label", nearest_with_type is not None and nearest_with_type.text == "远处",
             f"nearest={nearest_with_type.text if nearest_with_type else None}")

    no_match = cache.find_nearest(150, 130, element_type="icon")
    tr.check("不存在的类型返回None", no_match is None)


def test_ttl_expiry(tr: TestResult):
    """测试8：TTL 过期淘汰。"""
    print("\n--- 测试8：TTL 过期淘汰 ---")
    cache = TargetCache(ttl_seconds=0.5)  # 0.5秒过期

    # 添加一个"旧"目标（created_at 设为1秒前）
    old_target = make_target("旧目标", (100, 100, 80, 40), "button", 0.9, created_at=time.time() - 1.0)
    cache.add(old_target)

    # 添加一个"新"目标
    new_target = make_target("新目标", (200, 200, 80, 40), "button", 0.88)
    cache.add(new_target)

    tr.check("添加后大小为2", cache.size == 2, f"size={cache.size}")

    # 移除过期
    removed = cache.remove_expired()
    tr.check("过期移除1个", removed == 1, f"removed={removed}")
    tr.check("移除后大小为1", cache.size == 1, f"size={cache.size}")
    
    remaining = cache.get_by_id(new_target.target_id)
    tr.check("新目标仍在", remaining is not None)
    
    expired = cache.get_by_id(old_target.target_id)
    tr.check("旧目标已移除", expired is None)


def test_ttl_realtime_wait(tr: TestResult):
    """测试9：实时等待 TTL 过期。"""
    print("\n--- 测试9：实时等待 TTL 过期 ---")
    cache = TargetCache(ttl_seconds=0.3)  # 0.3秒过期

    t = make_target("等过期", (300, 300, 80, 40), "button", 0.9)
    cache.add(t)
    tr.check("添加后大小为1", cache.size == 1)

    # 等待过期
    time.sleep(0.4)
    removed = cache.remove_expired()
    tr.check("等待0.4s后过期移除1个", removed == 1, f"removed={removed}")
    tr.check("移除后大小为0", cache.size == 0)


def test_capacity_eviction(tr: TestResult):
    """测试10：容量限制淘汰。"""
    print("\n--- 测试10：容量限制淘汰 ---")
    cache = TargetCache(max_size=3)

    t1 = make_target("目标1", (100, 100, 80, 40), "button", 0.9)
    t2 = make_target("目标2", (200, 200, 80, 40), "button", 0.88)
    t3 = make_target("目标3", (300, 300, 80, 40), "button", 0.85)
    
    cache.add_batch([t1, t2, t3])
    tr.check("添加3个目标大小为3", cache.size == 3, f"size={cache.size}")

    # 添加第4个，应淘汰最旧的（t1）
    t4 = make_target("目标4", (400, 400, 80, 40), "button", 0.82)
    cache.add(t4)
    tr.check("超容量后大小仍为3", cache.size == 3, f"size={cache.size}")

    oldest = cache.get_by_id(t1.target_id)
    tr.check("最旧目标被淘汰", oldest is None, "t1应该被淘汰")

    newest = cache.get_by_id(t4.target_id)
    tr.check("最新目标存在", newest is not None)
    if newest:
        tr.check("最新目标text正确", newest.text == "目标4")


def test_capacity_eviction_order(tr: TestResult):
    """测试11：容量淘汰顺序验证。"""
    print("\n--- 测试11：容量淘汰顺序验证 ---")
    cache = TargetCache(max_size=5)

    # 添加5个目标
    targets = [make_target(f"T{i}", (i * 100, 100, 80, 40), "button", 0.9 - i * 0.01) for i in range(5)]
    cache.add_batch(targets)
    tr.check("5个目标大小为5", cache.size == 5)

    # 再添加2个，应淘汰前2个
    cache.add(make_target("T5", (600, 100, 80, 40), "button", 0.85))
    cache.add(make_target("T6", (700, 100, 80, 40), "button", 0.84))

    tr.check("淘汰后大小仍为5", cache.size == 5)
    
    # T0 和 T1 应被淘汰
    tr.check("T0被淘汰", cache.get_by_id(targets[0].target_id) is None)
    tr.check("T1被淘汰", cache.get_by_id(targets[1].target_id) is None)
    # T2, T3, T4 仍在
    tr.check("T2仍在", cache.get_by_id(targets[2].target_id) is not None)
    tr.check("T5存在", cache.find_by_text("T5"))
    tr.check("T6存在", cache.find_by_text("T6"))


def test_update_existing(tr: TestResult):
    """测试12：更新已有目标。"""
    print("\n--- 测试12：更新已有目标 ---")
    cache = TargetCache()

    t1 = make_target("原始", (100, 100, 80, 40), "button", 0.9, target_id="fixed-id")
    cache.add(t1)
    tr.check("添加后大小为1", cache.size == 1)

    # 用相同ID更新
    t1_updated = make_target("更新后", (200, 200, 100, 50), "label", 0.95, target_id="fixed-id")
    cache.add(t1_updated)
    tr.check("更新后大小仍为1", cache.size == 1, f"size={cache.size}")

    found = cache.get_by_id("fixed-id")
    tr.check("更新后text变化", found is not None and found.text == "更新后")
    if found:
        tr.check("更新后bbox变化", found.bbox == (200, 200, 100, 50))
        tr.check("更新后type变化", found.element_type == "label")
        tr.check("更新后confidence变化", found.confidence == 0.95)


def test_clear(tr: TestResult):
    """测试13：清空缓存。"""
    print("\n--- 测试13：清空缓存 ---")
    cache = TargetCache()

    targets = [make_target(f"T{i}", (i * 100, 100, 80, 40), "button", 0.9) for i in range(5)]
    cache.add_batch(targets)
    tr.check("添加5个目标", cache.size == 5)

    cache.clear()
    tr.check("清空后大小为0", cache.size == 0)

    stats = cache.get_statistics()
    tr.check("清空后total=0", stats["total"] == 0)
    tr.check("清空后hits=0", stats["hits"] == 0)


def test_statistics(tr: TestResult):
    """测试14：统计信息。"""
    print("\n--- 测试14：统计信息 ---")
    cache = TargetCache()

    targets = [
        make_target("按钮1", (100, 100, 80, 40), "button", 0.9),
        make_target("按钮2", (200, 100, 80, 40), "button", 0.88),
        make_target("标签1", (300, 100, 80, 40), "label", 0.85),
        make_target("链接1", (800, 100, 80, 40), "link", 0.92),
    ]
    cache.add_batch(targets)

    # 制造一些查询
    cache.get_by_id(targets[0].target_id)  # hit
    cache.get_by_id(targets[1].target_id)  # hit
    cache.get_by_id("nonexistent")  # miss

    stats = cache.get_statistics()
    tr.check("统计total=4", stats["total"] == 4, f"total={stats['total']}")
    tr.check("统计button数量=2", stats["type_counts"].get("button") == 2)
    tr.check("统计hits=2", stats["hits"] == 2, f"hits={stats['hits']}")
    tr.check("统计misses=1", stats["misses"] == 1, f"misses={stats['misses']}")
    tr.check("命中率约0.667", abs(stats["hit_rate"] - 2 / 3) < 0.01, f"hit_rate={stats['hit_rate']}")


def test_determine_screen_region(tr: TestResult):
    """测试15：屏幕区域判定。"""
    print("\n--- 测试15：屏幕区域判定 ---")
    
    r1 = determine_screen_region((100, 100))  # 左上
    tr.check("(100,100)->top_left", r1 == "top_left", f"region={r1}")

    r2 = determine_screen_region((1800, 100))  # 右上
    tr.check("(1800,100)->top_right", r2 == "top_right", f"region={r2}")

    r3 = determine_screen_region((100, 900))  # 左下
    tr.check("(100,900)->bottom_left", r3 == "bottom_left", f"region={r3}")

    r4 = determine_screen_region((1800, 900))  # 右下
    tr.check("(1800,900)->bottom_right", r4 == "bottom_right", f"region={r4}")

    r5 = determine_screen_region((960, 540))  # 中心
    tr.check("(960,540)->center", r5 == "center", f"region={r5}")


def test_data_integrity_across_operations(tr: TestResult):
    """测试16：跨操作数据完整性。"""
    print("\n--- 测试16：跨操作数据完整性 ---")
    cache = TargetCache()

    # 创建不同类型、不同位置、不同置信度的目标
    test_data = [
        ("确定", (500, 400, 100, 40), "button", 0.95),
        ("系统设置", (300, 50, 120, 35), "menu_item", 0.72),
        ("欢迎使用", (960, 100, 200, 50), "text", 0.99),
        ("点击这里", (800, 600, 100, 30), "link", 0.60),
        ("齿轮图标", (50, 50, 30, 30), "icon", 0.45),
        ("用户名", (400, 300, 80, 25), "label", 0.88),
    ]

    targets = [make_target(text, bbox, etype, conf) for text, bbox, etype, conf in test_data]
    cache.add_batch(targets)

    tr.check("6个目标全部添加", cache.size == 6, f"size={cache.size}")

    # 逐一验证每个目标的完整数据
    for i, (text, bbox, etype, conf) in enumerate(test_data):
        t = targets[i]
        found = cache.get_by_id(t.target_id)
        tr.check(f"[{text}] 能按ID找到", found is not None)
        if found:
            tr.check(f"[{text}] text一致", found.text == text)
            x, y, w, h = bbox
            expected_center = (x + w // 2, y + h // 2)
            tr.check(f"[{text}] center一致", found.center == expected_center,
                     f"expected={expected_center}, actual={found.center}")
            tr.check(f"[{text}] bbox一致", found.bbox == bbox)
            tr.check(f"[{text}] type一致", found.element_type == etype)
            tr.check(f"[{text}] confidence一致", found.confidence == conf, f"conf={found.confidence}")
            tr.check(f"[{text}] region非空", found.screen_region in
                     ["top_left", "top_right", "bottom_left", "bottom_right", "center"])


def main():
    print("=" * 60)
    print("T-PC-02 实操测试：目标缓存存取")
    print("=" * 60)

    tr = TestResult()

    tests = [
        test_basic_add_get,
        test_batch_add,
        test_find_by_text,
        test_find_by_type,
        test_find_by_region,
        test_find_by_bbox,
        test_find_nearest,
        test_ttl_expiry,
        test_ttl_realtime_wait,
        test_capacity_eviction,
        test_capacity_eviction_order,
        test_update_existing,
        test_clear,
        test_statistics,
        test_determine_screen_region,
        test_data_integrity_across_operations,
    ]

    for test_fn in tests:
        try:
            test_fn(tr)
        except Exception as e:
            print(f"  [ERROR] {test_fn.__name__}: {e}")
            traceback.print_exc()
            tr.failed += 1
            tr.errors.append(test_fn.__name__)

    all_pass = tr.summary()
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
