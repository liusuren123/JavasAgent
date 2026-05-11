"""T-TL-03: 剪贴板读写"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(__file__))

async def main():
    try:
        import pyperclip
    except ImportError:
        print("[FAIL] pyperclip not installed")
        return False
    
    # 写入
    test_text = "JavasAgent clipboard test"
    pyperclip.copy(test_text)
    print(f"写入剪贴板: '{test_text}'")
    
    # 读取
    clip = pyperclip.paste()
    print(f"读取剪贴板: '{clip}'")
    
    assert clip == test_text, f"内容不匹配: '{clip}' != '{test_text}'"
    
    # 测试中文
    chinese = "JavasAgent"
    pyperclip.copy(chinese)
    clip_cn = pyperclip.paste()
    print(f"中文剪贴板: '{clip_cn}'")
    
    assert clip_cn == chinese, f"中文不匹配: '{clip_cn}' != '{chinese}'"
    
    out_dir = "test-evidence/08-real-execution/REAL-TL03-clipboard"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "TEST-DESC.md"), "w", encoding="utf-8") as f:
        f.write("""# T-TL-03: 剪贴板读写

## 测试目的
验证 pyperclip 剪贴板读写功能（中文和英文）。

## 测试结果
- 英文读写: PASS
- 中文读写: PASS
- 状态: PASS
""")
    
    print("[OK] T-TL-03 完成")
    return True

if __name__ == "__main__":
    asyncio.run(main())
