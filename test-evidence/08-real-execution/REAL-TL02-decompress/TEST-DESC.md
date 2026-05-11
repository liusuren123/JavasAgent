# T-TL-02: 文件解压 (BUG-002 回归测试)

## 测试目的
验证 decompress_archive() 接受 str 类型 workspace 参数（BUG-002 修复回归）。

## 测试步骤
1. 创建临时文件 hello.txt
2. 用 str 类型 workspace 调用 compress_files() 压缩
3. 用 str 类型 workspace 调用 decompress_archive() 解压
4. 验证解压文件内容一致

## 测试结果
- compress_files(workspace=str): PASS
- decompress_archive(workspace=str): PASS
- 内容验证: PASS
- 状态: PASS (BUG-002 修复已验证)
