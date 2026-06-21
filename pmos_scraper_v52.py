#!/usr/bin/env python3
"""
电力交易平台 - 一键提取 v52（支持 actual/forecast 双模式）
=============================================================
基于 v51 改写，新增 --mode 参数支持实际数据和预测数据切换
用法:
  python3 pmos_scraper_v52.py --mode actual                              # 默认昨天
  python3 pmos_scraper_v52.py --mode forecast 2026-06-16                # 单日
  python3 pmos_scraper_v52.py --mode actual 2026-03-01 2026-05-25       # 范围
  python3 pmos_scraper_v52.py --mode both 2026-06-16                    # 先 actual 再 forecast
"""

import sys, json, os, time, re, base64, argparse
from datetime import datetime, timedelta

LOCAL_CHROME_DEBUG = "http://127.0.0.1:9222"

# ============================================================
# 模式配置
# ============================================================
MODE_CONFIG = {
    "actual": {
        "url": "https://pmos.ha.sgcc.com.cn/pxf-common-qctc/#/pxf-common-qctc/qctc-trade/informationDisclosure/actual",
        # 侧边栏切换目标（点击 treeitem）
        "switch_to": "电网运行实际信息",
        "tab_keywords": ["负荷", "联络线", "非现货", "新能源", "机组检修", "输变电", "备用", "断面", "必开", "电价"],
        "skip_tabs": {"实际变压器潮流息", "实际线路潮流"},
        "xhr_export_tabs": ["断面约束"],
        "output_prefix": "power_data_actual",
        "label": "实际运行数据"
    },
    "forecast": {
        "url": "https://pmos.ha.sgcc.com.cn/pxf-common-qctc/#/pxf-common-qctc/qctc-trade/informationDisclosure/actual",
        # 侧边栏切换目标（点击 treeitem）
        "switch_to": "电网运行预测信息",
        "tab_keywords": ["负荷", "联络线", "非现货", "新能源", "机组检修", "输变电", "备用", "断面", "必开", "电价", "调频", "调峰", "日前", "开停机"],
        "skip_tabs": set(),
        "xhr_export_tabs": ["断面约束"],
        "output_prefix": "power_data_forecast",
        "label": "预测运行数据"
    }
}

# ============================================================
# 以下函数保持 v51 原样
# ============================================================

def extract_vue_tables(page):
    return page.evaluate("""
    (function() {
        var result = {};
        var tables = document.querySelectorAll('.elx-table');
        for (var i = 0; i < tables.length; i++) {
            var vue = tables[i].__vue__;
            if (!vue) continue;
            var rows = vue.tableSourceData || vue.tableFullData || vue.tableData;
            if (!rows || rows.length === 0) continue;
            result['t' + i] = {rows: rows, count: rows.length};
        }
        return result;
    })()
    """)

def scroll_to_load(page):
    page.evaluate("""
    (function() {
        window.scrollBy(0, 800);
        var els = document.querySelectorAll('.el-table__body-wrapper, .el-scrollbar__wrap, [class*=scroll]');
        for (var i = 0; i < els.length; i++) {
            if (els[i].scrollHeight > els[i].clientHeight) els[i].scrollTop = els[i].scrollHeight / 2;
        }
    })()
    """)
    time.sleep(1)
    page.evaluate("""
    (function() {
        window.scrollBy(0, 800);
        var els = document.querySelectorAll('.el-table__body-wrapper, .el-scrollbar__wrap, [class*=scroll]');
        for (var i = 0; i < els.length; i++) {
            if (els[i].scrollHeight > els[i].clientHeight) els[i].scrollTop = els[i].scrollHeight;
        }
    })()
    """)
    time.sleep(1)
    page.evaluate("window.scrollTo(0, 0);")
    time.sleep(0.5)

def open_date_picker(page):
    pos = page.evaluate("""
    (function() {
        var input = document.querySelector('.el-date-editor .el-input__inner');
        if (!input) return null;
        var rect = input.getBoundingClientRect();
        return {x: rect.left + rect.width/2, y: rect.top + rect.height/2};
    })()
    """)
    if not pos: return False
    page.mouse.click(pos['x'], pos['y'])
    time.sleep(1)
    return True

