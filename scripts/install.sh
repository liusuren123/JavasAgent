#!/usr/bin/env bash
# JavasAgent Linux/macOS 一键安装脚本
# 用法: ./scripts/install.sh

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
GRAY='\033[0;90m'
NC='\033[0m'

echo -e "${CYAN}========================================"
echo -e "  JavasAgent 安装脚本 (Linux/macOS)"
echo -e "========================================${NC}"
echo ""

# 1. 检查 Python 版本
echo -e "${YELLOW}[1/6] 检查 Python 版本...${NC}"

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$($cmd --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON_CMD="$cmd"
            echo -e "  找到 $($cmd --version 2>&1)${NC}" | sed "s/\\\e.*//g/"
            echo -e "  ${GREEN}找到 $($cmd --version 2>&1)${NC}"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "  ${RED}错误: 需要 Python 3.11+，请先安装 Python${NC}"
    exit 1
fi

# 2. 创建虚拟环境
echo -e "${YELLOW}[2/6] 创建虚拟环境...${NC}"

if [ -d "venv" ]; then
    echo -e "  ${GRAY}虚拟环境已存在，跳过${NC}"
else
    $PYTHON_CMD -m venv venv
    echo -e "  ${GREEN}虚拟环境已创建${NC}"
fi

source venv/bin/activate

# 3. 安装核心依赖
echo -e "${YELLOW}[3/6] 安装核心依赖...${NC}"

pip install -e "." 2>&1 | while read line; do echo -e "  ${GRAY}${line}${NC}"; done
echo -e "  ${GREEN}核心依赖安装完成${NC}"

# 4. 安装可选依赖
echo -e "${YELLOW}[4/6] 安装可选依赖（语音模块）...${NC}"

pip install edge-tts 2>/dev/null || true
pip install pyaudio 2>/dev/null || pip install sounddevice 2>/dev/null || true
echo -e "  ${GREEN}可选依赖安装完成（部分可能跳过）${NC}"

# 5. 检查配置
echo -e "${YELLOW}[5/6] 检查配置文件...${NC}"

if [ ! -f "config/default.yaml" ]; then
    echo -e "  ${YELLOW}警告: config/default.yaml 不存在${NC}"
else
    echo -e "  ${GREEN}配置文件已就绪${NC}"
fi

mkdir -p data/memory/chroma data/screenshots data/logs
echo -e "  ${GREEN}数据目录已创建${NC}"

# 6. 验证安装
echo -e "${YELLOW}[6/6] 验证安装...${NC}"

if python -c "import src; print('OK')" 2>/dev/null | grep -q "OK"; then
    echo -e "  ${GREEN}验证通过！${NC}"
else
    echo -e "  ${YELLOW}警告: 模块导入测试未通过，请检查依赖${NC}"
fi

echo ""
echo -e "${CYAN}========================================"
echo -e "  ${GREEN}安装完成！"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "  激活虚拟环境:"
echo -e "    ${CYAN}source venv/bin/activate${NC}"
echo ""
echo -e "  启动对话:"
echo -e "    ${CYAN}javas chat${NC}"
echo ""
