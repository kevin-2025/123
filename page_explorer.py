#!/usr/bin/env python3
"""
页面Tab探测器 — 遍历所有侧边栏菜单项，记录每个页面的Tab信息
用法:
  python3 page_explorer.py
输出: page_tabs.json
"""

import sys, time, json

LOCAL_CHROME_DEBUG = "http://127.0.0.1:9222"
URL = "https://pmos.ha.sgcc.com.cn/pxf-common-qctc/#/pxf-common-qctc/qctc-trade/informationDisclosure/actual"


def get_tabs(page):
    """获取当前页面的所有Tab"""
    return page.evaluate("""
    (function() {
        var result = [];
        var els = document.querySelectorAll('[class*=tab], .el-tabs__item');
        var seen = {};
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var text = (el.textContent || '').trim();
            var rect = el.getBoundingClientRect();
            if (text && text.length < 40 && rect.width > 0 && rect.height > 0 && rect.top > 50) {
                if (!seen[text]) {
                    result.push(text);
                    seen[text] = true;
                }
            }
        }
        return result;
    })()
    """)


def get_menu_tree(page):
    """获取完整菜单树（带ref的层级结构）"""
    return page.evaluate("""
    (function() {
        var items = document.querySelectorAll('[role="treeitem"]');
        var result = [];
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var text = (el.textContent || '').trim();
            var aria = el.getAttribute('aria-expanded') || '';
            var level = 0;
            var parent = el.parentElement;
            while (parent) {
                if (parent.getAttribute && parent.getAttribute('role') === 'group') level++;
                parent = parent.parentElement;
            }
            result.push({
                text: text.substring(0, 50),
                level: level,
                expanded: aria,
                hasAria: el.hasAttribute('aria-expanded')
            });
        }
        return result;
    })()
    """)


def click_by_text(page, text):
    """通过文本内容点击treeitem"""
    return page.evaluate("""
    (function() {
        var target = "__TARGET__";
        var items = document.querySelectorAll('[role="treeitem"]');
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var t = (el.textContent || '').trim();
            if (t.indexOf(target) === 0 && t.length < target.length + 5) {
                el.click();
                return t.substring(0, 50);
            }
        }
        // 回退：模糊匹配
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var t = (el.textContent || '').trim();
            if (t.indexOf(target) !== -1 && t.length < 50) {
                el.click();
                return t.substring(0, 50);
            }
        }
        return null;
    })()
    """.replace("__TARGET__", text))


def expand_all_parents(page):
    """展开所有可展开的父节点"""
    for _ in range(4):
        before = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
        # 第一轮全点，后续只点收起的
        page.evaluate("""
        (function() {
            var items = document.querySelectorAll('[role="treeitem"]');
            for (var i = 0; i < items.length; i++) {
                var el = items[i];
                if (el.hasAttribute('aria-expanded') && el.getAttribute('aria-expanded') !== 'true') {
                    el.click();
                }
            }
        })()
        """)
        time.sleep(2)
        after = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
        collapsed = page.evaluate("document.querySelectorAll('[role=\"treeitem\"][aria-expanded=\"false\"]').length")
        if after == before and collapsed == 0:
            break


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ pip install playwright")
        sys.exit(1)

    print("=" * 60)
    print(" 页面Tab探测器")
    print("=" * 60)

    print(f"\n🔗 连接 Chrome（{LOCAL_CHROME_DEBUG}）...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(LOCAL_CHROME_DEBUG)
        context = browser.contexts[0]

        # 使用已有页面（不新建），取第一个非空白页
        pages = context.pages
        page = None
        for p in pages:
            url = p.url
            if 'pmos' in url or 'sgcc' in url:
                page = p
                break
        if not page:
            page = pages[0] if pages else context.new_page()

        print(f"🌐 使用已有页面: {page.url[:80]}...")

        # 导航到数据页面（确保菜单完整）
        print(f"🌐 导航到数据页面...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        # 等待侧边栏出现
        try:
            page.wait_for_selector('[role="treeitem"]', timeout=15000)
        except:
            print("❌ 侧边栏未加载，请确认页面已打开")
            return

        # 展开所有菜单
        print(f"🔽 展开所有菜单...")
        # 第一轮：逐个点击所有项（初始没有aria-expanded）
        count = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
        print(f"   初始: {count} 项")
        for i in range(count):
            clicked = page.evaluate("""
            (function() {
                var items = document.querySelectorAll('[role="treeitem"]');
                if (__I__ < items.length) {
                    var el = items[__I__];
                    el.click();
                    return (el.textContent || '').trim().substring(0, 30);
                }
                return null;
            })()
            """.replace("__I__", str(i)))
            print(f"   [{i+1}/{count}] 点击: {clicked}")
            time.sleep(5)
        time.sleep(3)

        after_first = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
        print(f"   第一轮后: {after_first} 项")

        # 后续轮：只点收起状态的
        expand_all_parents(page)

        after_expand = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
        print(f"   展开后: {after_expand} 项")

        # 获取菜单树
        menu_tree = get_menu_tree(page)
        print(f"   📋 {len(menu_tree)} 个菜单项")

        # 只遍历叶子节点（没有aria-expanded的 = 没有子菜单）
        leaves = [it for it in menu_tree if not it['hasAria']]
        print(f"   🍃 {len(leaves)} 个叶子页面需要探测\n")

        results = []
        for idx, item in enumerate(leaves):
            indent = "  " * item['level']
            print(f"[{idx+1}/{len(leaves)}] {indent}{item['text']}...", end=" ", flush=True)

            clicked = click_by_text(page, item['text'])
            if not clicked:
                # 可能是父节点被折叠了，先展开再试
                expand_all_parents(page)
                clicked = click_by_text(page, item['text'])

            time.sleep(2.5)

            tabs = get_tabs(page)
            data_tabs = [t for t in tabs if t not in ('常规菜单', '定制菜单')]

            entry = {
                "path": item['text'],
                "level": item['level'],
                "tab_count": len(data_tabs),
                "tabs": data_tabs
            }
            results.append(entry)

            if data_tabs:
                print(f"✅ {len(data_tabs)}Tab: {', '.join(data_tabs[:10])}")
            else:
                print(f"📄 无Tab")

        # 保存结果
        out_file = "page_tabs.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n\n💾 已保存: {out_file}")

        # 统计
        pages_with_tabs = [r for r in results if r['tab_count'] > 0]
        print(f"\n📊 统计: {len(results)}个页面, {len(pages_with_tabs)}个有数据Tab")
        for r in pages_with_tabs:
            print(f"   [{r['tab_count']}Tab] {r['path']}")

        page.close()

    print(f"\n✅ 完成")


if __name__ == "__main__":
    main()