def get_picker_header(page):
    return page.evaluate("""
    (function() {
        var picker = document.querySelector('.el-picker-panel, .el-date-picker');
        if (!picker) return null;
        var header = picker.querySelector('.el-date-picker__header, .el-picker-panel__header');
        if (!header) return null;
        var text = header.textContent.trim();
        var btns = header.querySelectorAll('button');
        var prev = null, next = null;
        if (btns.length >= 2) {
            var r0 = btns[0].getBoundingClientRect();
            var r1 = btns[1].getBoundingClientRect();
            prev = {x: r0.left + r0.width/2, y: r0.top + r0.height/2};
            next = {x: r1.left + r1.width/2, y: r1.top + r1.height/2};
        }
        return { text: text.slice(0, 30), prevBtn: prev, nextBtn: next };
    })()
    """)

def click_day(page, target_day):
    js = """
    (function() {
        var picker = document.querySelector('.el-picker-panel, .el-date-picker');
        if (!picker) return null;
        var cells = picker.querySelectorAll('td');
        var target = String(__TARGET_DAY__);
        for (var i = 0; i < cells.length; i++) {
            var cell = cells[i];
            var cls = cell.className || '';
            if (cell.textContent.trim() === target &&
                cls.indexOf('prev') === -1 && cls.indexOf('next') === -1 &&
                cls.indexOf('prev-month') === -1 && cls.indexOf('next-month') === -1) {
                var rect = cell.getBoundingClientRect();
                return {x: rect.left + rect.width/2, y: rect.top + rect.height/2};
            }
        }
        return null;
    })()
    """.replace("__TARGET_DAY__", str(target_day))
    pos = page.evaluate(js)
    if not pos: return False
    page.mouse.click(pos['x'], pos['y'])
    time.sleep(2.5)
    return True

def pick_date(page, target_year, target_month, target_day):
    if not open_date_picker(page):
        return False
    diff = 0
    for _ in range(25):
        h = get_picker_header(page)
        if not h: break
        header_text = h.get('text', '')
        ym = re.search(r'(\d{4}).*?(\d{1,2})\s*月', header_text)
        if ym:
            py = int(ym.group(1))
            pm = int(ym.group(2))
            if py == target_year and pm == target_month:
                break
            diff = (target_year - py) * 12 + (target_month - pm)
        if diff > 0 and h.get('nextBtn'):
            page.mouse.click(h['nextBtn']['x'], h['nextBtn']['y'])
        elif diff < 0 and h.get('prevBtn'):
            page.mouse.click(h['prevBtn']['x'], h['prevBtn']['y'])
        else:
            break
        time.sleep(0.3)
    time.sleep(0.5)
    return click_day(page, target_day)


