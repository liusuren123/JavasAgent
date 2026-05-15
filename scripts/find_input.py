"""通过截屏像素分析精确定位 Agent 输入框。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from PIL import ImageGrab

# 截取左侧面板底部
img = ImageGrab.grab(bbox=(0, 1800, 1000, 2160))
w, h = img.size
print(f"截图大小: {w}x{h}")

# 扫描每一行的颜色特征，找到输入框的边界
# 输入框通常有一个不同于背景的边框或背景色
# 从底部向上扫描
for y in range(h - 1, 0, -1):
    row_pixels = [img.getpixel((x, y)) for x in range(0, w, 50)]
    # 检查是否有明显的颜色变化行（输入框边框）
    r_vals = [p[0] for p in row_pixels]
    g_vals = [p[1] for p in row_pixels]
    b_vals = [p[2] for p in row_pixels]
    avg_r = sum(r_vals) / len(r_vals)
    avg_g = sum(g_vals) / len(g_vals)
    avg_b = sum(b_vals) / len(b_vals)
    
    # 打印底部 50 行的颜色信息
    if y > h - 60:
        print(f"  行 {y+1800}: R={avg_r:.0f} G={avg_g:.0f} B={avg_b:.0f}")

# 找到 Edits 栏 — 保存几个关键行的颜色样本
print("\n关键区域颜色分析:")
for screen_y in [2050, 2060, 2070, 2080, 2090, 2100, 2110, 2120, 2130, 2140, 2150]:
    if screen_y - 1800 < h:
        center_pixel = img.getpixel((400, screen_y - 1800))
        print(f"  y={screen_y}: {center_pixel}")

img.save("scripts/agent_bottom_analysis.png")
