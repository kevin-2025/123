#!/bin/bash
# ==============================================================================
# 电力交易系统 - 爬虫诊断工具
# 用法: bash crawler-diagnosis.sh
# 作用: 扫描服务器上的爬虫脚本，汇总信息
# ==============================================================================

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║          电力交易系统 - 爬虫诊断工具 v1.0                              ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

echo "【1】 查找所有 Python 爬虫脚本..."
echo "──────────────────────────────────────────────────────────────────────"
find / -type f \( -name "*spider*" -o -name "*crawl*" -o -name "*爬虫*" -o -name "*v5*" \) -name "*.py" 2>/dev/null | head -30
echo ""

echo "【2】 查找所有包含 '爬取' 或 'spider' 的 Python 脚本..."
echo "──────────────────────────────────────────────────────────────────────"
grep -rl "爬取\|spider\|crawl" / --include="*.py" 2>/dev/null | grep -v "__pycache__" | grep -v "site-packages" | head -30
echo ""

echo "【3】 查找所有 .sh 脚本（可能有启动脚本）..."
echo "──────────────────────────────────────────────────────────────────────"
find / -type f -name "*.sh" 2>/dev/null | grep -iE "crawl|spider|power|trading|数据" | head -20
echo ""

echo "【4】 检查定时任务 crontab..."
echo "──────────────────────────────────────────────────────────────────────"
crontab -l 2>/dev/null || echo "(无 crontab 或需要 root 权限)"
echo ""

echo "【5】 检查 MySQL 数据库中的数据表..."
echo "──────────────────────────────────────────────────────────────────────"
# 这需要你在 MySQL 中执行以下命令
echo "请在 MySQL 中执行: SHOW TABLES;"
echo ""

echo "【6】 查找最近 3 天修改过的 Python 文件..."
echo "──────────────────────────────────────────────────────────────────────"
find / -type f -name "*.py" -mtime -3 2>/dev/null | grep -v "__pycache__" | grep -v "site-packages" | head -30
echo ""

echo "【7】 检查系统中运行的进程（可能有爬虫在运行）..."
echo "──────────────────────────────────────────────────────────────────────"
ps aux | grep -i python | grep -v grep
echo ""

echo "【8】 检查 /data 和 /opt 目录（常见的爬虫部署位置）..."
echo "──────────────────────────────────────────────────────────────────────"
if [ -d /data ]; then
    echo "=== /data 目录 ==="
    ls -la /data/
    echo ""
    find /data -name "*.py" -type f 2>/dev/null | head -20
fi

if [ -d /opt ]; then
    echo ""
    echo "=== /opt 目录 ==="
    ls -la /opt/
    echo ""
    find /opt -name "*.py" -type f 2>/dev/null | head -20
fi

if [ -d /root ]; then
    echo ""
    echo "=== /root 目录 ==="
    ls -la /root/
    echo ""
    find /root -name "*.py" -type f 2>/dev/null | head -20
fi

if [ -d /home ]; then
    echo ""
    echo "=== /home 目录 ==="
    ls -la /home/
    echo ""
    find /home -name "*.py" -type f 2>/dev/null | head -20
fi

echo ""
echo "【9】 检查 MySQL 数据表结构..."
echo "──────────────────────────────────────────────────────────────────────"
echo "请在 MySQL 中执行以下命令查看表结构:"
echo "  SHOW TABLES;"
echo "  DESCRIBE load_info;"
echo "  DESCRIBE spot_clearing_price;"
echo "  DESCRIBE renewable_generation;"
echo "  DESCRIBE section_data;"
echo ""

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  诊断完成！请把输出结果发回给我，我来帮你优化现有爬虫代码。          ║"
echo "║                                                                      ║"
echo "║  或者，你可以直接把你的 v51 爬虫脚本内容复制粘贴发过来。              ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