def export_section_xhr(page):
    """通过 XHR 拦截获取断面约束导出 Excel"""
    print(f"\n   📥 XHR拦截导出...", end=" ", flush=True)

    page.evaluate("""
    (function() {
        window.__xhrExport = {done: false, data: null, size: 0};
        var origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this._url = url;
            return origOpen.apply(this, arguments);
        };
        var origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function(body) {
            var self = this;
            if (this._url && this._url.indexOf('exportExcel') !== -1) {
                this.responseType = 'arraybuffer';
                this.addEventListener('load', function() {
                    if (self.response && self.response.byteLength > 0) {
                        var bytes = new Uint8Array(self.response);
                        var binary = '';
                        for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                        window.__xhrExport.data = btoa(binary);
                        window.__xhrExport.size = bytes.length;
                        window.__xhrExport.done = true;
                    }
                });
            }
            return origSend.apply(this, arguments);
        };
    })()
    """)

    page.evaluate("""
    (function() {
        var els = document.querySelectorAll('.el-dialog__wrapper, .v-modal');
        for (var i = 0; i < els.length; i++) els[i].style.display = 'none';
    })()
    """)
    time.sleep(0.3)

    page.evaluate("""
    (function() {
        var btns = document.querySelectorAll('.el-button--primary');
        for (var i = 0; i < btns.length; i++) {
            var b = btns[i];
            if ((b.textContent || '').indexOf('导出') !== -1) {
                b.click();
                return;
            }
        }
    })()
    """)

    for i in range(20):
        time.sleep(0.5)
        status = page.evaluate("window.__xhrExport ? {done: window.__xhrExport.done, size: window.__xhrExport.size || 0} : {done: false, size: 0}")
        if status['done']:
            print(f"✅ {status['size']/1024:.0f}KB", end=" ", flush=True)
            break
    else:
        print(f"⏰ 超时")
        page.evaluate("""
        (function() {
            var els = document.querySelectorAll('.el-dialog__wrapper, .v-modal');
            for (var i = 0; i < els.length; i++) els[i].style.display = '';
        })()
        """)
        return None

    data_b64 = page.evaluate("window.__xhrExport ? window.__xhrExport.data : null")

    page.evaluate("""
    (function() {
        var els = document.querySelectorAll('.el-dialog__wrapper, .v-modal');
        for (var i = 0; i < els.length; i++) els[i].style.display = '';
    })()
    """)

    if not data_b64:
        return None

    # 方法1: openpyxl 解析
    try:
        import openpyxl, io
        binary = base64.b64decode(data_b64)
        wb = openpyxl.load_workbook(io.BytesIO(binary), data_only=True)
        ws = wb.active
        rows_list = list(ws.iter_rows(values_only=True))
        if rows_list:
            headers = [str(h) if h else 'col_%d' % i for i, h in enumerate(rows_list[0])]
            data = []
            for row in rows_list[1:]:
                if row and any(v is not None for v in row):
                    item = {}
                    for j, h in enumerate(headers):
                        if j < len(row) and row[j] is not None:
                            item[h] = row[j]
                    if item:
                        data.append(item)
            print(f"📊 {len(data)}行 {len(headers)}列")
            return data
        else:
            # 保存原始文件用于调试
            fname = 'section_debug.xlsx'
            with open(fname, 'wb') as f:
                f.write(binary)
            print(f"⚠️ openpyxl读出0行，已保存原始文件: {fname}")
    except ImportError:
        print(f"⚠️ pip install openpyxl")
    except Exception as e:
        print(f"⚠️ openpyxl错误: {e}，尝试xlrd...")
        # 方法2: 可能是xls格式
        try:
            import xlrd
            binary = base64.b64decode(data_b64)
            fname = 'section_debug.xls'
            with open(fname, 'wb') as f:
                f.write(binary)
            wb = xlrd.open_workbook(fname)
            ws = wb.sheet_by_index(0)
            headers = [ws.cell_value(0, j) for j in range(ws.ncols)]
            data = []
            for i in range(1, ws.nrows):
                row = ws.row_values(i)
                if any(v is not None and v != '' for v in row):
                    item = {}
                    for j, h in enumerate(headers):
                        if j < len(row) and row[j] != '':
                            item[str(h) if h else 'col_%d' % j] = row[j]
                    if item:
                        data.append(item)
            print(f"📊 {len(data)}行 {len(headers)}列")
            return data
        except ImportError:
            print(f"⚠️ pip install xlrd")
        except Exception as e2:
            print(f"⚠️ xlrd也失败: {e2}，已保存section_debug.xlsx供手动检查")

    return None


