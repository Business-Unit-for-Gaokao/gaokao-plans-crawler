import itertools
import json
import os
import time
from pathlib import Path

from .base import BaseCrawler


class PlanCrawler(BaseCrawler):
    def __init__(self):
        super().__init__()
        self.progress_dir = Path(os.getenv('PLAN_PROGRESS_DIR', 'data/plans_progress'))
        self.plan_data_dir = Path(os.getenv('PLAN_DATA_DIR', 'data/plans'))
        self.run_deadline_seconds = int(os.getenv('PLAN_RUN_DEADLINE_SECONDS', '17400'))
        self.flush_schools = max(1, int(os.getenv('PLAN_FLUSH_SCHOOLS', '10')))
        self.flush_combos = max(1, int(os.getenv('PLAN_FLUSH_COMBOS', '5')))
        self.browser_headless = os.getenv('PLAN_HEADLESS', '1') == '1'
        self.browser_slow_mo = int(os.getenv('PLAN_BROWSER_SLOW_MO', '0') or 0)
        self.page_timeout_ms = int(os.getenv('PLAN_PAGE_TIMEOUT_MS', '25000'))
        self.max_combos = int(os.getenv('PLAN_MAX_COMBOS', '0') or 0)
        self.page_size_hint = max(1, int(os.getenv('PLAN_PAGE_SIZE_HINT', '10')))
        self.wait_after_click_ms = int(os.getenv('PLAN_WAIT_AFTER_CLICK_MS', '1000'))
        self.wait_after_nav_ms = int(os.getenv('PLAN_WAIT_AFTER_NAV_MS', '2000'))

        self.province_dict = {
            '11': '北京', '12': '天津', '13': '河北', '14': '山西', '15': '内蒙古',
            '21': '辽宁', '22': '吉林', '23': '黑龙江',
            '31': '上海', '32': '江苏', '33': '浙江', '34': '安徽', '35': '福建', '36': '江西', '37': '山东',
            '41': '河南', '42': '湖北', '43': '湖南',
            '44': '广东', '45': '广西', '46': '海南',
            '50': '重庆', '51': '四川', '52': '贵州', '53': '云南', '54': '西藏',
            '61': '陕西', '62': '甘肃', '63': '青海', '64': '宁夏', '65': '新疆',
            '71': '台湾', '81': '香港', '82': '澳门',
        }

    def now_str(self):
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

    def write_json_atomic(self, path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + '.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)

    def format_duration(self, seconds):
        seconds = max(0, float(seconds))
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f'{hours}小时{minutes}分{secs}秒'
        if minutes > 0:
            return f'{minutes}分{secs}秒'
        return f'{seconds:.2f}秒'

    def parse_years(self, years_input):
        if isinstance(years_input, list):
            return [str(y).strip() for y in years_input if str(y).strip()]
        if isinstance(years_input, str):
            raw = years_input.strip()
            if not raw:
                return []
            if '-' in raw:
                start, end = raw.split('-', 1)
                start = int(start.strip())
                end = int(end.strip())
                if start >= end:
                    return [str(y) for y in range(start, end - 1, -1)]
                return [str(y) for y in range(end, start - 1, -1)]
            if ',' in raw:
                return [y.strip() for y in raw.split(',') if y.strip()]
            return [raw]
        return years_input or []

    def load_default_school_ids(self):
        schools_file = Path(os.getenv('SCHOOL_DATA_FILE', 'data/schools.json'))
        if not schools_file.exists():
            print(f'⚠️  未找到 schools.json: {schools_file}')
            return []

        with open(schools_file, 'r', encoding='utf-8') as f:
            payload = json.load(f)

        if isinstance(payload, list):
            schools = payload
        elif isinstance(payload, dict):
            schools = payload.get('data', [])
            if not schools and payload.get('school_id'):
                schools = [payload]
        else:
            schools = []

        school_ids = []
        for item in schools:
            if isinstance(item, dict) and item.get('school_id'):
                school_ids.append(str(item['school_id']))

        def sort_key(x):
            return (0, int(x)) if x.isdigit() else (1, x)

        school_ids = sorted(dict.fromkeys(school_ids), key=sort_key)
        sample_count = int(os.getenv('SAMPLE_SCHOOLS', '0') or 0)
        if sample_count > 0:
            school_ids = school_ids[:sample_count]
        return school_ids

    def get_progress_file(self, year, province_id):
        custom = os.getenv('PLAN_PROGRESS_FILE', '').strip()
        if custom:
            return Path(custom)
        return self.progress_dir / f'{year}.{province_id}.json'

    def load_progress(self, year, province_id, target_school_ids):
        path = self.get_progress_file(year, province_id)
        base = {
            'year': str(year),
            'province_id': str(province_id),
            'target_school_ids': [str(x) for x in target_school_ids],
            'current_school_index': 0,
            'current_combo_index': 0,
            'current_page': 1,
            'updated_at': None,
            'last_error': None,
            'status': 'new',
        }
        if not path.exists():
            return base
        try:
            with open(path, 'r', encoding='utf-8') as f:
                progress = json.load(f)
        except Exception:
            return base

        saved_year = str(progress.get('year', ''))
        saved_province_id = str(progress.get('province_id', ''))
        saved_targets = [str(x) for x in progress.get('target_school_ids', [])]
        current_targets = [str(x) for x in target_school_ids]
        if saved_year != str(year) or saved_province_id != str(province_id) or saved_targets != current_targets:
            return base
        merged = base.copy()
        merged.update(progress)
        return merged

    def save_progress(
        self,
        year,
        province_id,
        target_school_ids,
        current_school_index,
        current_combo_index=0,
        current_page=1,
        last_error=None,
        status='running',
    ):
        payload = {
            'year': str(year),
            'province_id': str(province_id),
            'target_school_ids': [str(x) for x in target_school_ids],
            'current_school_index': int(current_school_index),
            'current_combo_index': int(current_combo_index),
            'current_page': int(current_page),
            'updated_at': self.now_str(),
            'last_error': last_error,
            'status': status,
        }
        self.write_json_atomic(self.get_progress_file(year, province_id), payload)

    def clear_progress(self, year, province_id):
        path = self.get_progress_file(year, province_id)
        if path.exists():
            path.unlink()

    def get_province_file_path(self, year, province_id):
        province_name = self.province_dict.get(str(province_id), f'省份{province_id}')
        return self.plan_data_dir / str(year) / f'{province_name}.json'

    def build_record_key(self, item):
        return (
            str(item.get('school_id') or ''),
            str(item.get('year') or ''),
            str(item.get('province_id') or ''),
            str(item.get('plan_type') or ''),
            str(item.get('batch') or ''),
            str(item.get('type') or ''),
            str(item.get('major') or ''),
            str(item.get('major_code') or ''),
            str(item.get('major_group') or ''),
            str(item.get('major_group_code') or ''),
            str(item.get('plan_number') or ''),
            str(item.get('years') or ''),
            str(item.get('tuition') or ''),
            str(item.get('note') or ''),
            str(item.get('subject_requirements') or ''),
            json.dumps(item.get('source_filter') or {}, ensure_ascii=False, sort_keys=True),
        )

    def load_province_records(self, year, province_id):
        path = self.get_province_file_path(year, province_id)
        province_name = self.province_dict.get(str(province_id), f'省份{province_id}')
        records = []
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    records = payload.get('data', []) or []
                elif isinstance(payload, list):
                    records = payload
            except Exception as e:
                print(f'⚠️  读取已有省份文件失败，改为重建: {path} - {e}')
                records = []
        existing_keys = {self.build_record_key(item) for item in records if isinstance(item, dict)}
        return {
            'year': str(year),
            'province_id': str(province_id),
            'province': province_name,
            'data': records,
            'existing_keys': existing_keys,
        }

    def save_province_records(self, year, province_id, payload):
        file_path = self.get_province_file_path(year, province_id)
        body = {
            'update_time': self.now_str(),
            'year': str(year),
            'province_id': str(province_id),
            'province': payload.get('province'),
            'count': len(payload.get('data', [])),
            'data': payload.get('data', []),
        }
        self.write_json_atomic(file_path, body)

    def should_stop(self, started_at):
        return (time.time() - started_at) >= self.run_deadline_seconds

    def merge_records(self, province_payload, new_records):
        added = 0
        for item in new_records:
            key = self.build_record_key(item)
            if key in province_payload['existing_keys']:
                continue
            province_payload['existing_keys'].add(key)
            province_payload['data'].append(item)
            added += 1
        return added

    def _clean_text(self, value):
        if value is None:
            return ''
        return ' '.join(str(value).replace('\u3000', ' ').split()).strip()

    def _start_playwright_browser(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError('未安装 Playwright。请先执行: pip install playwright && playwright install chromium') from e
        p = sync_playwright().start()
        browser = p.chromium.launch(headless=self.browser_headless, slow_mo=self.browser_slow_mo)
        return p, browser

    def school_rule_url(self, school_id):
        return f'https://www.gaokao.cn/school/{school_id}/sturule'

    def _page_wait(self, page, ms=None):
        page.wait_for_timeout(ms if ms is not None else self.wait_after_click_ms)

    def dismiss_page_noise(self, page):
        texts = ['我知道了', '知道了', '关闭', '稍后再说', '同意', '允许']
        for text in texts:
            try:
                clicked = page.evaluate(
                    """
                    (targetText) => {
                      const norm = s => (s || '').replace(/\s+/g, '').trim();
                      const visible = el => {
                        if (!el) return false;
                        const rect = el.getBoundingClientRect();
                        const st = window.getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                      };
                      const nodes = [...document.querySelectorAll('button,[role="button"],a,span,div')];
                      const hit = nodes.find(el => visible(el) && norm(el.innerText || el.textContent) === norm(targetText));
                      if (hit) {
                        hit.click();
                        return true;
                      }
                      return false;
                    }
                    """,
                    text,
                )
                if clicked:
                    self._page_wait(page, 500)
            except Exception:
                pass

    def goto_school_rule_page(self, page, school_id, year, province_name):
        url = self.school_rule_url(school_id)
        page.goto(url, wait_until='domcontentloaded', timeout=self.page_timeout_ms)

        try:
            page.wait_for_load_state('networkidle', timeout=10000)
        except Exception:
            pass

        self._page_wait(page, self.wait_after_nav_ms)
        self.dismiss_page_noise(page)
        page.wait_for_selector('body', state='attached', timeout=self.page_timeout_ms)

        print(f'   页面标题: {page.title()}')
        print(f'   页面地址: {page.url}')

        has_plan_block = page.evaluate(
            """
            () => {
              const norm = s => (s || '').replace(/\s+/g, '').trim();
              const blocks = [...document.querySelectorAll('div.bgwhite, div, section')];
              return blocks.some(b => norm(b.innerText || '').includes('招生计划'));
            }
            """
        )
        if not has_plan_block:
            raise RuntimeError('当前学校页面未发现“招生计划”模块')

        found_root = page.evaluate(
            """
            () => {
              const blocks = [...document.querySelectorAll('div.bgwhite')];
              return blocks.some(b => (b.innerText || '').includes('招生计划'));
            }
            """
        )
        if not found_root:
            raise RuntimeError('已检测到招生计划文本，但未找到对应区块 root')

        try:
            page.wait_for_selector('div.bgwhite .ant-select-selection, div.bgwhite table.tb-normal', state='attached', timeout=12000)
        except Exception:
            pass

        self.select_plan_filter_by_index(page, 0, province_name)
        self.select_plan_filter_by_index(page, 1, str(year))
        self._page_wait(page, 1200)
        self.wait_table_ready(page)

    def wait_table_ready(self, page):
        selectors = [
            'table.tb-normal tbody tr',
            'table.tb-normal',
            '.ant-select-selection',
        ]
        for sel in selectors:
            try:
                page.wait_for_selector(sel, state='attached', timeout=8000)
                self._page_wait(page, 500)
                return
            except Exception:
                continue
        raise RuntimeError('招生计划区块已存在，但表格/筛选控件未加载出来')

    def select_plan_filter_by_index(self, page, select_index, visible_text):
        visible_text = self._clean_text(visible_text)
        if not visible_text:
            return False
        clicked = page.evaluate(
            """
            ({selectIndex}) => {
              const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return false;
              const sels = [...root.querySelectorAll('.ant-select-selection[role="combobox"]')];
              const target = sels[selectIndex];
              if (!target) return false;
              target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
              target.click();
              return true;
            }
            """,
            {'selectIndex': int(select_index)},
        )
        if not clicked:
            return False
        self._page_wait(page, 500)
        picked = page.evaluate(
            """
            ({visibleText}) => {
              const norm = s => (s || '').replace(/\s+/g, '').trim();
              const visible = el => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const st = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
              };
              const dropdowns = [...document.querySelectorAll('.ant-select-dropdown')].filter(visible);
              for (const dd of dropdowns) {
                const options = [...dd.querySelectorAll('.ant-select-dropdown-menu-item, .ant-select-item-option, li')];
                const hit = options.find(el => norm(el.innerText || el.textContent) === norm(visibleText));
                if (hit) {
                  hit.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                  hit.click();
                  return true;
                }
              }
              return false;
            }
            """,
            {'visibleText': visible_text},
        )
        if picked:
            self._page_wait(page, 1200)
            return True
        try:
            page.get_by_text(visible_text, exact=True).last.click(timeout=1500)
            self._page_wait(page, 1200)
            return True
        except Exception:
            return False

    def get_current_filter_texts(self, page):
        data = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return {};
              const sels = [...root.querySelectorAll('.ant-select-selection-selected-value')];
              const read = i => sels[i] ? (sels[i].innerText || sels[i].textContent || '').trim() : '';
              return {province: read(0), year: read(1), type: read(2), batch: read(3)};
            }
            """
        )
        return data if isinstance(data, dict) else {}

    def collect_dropdown_options_by_index(self, page, select_index):
        opened = page.evaluate(
            """
            ({selectIndex}) => {
              const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return false;
              const sels = [...root.querySelectorAll('.ant-select-selection[role="combobox"]')];
              const target = sels[selectIndex];
              if (!target) return false;
              target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
              target.click();
              return true;
            }
            """,
            {'selectIndex': int(select_index)},
        )
        if not opened:
            return []
        self._page_wait(page, 500)
        options = page.evaluate(
            """
            () => {
              const norm = s => (s || '').replace(/\s+/g, ' ').trim();
              const visible = el => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                const st = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
              };
              const dropdown = [...document.querySelectorAll('.ant-select-dropdown')].find(visible);
              if (!dropdown) return [];
              const nodes = [...dropdown.querySelectorAll('.ant-select-dropdown-menu-item, .ant-select-item-option, li')];
              const out = [];
              const seen = new Set();
              for (const el of nodes) {
                const t = norm(el.innerText || el.textContent);
                if (!t || seen.has(t)) continue;
                seen.add(t);
                out.push(t);
              }
              return out;
            }
            """
        )
        try:
            page.locator('body').click(position={'x': 10, 'y': 10})
            self._page_wait(page, 300)
        except Exception:
            pass
        cleaned = []
        seen = set()
        for x in options or []:
            v = self._clean_text(x)
            if not v or v in seen:
                continue
            seen.add(v)
            cleaned.append(v)
        return cleaned

    def collect_major_groups(self, page):
        groups = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return [];
              const wrap = root.querySelector('.score-plan_groupList__1eMnJ');
              if (!wrap) return [];
              return [...wrap.querySelectorAll('.score-plan_item__1mtQ4')].map(el => (el.innerText || el.textContent || '').trim()).filter(Boolean);
            }
            """
        )
        cleaned = []
        seen = set()
        for x in groups or []:
            v = self._clean_text(x)
            if not v or v in seen:
                continue
            seen.add(v)
            cleaned.append(v)
        return cleaned

    def expand_major_groups_if_needed(self, page):
        try:
            expanded = page.evaluate(
                """
                () => {
                  const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
                  if (!root) return false;
                  const btn = root.querySelector('.score-plan_showMore__cYw23');
                  if (!btn) return false;
                  const t = (btn.innerText || '').trim();
                  if (t.includes('展开')) {
                    btn.click();
                    return true;
                  }
                  return false;
                }
                """
            )
            if expanded:
                self._page_wait(page, 800)
        except Exception:
            pass

    def click_major_group(self, page, text):
        text = self._clean_text(text)
        if not text:
            return False
        self.expand_major_groups_if_needed(page)
        clicked = page.evaluate(
            """
            ({targetText}) => {
              const norm = s => (s || '').replace(/\s+/g, '').trim();
              const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return false;
              const nodes = [...root.querySelectorAll('.score-plan_item__1mtQ4')];
              const hit = nodes.find(el => norm(el.innerText || el.textContent) === norm(targetText));
              if (!hit) return false;
              hit.click();
              return true;
            }
            """,
            {'targetText': text},
        )
        if clicked:
            self._page_wait(page, 1200)
            return True
        return False

    def collect_filter_dimensions(self, page):
        type_options = self.collect_dropdown_options_by_index(page, 2)
        batch_options = self.collect_dropdown_options_by_index(page, 3)
        self.expand_major_groups_if_needed(page)
        major_groups = self.collect_major_groups(page)
        return [
            {'key': 'type', 'mode': 'select', 'select_index': 2, 'options': [x for x in type_options if x not in {'全部'}], 'all_text': '全部'},
            {'key': 'batch', 'mode': 'select', 'select_index': 3, 'options': [x for x in batch_options if x not in {'全部'}], 'all_text': '全部'},
            {'key': 'major_group', 'mode': 'chips', 'options': [x for x in major_groups if x not in {'全部'}], 'all_text': '全部'},
        ]

    def build_filter_combos(self, dims):
        axes = []
        for dim in dims:
            values = [{'key': dim['key'], 'mode': dim['mode'], 'text': '__ALL__', 'all_text': dim.get('all_text'), 'select_index': dim.get('select_index')}]
            for opt in dim.get('options', []):
                values.append({'key': dim['key'], 'mode': dim['mode'], 'text': opt, 'all_text': dim.get('all_text'), 'select_index': dim.get('select_index')})
            axes.append(values)
        if not axes:
            return [{}]
        combos = []
        for prod in itertools.product(*axes):
            combo = {}
            for item in prod:
                combo[item['key']] = {'mode': item['mode'], 'text': item['text'], 'all_text': item.get('all_text'), 'select_index': item.get('select_index')}
            combos.append(combo)
        if self.max_combos > 0:
            combos = combos[:self.max_combos]
        if combos and {} not in combos:
            combos.insert(0, {})
        return combos or [{}]

    def combo_to_log_text(self, combo):
        if not combo:
            return '默认'
        parts = []
        for k in ['type', 'batch', 'major_group']:
            item = combo.get(k) or {}
            val = item.get('text')
            if val and val != '__ALL__':
                parts.append(f'{k}={val}')
        return ', '.join(parts) if parts else '默认'

    def apply_combo(self, page, combo):
        current = self.get_current_filter_texts(page)
        type_item = (combo or {}).get('type')
        if type_item:
            target = type_item.get('all_text') if type_item.get('text') == '__ALL__' else type_item.get('text')
            if target and current.get('type') != target:
                self.select_plan_filter_by_index(page, 2, target)
        current = self.get_current_filter_texts(page)
        batch_item = (combo or {}).get('batch')
        if batch_item:
            target = batch_item.get('all_text') if batch_item.get('text') == '__ALL__' else batch_item.get('text')
            if target and current.get('batch') != target:
                self.select_plan_filter_by_index(page, 3, target)
        group_item = (combo or {}).get('major_group')
        if group_item:
            target = group_item.get('all_text') if group_item.get('text') == '__ALL__' else group_item.get('text')
            if target:
                self.click_major_group(page, target)
        self._page_wait(page, 1000)
        self.wait_table_ready(page)

    def table_snapshot(self, page):
        data = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return {headers: [], rows: []};
              const table = root.querySelector('table.tb-normal');
              if (!table) return {headers: [], rows: []};
              const headers = [...table.querySelectorAll('thead td, thead th')].map(el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim());
              const rows = [...table.querySelectorAll('tbody tr')].map(tr => {
                const tds = [...tr.querySelectorAll('td')];
                return tds.map((td, idx) => {
                  const txt = (td.innerText || td.textContent || '').replace(/\s+/g, ' ').trim();
                  if (idx !== 0) return txt;
                  const h3 = td.querySelector('h3');
                  const pList = [...td.querySelectorAll('p')].map(x => (x.innerText || x.textContent || '').trim()).filter(Boolean);
                  const xk = td.querySelector('.score-plan_xkyq__16ULz');
                  return JSON.stringify({
                    major: h3 ? (h3.innerText || h3.textContent || '').trim() : '',
                    major_desc: pList.join('；'),
                    subject_requirements: xk ? (xk.innerText || xk.textContent || '').trim() : '',
                    raw: txt
                  });
                });
              }).filter(r => r.some(Boolean));
              return {headers, rows};
            }
            """
        )
        return data.get('headers') or [], data.get('rows') or []

    def normalize_table_rows(self, school_id, year, province_id, province_name, headers, rows, source_filter):
        result = []
        for row in rows:
            if len(row) < 3:
                continue
            major_cell_raw = row[0] if len(row) > 0 else ''
            plan_number = self._clean_text(row[1] if len(row) > 1 else '')
            fee_cell = self._clean_text(row[2] if len(row) > 2 else '')
            rate_cell = self._clean_text(row[3] if len(row) > 3 else '')
            major = ''
            major_desc = ''
            subject_requirements = source_filter.get('subject_requirements')
            try:
                major_obj = json.loads(major_cell_raw)
                if isinstance(major_obj, dict):
                    major = self._clean_text(major_obj.get('major'))
                    major_desc = self._clean_text(major_obj.get('major_desc'))
                    subject_requirements = self._clean_text(major_obj.get('subject_requirements')) or subject_requirements
            except Exception:
                major = self._clean_text(major_cell_raw)
            years_value = None
            tuition = None
            fee_parts = [self._clean_text(x) for x in fee_cell.split(' ') if self._clean_text(x)]
            if fee_parts:
                if len(fee_parts) >= 1:
                    years_value = fee_parts[0]
                if len(fee_parts) >= 2:
                    tuition = fee_parts[1]
            note_parts = []
            if major_desc:
                note_parts.append(major_desc)
            if rate_cell:
                note_parts.append(rate_cell)
            note = '；'.join(note_parts) if note_parts else None
            if not major and not plan_number:
                continue
            result.append({
                'school_id': str(school_id),
                'year': str(year),
                'province_id': str(province_id),
                'province': province_name,
                'plan_type': 'browser',
                'batch': source_filter.get('batch'),
                'type': source_filter.get('type'),
                'major': major,
                'major_code': None,
                'major_group': source_filter.get('major_group'),
                'major_group_code': None,
                'major_group_info': None,
                'level1_name': None,
                'level2_name': None,
                'level3_name': None,
                'plan_number': plan_number,
                'years': years_value,
                'tuition': tuition,
                'note': note,
                'subject_requirements': subject_requirements,
                'source': 'browser',
                'source_filter': dict(source_filter or {}),
                'raw_row': {
                    'major_raw': major_cell_raw,
                    'plan_number': plan_number,
                    'fee_cell': fee_cell,
                    'rate_cell': rate_cell,
                },
            })
        return result

    def current_page_no(self, page):
        try:
            n = page.evaluate(
                """
                () => {
                  const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
                  if (!root) return null;
                  const active = root.querySelector('.ant-pagination-item-active a, .ant-pagination-item-active');
                  if (!active) return null;
                  const t = (active.innerText || active.textContent || '').trim();
                  return /^\d+$/.test(t) ? parseInt(t, 10) : null;
                }
                """
            )
            return int(n) if n else None
        except Exception:
            return None

    def first_row_signature(self, page):
        _, rows = self.table_snapshot(page)
        if not rows:
            return ''
        return ' | '.join(rows[0][:4])

    def click_next_page(self, page):
        try:
            old_signature = self.first_row_signature(page)
            old_page_no = self.current_page_no(page) or 1
            clicked = page.evaluate(
                """
                () => {
                  const root = [...document.querySelectorAll('div.bgwhite')].find(b => (b.innerText || '').includes('招生计划'));
                  if (!root) return false;
                  const nextBtn = root.querySelector('.ant-pagination-next');
                  if (!nextBtn) return false;
                  const cls = String(nextBtn.className || '');
                  const disabled = nextBtn.getAttribute('aria-disabled') === 'true' || /disabled/.test(cls);
                  if (disabled) return false;
                  nextBtn.click();
                  return true;
                }
                """
            )
            if not clicked:
                return False
            for _ in range(8):
                self._page_wait(page, 500)
                new_signature = self.first_row_signature(page)
                new_page_no = self.current_page_no(page)
                if new_signature and new_signature != old_signature:
                    return True
                if new_page_no and new_page_no > old_page_no:
                    return True
            return True
        except Exception:
            return False

    def goto_page_number(self, page, target_page):
        if target_page <= 1:
            return True
        for _ in range(target_page - 1):
            ok = self.click_next_page(page)
            if not ok:
                return False
        return True

    def scrape_combo_pages(self, page, school_id, year, province_id, province_name, combo, start_page, started_at, school_ids, school_index, combo_index, province_payload):
        if start_page > 1:
            ok = self.goto_page_number(page, start_page)
            if not ok:
                return {'status': 'partial', 'current_combo_index': combo_index, 'current_page': start_page, 'added_records': 0}
        total_added = 0
        page_no = start_page
        seen_signatures = set()
        while True:
            if self.should_stop(started_at):
                return {'status': 'partial', 'current_combo_index': combo_index, 'current_page': page_no, 'added_records': total_added}
            headers, rows = self.table_snapshot(page)
            signature = self.first_row_signature(page)
            if signature:
                if signature in seen_signatures:
                    break
                seen_signatures.add(signature)
            source_filter = {'batch': None, 'type': None, 'major_group': None, 'subject_requirements': None, 'page': page_no}
            for k, v in (combo or {}).items():
                raw = (v or {}).get('text')
                source_filter[k] = None if raw in {None, '', '__ALL__'} else raw
            records = self.normalize_table_rows(school_id, year, province_id, province_name, headers, rows, source_filter)
            added = self.merge_records(province_payload, records)
            total_added += added
            self.save_progress(year=year, province_id=province_id, target_school_ids=school_ids, current_school_index=school_index, current_combo_index=combo_index, current_page=page_no + 1, last_error=None, status='running')
            if len(rows) < self.page_size_hint and page_no > 1:
                break
            moved = self.click_next_page(page)
            if not moved:
                break
            page_no += 1
            self.polite_sleep(0.5, 1.0)
        return {'status': 'done', 'current_combo_index': combo_index + 1, 'current_page': 1, 'added_records': total_added}

    def crawl_school_via_browser(self, page, school_id, year, province_id, province_name, province_payload, school_ids, school_index, started_at, resume_combo_index=0, resume_page=1):
        self.goto_school_rule_page(page, school_id, year, province_name)
        dims = self.collect_filter_dimensions(page)
        combos = self.build_filter_combos(dims)
        print(f'   学校 {school_id} 发现组合数: {len(combos)}')
        combo_start = max(0, int(resume_combo_index or 0))
        page_start = max(1, int(resume_page or 1))
        combo_added_total = 0
        for combo_index in range(combo_start, len(combos)):
            if self.should_stop(started_at):
                return {'status': 'partial', 'current_combo_index': combo_index, 'current_page': 1, 'added_records': combo_added_total}
            combo = combos[combo_index]
            self.goto_school_rule_page(page, school_id, year, province_name)
            self.apply_combo(page, combo)
            self._page_wait(page, 1000)
            start_page = page_start if combo_index == combo_start else 1
            print(f'      ↳ 组合 {combo_index + 1}/{len(combos)}: {self.combo_to_log_text(combo)}，起始页 {start_page}')
            outcome = self.scrape_combo_pages(page, school_id, year, province_id, province_name, combo, start_page, started_at, school_ids, school_index, combo_index, province_payload)
            combo_added_total += outcome.get('added_records', 0)
            if outcome.get('status') != 'done':
                return outcome
            if (combo_index + 1) % self.flush_combos == 0:
                self.save_province_records(year, province_id, province_payload)
                self.save_progress(year=year, province_id=province_id, target_school_ids=school_ids, current_school_index=school_index, current_combo_index=combo_index + 1, current_page=1, last_error=None, status='running')
                print(f'      ↻ 已阶段性保存，组合进度 {combo_index + 1}/{len(combos)}，当前 {len(province_payload["data"])} 条')
        return {'status': 'done', 'current_combo_index': 0, 'current_page': 1, 'added_records': combo_added_total}

    def crawl_one_year(self, year, school_ids=None, province_ids=None):
        school_ids = [str(x) for x in (school_ids or self.load_default_school_ids())]
        province_ids = [str(x) for x in (province_ids or list(self.province_dict.keys()))]
        if not school_ids:
            print('⚠️  没有可用学校ID')
            return {'year': str(year), 'status': 'skipped', 'saved_documents': 0, 'completed_schools': 0}
        if len(province_ids) != 1:
            raise ValueError('当前版本要求每次只传入一个省份')

        started_at = time.time()
        province_id = province_ids[0]
        province_name = self.province_dict.get(province_id, f'省份{province_id}')
        self.plan_data_dir.mkdir(parents=True, exist_ok=True)
        self.progress_dir.mkdir(parents=True, exist_ok=True)

        progress = self.load_progress(year, province_id, school_ids)
        start_index = int(progress.get('current_school_index', 0) or 0)
        start_combo_index = int(progress.get('current_combo_index', 0) or 0)
        start_page = int(progress.get('current_page', 1) or 1)
        province_payload = self.load_province_records(year, province_id)
        province_added_records = 0

        print(f"\n{'=' * 60}")
        print('启动招生计划爬虫')
        print(f'年份: {year}')
        print(f'省份: {province_name} ({province_id})')
        print(f'学校数: {len(school_ids)}')
        print('模式: browser_only')
        print(f'软截止: {self.format_duration(self.run_deadline_seconds)}')
        print(f'学校起始索引: {start_index + 1}/{len(school_ids)}')
        print(f"{'=' * 60}\n")

        playwright_ctx = None
        browser = None
        context = None
        page = None

        try:
            playwright_ctx, browser = self._start_playwright_browser()
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                viewport={'width': 1440, 'height': 960},
                locale='zh-CN',
            )
            page = context.new_page()
            page.set_default_timeout(self.page_timeout_ms)

            for school_index in range(start_index, len(school_ids)):
                if self.should_stop(started_at):
                    self.save_province_records(year, province_id, province_payload)
                    self.save_progress(year=year, province_id=province_id, target_school_ids=school_ids, current_school_index=school_index, current_combo_index=0, current_page=1, last_error='run deadline reached', status='partial')
                    print(f'⏸️ 接近 5 小时上限，已保存 {province_name} 和 progress，准备下一轮续跑')
                    return {'year': str(year), 'status': 'partial', 'saved_documents': 0, 'completed_schools': school_index}

                school_id = school_ids[school_index]
                school_resume_combo = start_combo_index if school_index == start_index else 0
                school_resume_page = start_page if school_index == start_index else 1
                print(f'[{school_index + 1}/{len(school_ids)}] 学校 {school_id}')

                try:
                    outcome = self.crawl_school_via_browser(page, school_id, str(year), province_id, province_name, province_payload, school_ids, school_index, started_at, school_resume_combo, school_resume_page)
                    province_added_records += outcome.get('added_records', 0)
                    if outcome.get('status') != 'done':
                        self.save_province_records(year, province_id, province_payload)
                        self.save_progress(year=year, province_id=province_id, target_school_ids=school_ids, current_school_index=school_index, current_combo_index=outcome.get('current_combo_index', school_resume_combo), current_page=outcome.get('current_page', school_resume_page), last_error='run deadline reached or page interrupted', status='partial')
                        print(f'⏸️ 学校 {school_id} 中断，已保存续跑位置')
                        return {'year': str(year), 'status': 'partial', 'saved_documents': 0, 'completed_schools': school_index}
                except Exception as e:
                    err = str(e)
                    if '当前学校页面未发现“招生计划”模块' in err:
                        print(f'ℹ️ 学校 {school_id} 页面无招生计划模块，跳过')
                        self.save_progress(year=year, province_id=province_id, target_school_ids=school_ids, current_school_index=school_index + 1, current_combo_index=0, current_page=1, last_error=None, status='running')
                        continue
                    self.save_province_records(year, province_id, province_payload)
                    self.save_progress(year=year, province_id=province_id, target_school_ids=school_ids, current_school_index=school_index, current_combo_index=school_resume_combo, current_page=school_resume_page, last_error=err, status='partial')
                    print(f'⚠️  浏览器抓取失败，学校 {school_id}: {e}')
                    return {'year': str(year), 'status': 'partial', 'saved_documents': 0, 'completed_schools': school_index}

                self.save_progress(year=year, province_id=province_id, target_school_ids=school_ids, current_school_index=school_index + 1, current_combo_index=0, current_page=1, last_error=None, status='running')
                if (school_index + 1) % self.flush_schools == 0:
                    self.save_province_records(year, province_id, province_payload)
                    print(f'   ↻ 已阶段性保存 {province_name}: 学校进度 {school_index + 1}/{len(school_ids)}，当前 {len(province_payload["data"])} 条')
                self.polite_sleep(0.4, 0.9)
        finally:
            try:
                if page is not None:
                    page.close()
            except Exception:
                pass
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright_ctx is not None:
                    playwright_ctx.stop()
            except Exception:
                pass

        self.save_province_records(year, province_id, province_payload)
        self.clear_progress(year, province_id)
        print(f'✅ 省份完成: {province_name}，本轮新增 {province_added_records} 条，累计 {len(province_payload["data"])} 条')
        return {'year': str(year), 'status': 'done', 'saved_documents': 1, 'completed_schools': len(school_ids)}

    def crawl(self, school_ids=None, years=None, province_ids=None):
        if years is None:
            years_env = os.getenv('PLAN_YEARS', '2025,2024,2023')
            years = self.parse_years(years_env)
        else:
            years = self.parse_years(years)
        if not years:
            print('⚠️  未提供有效年份')
            return {'year': '', 'status': 'skipped', 'saved_documents': 0, 'completed_schools': 0}
        result = None
        for year in years:
            result = self.crawl_one_year(year=str(year), school_ids=school_ids, province_ids=province_ids)
            if result.get('status') in {'partial', 'paused'}:
                return result
        return result or {'year': '', 'status': 'skipped', 'saved_documents': 0, 'completed_schools': 0}


if __name__ == '__main__':
    import sys
    years_arg = sys.argv[1] if len(sys.argv) > 1 else None
    crawler = PlanCrawler()
    crawler.crawl(years=years_arg)
