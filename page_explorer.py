#!/usr/bin/env python3
"""
页面Tab探测器 v3
修复: iframe延迟、新窗口、三级菜单展开、Tab粘连
"""

import sys, time, json

LOCAL_CHROME_DEBUG = "http://127.0.0.1:9222"
MAIN_URL = "https://pmos.ha.sgcc.com.cn/#/dashboard"

# 会弹新窗口的菜单项（跳过）
SKIP_ITEMS = {"绿证交易"}

# 需要先展开的父节点
EXPAND_PARENTS = ["信息披露"]


def click_by_text(page, text):
    return page.evaluate("""
    (function() {
        var target = "__TARGET__";
        var items = document.querySelectorAll('[role="treeitem"]');
        // 精确匹配
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var t = (el.textContent || '').trim();
            if (t === target) { el.click(); return t.substring(0, 50); }
        }
        // 前缀匹配
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var t = (el.textContent || '').trim();
            if (t.indexOf(target) === 0 && t.length < target.length + 5) {
                el.click(); return t.substring(0, 50);
            }
        }
        return null;
    })()
    """.replace("__TARGET__", text))


def get_tabs_from_iframe(page):
    """从 iframe 中读取 Tab（只用 .el-tabs__item 避免粘连）"""
    return page.evaluate("""
    (function() {
        var iframes = document.querySelectorAll('iframe');
        for (var f = 0; f < iframes.length; f++) {
            try {
                var doc = iframes[f].contentDocument || iframes[f].contentWindow.document;
                if (!doc) continue;
                // 只用精确的 el-tabs__item 选择器
                var els = doc.querySelectorAll('.el-tabs__item');
                if (els.length === 0) {
                    els = doc.querySelectorAll('[role="tab"]');
                }
                var tabs = [];
                var seen = {};
                for (var i = 0; i < els.length; i++) {
                    var t = (els[i].textContent || '').trim();
                    var r = els[i].getBoundingClientRect();
                    if (t && t.length < 20 && r.width > 0 && r.height > 0 && r.top > 30) {
                        if (!seen[t]) { tabs.push(t); seen[t] = true; }
                    }
                }
                if (tabs.length > 0) return tabs;
            } catch(e) {}
        }
        return [];
    })()
    """)


def wait_for_iframe_stable(page, timeout=8):
    """等 iframe 内容稳定：比较前后两次 body 内容，不同则说明已更新"""
    for _ in range(timeout):
        body1 = page.evaluate("""
        (function() {
            var iframes = document.querySelectorAll('iframe');
            for (var i = 0; i < iframes.length; i++) {
                try {
                    var doc = iframes[i].contentDocument;
                    if (doc && doc.body) return doc.body.innerText.substring(0, 200);
                } catch(e) {}
            }
            return '';
        })()
        """)
        time.sleep(1)
        body2 = page.evaluate("""
        (function() {
            var iframes = document.querySelectorAll('iframe');
            for (var i = 0; i < iframes.length; i++) {
                try {
                    var doc = iframes[i].contentDocument;
                    if (doc && doc.body) return doc.body.innerText.substring(0, 200);
                } catch(e) {}
            }
            return '';
        })()
        """)
        if body1 == body2 and body1 != '':
            return  # 内容稳定
    # 超时也继续


def expand_all(page):
    """展开所有菜单"""
    # 第一轮：全点
    page.evaluate("""
    (function() {
        var items = document.querySelectorAll('[role="treeitem"]');
        for (var i = 0; i < items.length; i++) { items[i].click(); }
    })()
    """)
    time.sleep(3)

    # 后续轮：只点收起的
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

    # 额外展开特定父节点
    for parent in EXPAND_PARENTS:
        page.evaluate("""
        (function() {
            var target = "__TARGET__";
            var items = document.querySelectorAll('[role="treeitem"]');
            for (var i = 0; i < items.length; i++) {
                var el = items[i];
                var t = (el.textContent || '').trim();
                if (t === target && el.hasAttribute('aria-expanded') && el.getAttribute('aria-expanded') !== 'true') {
                    el.click();
                }
            }
        })()
        """.replace("__TARGET__", parent))
        time.sleep(1.5)

    # 再展开一轮子节点
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


def get_leaves(page):
    return page.evaluate("""
    (function() {
        var items = document.querySelectorAll('[role="treeitem"]');
        var result = [];
        var parentNames = ["信息披露", "绿证交易"];
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            if (!el.hasAttribute('aria-expanded')) {
                var text = (el.textContent || '').trim().substring(0, 50);
                // 跳过弹窗页面
                var skip = false;
                for (var j = 0; j < parentNames.length; j++) {
                    if (text === parentNames[j]) skip = true;
                }
                if (!skip) result.push(text);
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
    print(" 页面Tab探测器 v3")
    print("=" * 60)

    print(f"\n🔗 连接 Chrome...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(LOCAL_CHROME_DEBUG)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        # 拦截新窗口
        def handle_popup(popup):
            popup.close()
        page.on("popup", handle_popup)

        print(f"🌐 导航到主应用...")
        page.goto(MAIN_URL, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        try:
            page.wait_for_selector('[role="treeitem"]', timeout=15000)
        except:
            print("❌ 侧边栏未加载")
            return

        print(f"🔽 展开全部菜单...")
        expand_all(page)
        total = page.evaluate("document.querySelectorAll('[role=\"treeitem\"]').length")
        print(f"   共 {total} 项")

        leaves = get_leaves(page)
        print(f"🍃 {len(leaves)} 个叶子页面\n")

        results = []
        prev_tabs = None
        for idx, leaf in enumerate(leaves):
            print(f"[{idx+1}/{len(leaves)}] {leaf}...", end=" ", flush=True)

            clicked = click_by_text(page, leaf)
            if not clicked:
                print("❌ 点击失败")
                continue

            # 等 iframe 稳定
            wait_for_iframe_stable(page)
            time.sleep(1)

            tabs = get_tabs_from_iframe(page)
            data_tabs = [t for t in tabs if t not in ('常规菜单', '定制菜单', '展开')]

            # 检测是否读到旧数据
            stale = prev_tabs and data_tabs == prev_tabs
            prev_tabs = data_tabs

            entry = {"path": leaf, "tab_count": len(data_tabs), "tabs": data_tabs}
            if stale:
                entry["stale"] = True
            results.append(entry)

            if data_tabs:
                tag = "⚠️重复" if stale else "✅"
                print(f"{tag} {len(data_tabs)}Tab: {', '.join(data_tabs[:8])}")
            else:
                print(f"📄 无Tab")

        out = "page_tabs.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n💾 {out}")

        with_tabs = [r for r in results if r['tab_count'] > 0]
        stale = [r for r in results if r.get('stale')]
        print(f"📊 {len(with_tabs)}/{len(results)} 个页面有数据Tab")
        if stale:
            print(f"⚠️ {len(stale)} 个页面Tab疑似残留: {[r['path'] for r in stale]}")

    print(f"\n✅ 完成")


if __name__ == "__main__":
    main()