def scrape_single_date(page, date_str, data_tabs, tab_positions, mode_cfg):
    """抓取单日所有 Tab 数据（v51 原版逻辑 + mode 配置）"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    ty = d.year; tm = d.month; td = d.day

    all_data = {}
    total_rows = 0
    skip_tabs = mode_cfg['skip_tabs']
    xhr_tabs = mode_cfg['xhr_export_tabs']

    date_set = False  # 日期只选一次，所有Tab共用

    for tab_idx, tab in enumerate(data_tabs):
        if tab['text'] in skip_tabs:
            continue

        print(f"  📊 [{tab_idx+1}/{len(data_tabs)}] {tab['text']}...", end=" ", flush=True)
        try:
            # 步骤1：点击Tab
            page.mouse.click(tab['x'], tab['y'])
            time.sleep(2)

            # 步骤2：选择日期（仅第一个Tab执行一次，后续Tab跳过）
            if not date_set:
                date_ok = pick_date(page, ty, tm, td)
                if not date_ok:
                    print(f"   ⚠️ 日期选择器无法打开")
                    continue
                date_set = True
                time.sleep(1.5)

            # 步骤3：滚动加载
            scroll_to_load(page)

            # 步骤4：XHR导出 或 Vue提取
            if any(kw in tab['text'] for kw in xhr_tabs):
                excel_data = export_section_xhr(page)
                if excel_data:
                    all_data[tab['text']] = {"exported": True, "rows": excel_data, "count": len(excel_data)}
                    total_rows += len(excel_data)
                    print(f"   ✅ {len(excel_data)}行")
                else:
                    print(f"   ⚠️ 导出失败")
                continue

            vue_data = extract_vue_tables(page)
            unique_tables = {}
            for k, v in vue_data.items():
                rows = v['rows']
                if not rows: continue
                unique_tables[k] = v

            if unique_tables:
                count = sum(v['count'] for v in unique_tables.values())
                total_rows += count
                all_data[tab['text']] = unique_tables
                print(f"   ✅ {count}行")
            else:
                print(f"   ⚠️ 无数据")

        except Exception as e:
            print(f"❌ {type(e).__name__}: {e}")

    return all_data, total_rows


# ============================================================
# 新增：页面内模式切换（实际/预测）
# ============================================================
def switch_mode_in_page(page, switch_to):
    """点击侧边栏 treeitem 切换到目标页面"""
    # 先确保"信息披露"父节点已展开
    page.evaluate("""
    (function() {
        var items = document.querySelectorAll('[role="treeitem"]');
        for (var i = 0; i < items.length; i++) {
            var text = (items[i].textContent || '').trim();
            if (text.indexOf('信息披露') !== -1 && text.length < 20) {
                // 检查是否已展开，未展开则点击
                var ariaExpanded = items[i].getAttribute('aria-expanded');
                if (ariaExpanded !== 'true') {
                    items[i].click();
                }
                break;
            }
        }
    })()
    """)
    time.sleep(1.5)

    # 再点击目标 treeitem
    js_code = """
    (function() {
        var target = "__TARGET__";
        var items = document.querySelectorAll('[role="treeitem"]');
        for (var i = 0; i < items.length; i++) {
            var el = items[i];
            var text = (el.textContent || '').trim();
            if (text.indexOf(target) !== -1 && text.length < 30) {
                var rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    return {
                        text: text.substring(0, 30),
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2
                    };
                }
            }
        }
        return null;
    })()
    """.replace("__TARGET__", switch_to)

    try:
        result = page.evaluate(js_code)
        return result
    except Exception as e:
        print(f"   [switch JS错误: {e}]")
        return None


# ============================================================
# 新增：按模式运行
# ============================================================
def run_mode(mode, dates, browser):
    """运行单个模式"""
    cfg = MODE_CONFIG[mode]
    url = cfg['url']
    tab_keywords = cfg['tab_keywords']
    output_prefix = cfg['output_prefix']
    switch_to = cfg['switch_to']

    print(f"\n{'#'*60}")
    print(f"# 🎯 模式: {mode} ({cfg['label']})")
    print(f"# 🌐 URL: {url}")
    print(f"# 🔀 侧边栏切换: 点击\"{switch_to}\"")
    print(f"{'#'*60}")

    context = browser.contexts[0]
    page = context.new_page()

    print(f"\n🌐 打开数据页面...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    # 点击侧边栏 treeitem 切换到目标页面
    print(f"\n🔀 在侧边栏查找并点击\"{switch_to}\"...")
    sw_el = switch_mode_in_page(page, switch_to)
    if sw_el:
        print(f"   找到: {sw_el.get('text')}")
        page.mouse.click(sw_el['x'], sw_el['y'])
        time.sleep(3)
    else:
        print(f"   ⚠️ 未找到\"{switch_to}\"侧边栏项（可能已在正确页面）")

    print("\n🔘 获取 Tab...")
    tabs = page.evaluate("""
    (function() {
        var result = [];
        var els = document.querySelectorAll('[class*=tab], .el-tabs__item');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var text = (el.textContent || '').trim();
            var rect = el.getBoundingClientRect();
            if (text && text.length < 40 && rect.width > 0 && rect.height > 0 && rect.top > 50) {
                result.push({text: text, x: rect.left + rect.width/2, y: rect.top + rect.height/2});
            }
        }
        return result;
    })()
    """)
    data_tabs = [t for t in tabs if any(k in t['text'] for k in tab_keywords)]
    print(f"   页面共 {len(tabs)} 个 Tab，匹配 {len(data_tabs)} 个:")
    for t in data_tabs:
        print(f"     - {t['text']}")

    all_dates_data = {}
    grand_total = 0

    for di, date_str in enumerate(dates):
        print(f"\n{'='*60}")
        print(f"📅 [{di+1}/{len(dates)}] {date_str}")
        print(f"{'='*60}")

        day_data, day_rows = scrape_single_date(page, date_str, data_tabs, tabs, cfg)

        if day_data:
            all_dates_data[date_str] = day_data
            grand_total += day_rows
            print(f"   📊 {date_str}: {day_rows} 行")

            if (di + 1) % 5 == 0 or di == len(dates) - 1:
                f = f"{output_prefix}_{dates[0]}_{dates[-1]}.json"
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(all_dates_data, fp, ensure_ascii=False, indent=2, default=str)
                print(f"   💾 已保存: {f} ({os.path.getsize(f)/1024:.0f} KB)")

    if all_dates_data:
        f = f"{output_prefix}_{dates[0]}_{dates[-1]}.json"
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(all_dates_data, fp, ensure_ascii=False, indent=2, default=str)

        print(f"\n{'='*60}")
        print(f"🎉 {mode} 模式完成！")
        print(f"   日期数: {len(all_dates_data)}/{len(dates)}")
        print(f"   总行数: {grand_total}")
        print(f"   文件: {f} ({os.path.getsize(f)/1024:.0f} KB)")

    page.screenshot(path=f"v52_{mode}_{dates[-1]}.png", full_page=True)
    print(f"\n📸 截图: v52_{mode}_{dates[-1]}.png")

    page.close()
    return all_dates_data


def parse_args():
    parser = argparse.ArgumentParser(description='PMOS 数据抓取 v52')
    parser.add_argument('--mode', type=str, default='actual',
                       choices=['actual', 'forecast', 'both'],
                       help='抓取模式: actual=实际数据, forecast=预测数据, both=两者都抓')
    parser.add_argument('dates', nargs='*', help='日期（YYYY-MM-DD），可指定一个或两个（范围）')
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print(" 一键提取 v52（支持 actual/forecast 双模式）")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ pip install playwright")
        sys.exit(1)

    # 解析日期
    date_args = args.dates
    if len(date_args) >= 2:
        start_date = datetime.strptime(date_args[0], '%Y-%m-%d')
        end_date = datetime.strptime(date_args[1], '%Y-%m-%d')
        dates = []
        d = start_date
        while d <= end_date:
            dates.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=1)
        print(f" 📅 日期范围: {date_args[0]} ~ {date_args[1]}（共 {len(dates)} 天）")
    elif len(date_args) == 1:
        dates = [date_args[0]]
        print(f" 🎯 目标日期: {date_args[0]}")
    else:
        today = datetime.now()
        yest = today - timedelta(days=1)
        dates = [yest.strftime('%Y-%m-%d')]
        print(f" 🎯 默认日期: {dates[0]}")

    modes = ['actual', 'forecast'] if args.mode == 'both' else [args.mode]

    print(f"\n🔗 连接 Chrome（{LOCAL_CHROME_DEBUG}）...")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(LOCAL_CHROME_DEBUG)
        print(f"   ✅ 已连接 Chrome，contexts: {len(browser.contexts)}")

        results = {}
        for mode in modes:
            try:
                results[mode] = run_mode(mode, dates, browser)
            except Exception as e:
                print(f"\n❌ {mode} 模式出错: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'='*60}")
        print(f"🏁 全部完成！模式: {', '.join(modes)}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
