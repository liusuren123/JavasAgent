# T-PC-02 实操测试：目标缓存存取

## 测试目的
验证 `src/perception/target_cache.py` 中 `TargetCache` 类的核心功能是否正常工作，包括目标的添加、查询、过期淘汰和容量限制。

## 测试方法

### 测试对象
- `TargetCache` 类：目标缓存管理器
- `TargetInfo` 数据类：目标信息载体
- `determine_screen_region` 函数：屏幕区域判定

### 测试覆盖项（16个测试场景，110个断言）

| # | 测试场景 | 验证内容 |
|---|---------|---------|
| 1 | 基本添加和按ID获取 | add/get_by_id，字段完整性 |
| 2 | 批量添加 | add_batch，缓存大小 |
| 3 | 按文字查找 | find_by_text（包含匹配/精确匹配） |
| 4 | 按类型查找 | find_by_type（button/label/link/icon） |
| 5 | 按屏幕区域查找 | find_by_region（top_left/center/bottom_right） |
| 6 | 按位置区域查找 | find_by_bbox（距离容差匹配） |
| 7 | 最近目标查找 | find_nearest（全局/按类型） |
| 8 | TTL过期淘汰 | remove_expired（手动设置created_at模拟过期） |
| 9 | 实时TTL过期 | time.sleep等待真实过期 |
| 10 | 容量限制淘汰 | max_size限制，FIFO淘汰最旧 |
| 11 | 淘汰顺序验证 | 多次超容量添加后验证淘汰顺序 |
| 12 | 更新已有目标 | 同ID目标更新，字段正确变化 |
| 13 | 清空缓存 | clear()重置所有状态 |
| 14 | 统计信息 | type_counts/region_counts/hits/misses/hit_rate |
| 15 | 屏幕区域判定 | determine_screen_region 五个区域判定 |
| 16 | 跨操作数据完整性 | 6种不同类型目标，逐一验证所有字段 |

## 测试环境

- **操作系统**: Windows 10/11 (x64)
- **Python 版本**: 3.13.12
- **测试方式**: 直接实例化 TargetCache，调用实际方法，无 mock
- **模块加载**: 通过 importlib 动态加载 target_cache.py，避免 perception/__init__.py 的重量级依赖

## 测试结果

**✅ PASS — 110/110 断言全部通过，0 失败**

### 关键验证点

1. **数据完整性**: bbox、center、text、element_type、confidence、screen_region 所有字段正确
2. **TTL过期**: 0.3秒TTL，实际等待0.4秒后过期清除正常工作
3. **容量淘汰**: max_size=3时，第4个目标添加后最旧目标被淘汰，FIFO顺序正确
4. **查询功能**: 按文字（包含/精确）、类型、区域、bbox、最近距离查询全部正确
5. **统计功能**: 命中率、类型计数、区域计数准确

## 证据文件

- `test_real_pc02.py` — 测试脚本
- `output.txt` — 运行输出
- `TEST-DESC.md` — 本文件
