#!/usr/bin/env python3
"""
电力交易平台 - 一键提取 v52（支持 actual/forecast 双模式）
=============================================================
v52: 一个脚本 + mode 参数，同时支持实际数据和预测数据抓取
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
# 模式配置（每种模式独立的 URL、Tab 关键词、跳过列表、输出前缀）
# ============================================================
MODE_CONFIG = {
    "actual": {
        "url": "https://pmos.ha.sgcc.com.cn/pxf-common-qctc/#/pxf-common-qctc/qctc-trade/informationDisclosure/actual",
        "tab_keywords": ["负荷", "联络线", "非现货", "新能源", "机组检修", "输变电", "备用", "断面", "必开", "电价"],
        "skip_tabs": {"实际变压器潮流息", "实际线路潮流"},
        "xhr_export_tabs": ["断面约束"],
        "output_prefix": "power_data_actual",
        "label": "实际运行数据"
    },
    "forecast": {
        "url": "https://pmos.ha.sgcc.com.cn/pxf-common-qctc/#/pxf-common-qctc/qctc-trade/informationDisclosure/forecast",
        "tab_keywords": ["负荷", "联络线", "非现货", "新能源", "机组检修", "输变电", "备用", "断面", "必开", "电价", "调频", "调峰", "日前", "开停机"],
        "skip_tabs": set(),
        "xhr_export_tabs": ["断面约束"],
        "output_prefix": "power_data_forecast",
        "label": "预测运行数据"
    }
}


def extract_vue_tables(page):
    return page.evaluate("""() => {
        const result = {};
        document.querySelectorAll('.elx-table').forEach((table, idx) => {
            const vue = table.__vue__;
            if (!vue) return;
            let rows = vue.tableSourceData || vue.tableFullData || vue.tableData || [];
            if (!rows || rows.length === 0) return;
            result['t' + idx] = {rows: rows, count: rows.length};
        });
        return result;
    }""")


def scroll_to_load(page):
    page.evaluate("""() => {
        window.scrollBy(0, 800);
        document.querySelectorAll('.el-table__body-wrapper, .el-scrollbar__wrap, [class*=scroll]').forEach(el => {
            if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight / 2;
        });
    }""")
    time.sleep(1)
    page.evaluate("""() => {
        window.scrollBy(0, 800);
        document.querySelectorAll('.el-table__body-wrapper, .el-scrollbar__wrap, [class*=scroll]').forEach(el => {
            if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
        });
    }""")
    time.sleep(1)
    page.evaluate("""() => { window.scrollTo(0, 0); }""")
    time.sleep(0.5)


def open_date_picker(page):
    pos = page.evaluate("""() => {
        const input = document.querySelector('.el-date-editor .el-input__inner');
        if (!input) return null;
        const rect = input.getBoundingClientRect();
        return {x: rect.left + rect.width/2, y: rect.top + rect.height/2};
    }""")
    if not pos: return False
    page.mouse.click(pos['x'], pos['y'])
    time.sleep(1)
    return True


def get_picker_header(page):
    return page.evaluate("""() => {
        const picker = document.querySelector('.el-picker-panel, .el-date-picker');
        if (!picker) return null;
        const header = picker.querySelector('.el-date-picker__header, .el-picker-panel__header');
        if (!header) return null;
        const text = header.textContent.trim();
        const btns = header.querySelectorAll('button');
        let prev = null, next = null;
        if (btns.length >= 2) {
            const r0 = btns[0].getBoundingClientRect();
            const r1 = btns[1].getBoundingClientRect();
            prev = {x: r0.left + r0.width/2, y: r0.top + r0.height/2};
            next = {x: r1.left + r1.width/2, y: r1.top + r1.height/2};
        }
        return { text: text[:30], prevBtn: prev, nextBtn: next };
    }""")


def click_day(page, target_day):
    pos = page.evaluate(f"""() => {{
        const picker = document.querySelector('.el-picker-panel, .el-date-picker');
        if (!picker) return null;
        const cells = picker.querySelectorAll('td');
        for (const cell of cells) {{
            const cls = cell.className;
            if (cell.textContent.trim() === String({target_day}) &&
                !cls.includes('prev') && !cls.includes('next') &&
                !cls.includes('prev-month') && !cls.includes('next-month')) {{
                const rect = cell.getBoundingClientRect();
                return {{x: rect.left + rect.width/2, y: rect.top + rect.height/2}};
            }}
        }}
        return null;
    }}""")
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

    page.evaluate("""() => {
        window.__xhrExport = {done: false, data: null, size: 0};
        const origOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url) {
            this._url = url;
            return origOpen.apply(this, arguments);
        };
        const origSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function(body) {
            if (this._url && this._url.includes('exportExcel')) {
                this.responseType = 'arraybuffer';
                this.addEventListener('load', function() {
                    if (this.response && this.response.byteLength > 0) {
                        const bytes = new Uint8Array(this.response);
                        let binary = '';
                        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                        window.__xhrExport.data = btoa(binary);
                        window.__xhrExport.size = bytes.length;
                        window.__xhrExport.done = true;
                    }
                });
            }
            return origSend.apply(this, arguments);
        };
    }""")

    page.evaluate("""() => {
        document.querySelectorAll('.el-dialog__wrapper, .v-modal').forEach(el => {
            el.style.display = 'none';
        });
    }""")
    time.sleep(0.3)

    page.evaluate("""() => {
        const btns = document.querySelectorAll('.el-button--primary');
        for (const b of btns) {
            if ((b.textContent || '').includes('导出')) {
                b.click();
                return;
            }
        }
    }""")

    for i in range(20):
        time.sleep(0.5)
        status = page.evaluate("""() => {
            return {done: window.__xhrExport.done, size: window.__xhrExport.size || 0};
        }""")
        if status['done']:
            print(f"✅ {status['size']/1024:.0f}KB", end=" ", flush=True)
            break
    else:
        print(f"⏰ 超时")
        page.evaluate("""() => {
            document.querySelectorAll('.el-dialog__wrapper, .v-modal').forEach(el => {
                el.style.display = '';
            });
        }""")
        return None

    data_b64 = page.evaluate("""() => window.__xhrExport.data || null""")

    page.evaluate("""() => {
        document.querySelectorAll('.el-dialog__wrapper, .v-modal').forEach(el => {
            el.style.display = '';
        });
    }""")

    if not data_b64:
        return None

    try:
        import openpyxl, io
        binary = base64.b64decode(data_b64)
        wb = openpyxl.load_workbook(io.BytesIO(binary), data_only=True)
        ws = wb.active
        rows_list = list(ws.iter_rows(values_only=True))
        if rows_list:
            headers = [str(h) if h else f'col_{i}' for i, h in enumerate(rows_list[0])]
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
    except ImportError:
        print(f"⚠️ pip install openpyxl")
    except Exception as e:
        print(f"⚠️ {e}")

    return None


def get_table_fingerprint(rows):
    if not rows: return ""
    sample = rows[:3]
    return json.dumps([dict(sorted(r.items())) for r in sample], sort_keys=True, default=str)


def scrape_single_date(page, date_str, data_tabs, tab_positions, mode_cfg):
    """抓取单日所有 Tab 数据（基于 mode 配置）"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    ty = d.year; tm = d.month; td = d.day

    all_data = {}
    total_rows = 0
    skip_tabs = mode_cfg['skip_tabs']
    xhr_tabs = mode_cfg['xhr_export_tabs']

    for tab_idx, tab in enumerate(data_tabs):
        if tab['text'] in skip_tabs:
            print(f"  ⏭️  [{tab_idx+1}/{len(data_tabs)}] {tab['text']} (跳过)")
            continue

        print(f"  📊 [{tab_idx+1}/{len(data_tabs)}] {tab['text']}...", end=" ", flush=True)
        try:
            page.mouse.click(tab['x'], tab['y'])
            time.sleep(2)

            pick_date(page, ty, tm, td)
            time.sleep(1.5)

            scroll_to_load(page)

            # XHR导出（断面约束等）
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
            print(f"❌ {e}")

    return all_data, total_rows


def run_mode(mode, dates, browser):
    """运行单个模式（actual 或 forecast）"""
    cfg = MODE_CONFIG[mode]
    url = cfg['url']
    tab_keywords = cfg['tab_keywords']
    output_prefix = cfg['output_prefix']

    print(f"\n{'#'*60}")
    print(f"# 🎯 模式: {mode} ({cfg['label']})")
    print(f"# 🌐 URL: {url}")
    print(f"{'#'*60}")

    context = browser.contexts[0]
    page = context.new_page()

    print(f"\n🌐 打开数据页面...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    print("\n🔘 获取 Tab...")
    tabs = page.evaluate("""() => {
        const tabs = [];
        document.querySelectorAll('[class*=tab], .el-tabs__item').forEach(el => {
            const text = el.textContent.trim();
            const rect = el.getBoundingClientRect();
            if (text && text.length < 40 && rect.width > 0 && rect.height > 0 && rect.top > 50) {
                tabs.push({text, x: rect.left + rect.width/2, y: rect.top + rect.height/2});
            }
        });
        return tabs;
    }""")
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

    # 确定要运行的模式
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
