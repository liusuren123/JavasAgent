import sys
sys.path.insert(0, "src")
from tools.system_monitor import SystemMonitor
import asyncio
import json

async def main():
    monitor = SystemMonitor()
    
    # 测试1: resource_usage
    result = await monitor.execute("resource_usage", {})
    print("=== resource_usage ===")
    print(json.dumps(result, indent=2, default=str))
    
    # 测试2: top_processes
    result = await monitor.execute("top_processes", {"sort_by": "cpu", "count": 5})
    print("\n=== top_processes (cpu) ===")
    print(json.dumps(result, indent=2, default=str))
    
    # 测试3: system_info
    result = await monitor.execute("system_info", {})
    print("\n=== system_info ===")
    print(json.dumps(result, indent=2, default=str))
    
    # 测试4: snapshot
    result = await monitor.execute("snapshot", {})
    print("\n=== snapshot ===")
    print(json.dumps(result, indent=2, default=str))
    
    # 验证关键数据
    assert "cpu_percent" in str(result) or "cpu" in str(result).lower(), "snapshot应包含cpu信息"
    assert "memory" in str(result).lower(), "snapshot应包含内存信息"
    print("\n✅ T-TL-04 系统监控测试全部通过！")

asyncio.run(main())
