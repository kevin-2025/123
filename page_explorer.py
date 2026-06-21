#!/usr/bin/env python3
"""
页面Tab探测器 v2
从主应用进入，通过侧边栏点击导航，在 iframe 中读取 Tab
用法:
  python3 page_explorer.py
"""

import sys, time, json

LOCAL_CHROME_DEBUG = "http://127.0.0.1:9222"
MAIN_URL = "https://pmos.ha.sgcc.com.cn/#/dashboard"


def click_by_text(page, text):
    return page.evaluate("""
    (function() {
        var target = "__TARGET__";
        var items = document.querySelectorAll('[role="treeitem"]');
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var t = (el.textContent || '').trim();
            if (t.indexOf(target) === 0 && t.length < target.length + 5) {
                el.click(); return t.substring(0, 50);
            }
        }
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var t = (el.textContent || '').trim();
            if (t.indexOf(target) !== -1 && t.length < 50) {
                el.click(); return t.substring(0, 50);
            }
        }
        return null;
    })()
    """.replace("__TARGET__", text))


def get_tabs_from_iframe(page):
    """从 iframe 中读取 Tab"""
    return page.evaluate("""
    (function() {
        var iframes = document.querySelectorAll('iframe');
        for (var f = 0; f < iframes.length; f++) {
            try {
                var doc = iframes[f].contentDocument || iframes[f].contentWindow.document;
                if (!doc) continue;
                var els = doc.querySelectorAll('[class*=tab], .el-tabs__item');
                var tabs = [];
                var seen = {};
                for (var i = 0; i < els.length; i++) {
                    var t = (els[i].textContent || '').trim();
                    var r = els[i].getBoundingClientRect();
                    if (t && t.length < 40 && r.width > 0 && r.height > 0 && r.top > 30) {
                        if (!seen[t]) { tabs.push(t); seen[t] = true; }
                    }
                }
                if (tabs.length > 0) return tabs;
            } catch(e) {}
        }
        return [];
    })()
    """)


def expand_all(page):
    """展开所有菜单"""
    page.evaluate("""
    (function() {
        var items = document.querySelectorAll('[role="treeitem"]');
        for (var i = 0; i < items.length; i++) { items[i].click(); }
    })()
    """)
    time.sleep(3)
    for _ in range(4):
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
        collapsed = page.evaluate(
            "document.querySelectorAll('[role=\"treeitem\"][aria-expanded=\"false\"]').length")
        if collapsed == 0:
            break


def get_leaves(page):
    return page.evaluate("""
    (function() {
        var items = document.querySelectorAll('[role="treeitem"]');
        var result = [];
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            if (!el.hasAttribute('aria-expanded')) {
                var text = (el.textContent || '').trim().substring(0, 50);
                result.push(text);
            }
        }
        return result;
    })()
    """)


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ pip install playwright")
        sys.exit(1)

    print("=" * 60)
    print(" 页面Tab探测器 v2")
    print("=" * 60)

    print(f"\n🔗 连接 Chrome...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(LOCAL_CHROME_DEBUG)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        # 导航到主应用
        print(f"🌐 导航到主应用...")
        page.goto(MAIN_URL, wait_until="networkidle", timeout=60000)
        time.sleep(3)
        print(f"   URL: {page.url[:80]}")

        # 等侧边栏
        try:
            page.wait_for_selector('[role="treeitem"]', timeout=15000)
        except:
            print("❌ 侧边栏未加载")
            return

        # 展开菜单
        print(f"🔽 展开全部菜单...")
        expand_all(page)
        total = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
        print(f"   共 {total} 项")

        # 获取叶子节点
        leaves = get_leaves(page)
        print(f"🍃 {len(leaves)} 个叶子页面\n")

        results = []
        for idx, leaf in enumerate(leaves):
            print(f"[{idx+1}/{len(leaves)}] {leaf}...", end=" ", flush=True)

            # 点击侧边栏导航
            clicked = click_by_text(page, leaf)
            if not clicked:
                print("❌ 点击失败")
                continue

            time.sleep(2.5)

            # 从 iframe 读 Tab
            tabs = get_tabs_from_iframe(page)
            data_tabs = [t for t in tabs if t not in ('常规菜单', '定制菜单')]

            entry = {"path": leaf, "tab_count": len(data_tabs), "tabs": data_tabs}
            results.append(entry)

            if data_tabs:
                print(f"✅ {len(data_tabs)}Tab: {', '.join(data_tabs[:10])}")
            else:
                print(f"📄 无Tab")

        # 保存
        out = "page_tabs.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n💾 {out}")

        with_tabs = [r for r in results if r['tab_count'] > 0]
        print(f"📊 {len(with_tabs)}/{len(results)} 个页面有数据Tab")
        for r in with_tabs:
            print(f"   [{r['tab_count']}Tab] {r['path']}")

    print(f"\n✅ 完成")


if __name__ == "__main__":
    main()