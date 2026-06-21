#!/usr/bin/env python3
"""
菜单探测工具 — 连 Chrome 展开所有侧边栏菜单，打印完整树结构
用法:
  python3 menu_explorer.py
"""

import sys, time, json

LOCAL_CHROME_DEBUG = "http://127.0.0.1:9222"
URL = "https://pmos.ha.sgcc.com.cn/pxf-common-qctc/#/pxf-common-qctc/qctc-trade/informationDisclosure/actual"


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ pip install playwright")
        sys.exit(1)

    print("=" * 60)
    print(" 菜单探测工具")
    print("=" * 60)

    print(f"\n🔗 连接 Chrome（{LOCAL_CHROME_DEBUG}）...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(LOCAL_CHROME_DEBUG)
        print(f"   ✅ 已连接，contexts: {len(browser.contexts)}")

        context = browser.contexts[0]
        page = context.new_page()

        print(f"\n🌐 打开页面...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        # 多轮展开所有菜单
        print(f"\n🔽 展开所有菜单...")
        for round_num in range(3):
            before = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
            page.evaluate("""
            (function() {
                var items = document.querySelectorAll('[role="treeitem"]');
                for (var i = 0; i < items.length; i++) {
                    var el = items[i];
                    // 只点有 aria-expanded 属性的（父节点），叶子节点会跳转页面
                    if (el.hasAttribute('aria-expanded') && el.getAttribute('aria-expanded') !== 'true') {
                        el.click();
                    }
                }
            })()
            """)
            time.sleep(2)
            after = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
            print(f"   第{round_num+1}轮: {before} → {after} 项")
            if after == before:
                break  # 没有新项出现，说明都展开了

        # 获取完整菜单树
        menu_tree = page.evaluate("""
        (function() {
            var items = document.querySelectorAll('[role="treeitem"]');
            var result = [];
            for (var i = 0; i < items.length; i++) {
                var text = (items[i].textContent || '').trim();
                var aria = items[i].getAttribute('aria-expanded') || '';
                var level = 0;
                var parent = items[i].parentElement;
                while (parent) {
                    if (parent.getAttribute && parent.getAttribute('role') === 'group') level++;
                    parent = parent.parentElement;
                }
                result.push({text: text, level: level, expanded: aria});
            }
            return result;
        })()
        """)

        # 打印树
        print(f"\n{'='*60}")
        print(f"📋 完整菜单树 ({len(menu_tree)}项)")
        print(f"{'='*60}")
        for it in menu_tree:
            indent = "  " * it['level']
            mark = "▼" if it['expanded'] == 'true' else "▶"
            print(f"{indent}{mark} {it['text']}")

        # 保存 JSON
        out_file = "menu_tree.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(menu_tree, f, ensure_ascii=False, indent=2)
        print(f"\n💾 已保存: {out_file}")

        page.close()

    print(f"\n✅ 完成")


if __name__ == "__main__":
    main()