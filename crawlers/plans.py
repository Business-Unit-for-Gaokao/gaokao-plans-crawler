# crawlers/plans.py
import itertools
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import BaseCrawler


class PlanCrawler(BaseCrawler):
    def __init__(self):
        super().__init__()
        self._first_logged = False

        self.progress_dir = Path(os.getenv('PLAN_PROGRESS_DIR', 'data/plans_progress'))
        self.plan_data_dir = Path(os.getenv('PLAN_DATA_DIR', 'data/plans'))

        self.run_deadline_seconds = int(os.getenv('PLAN_RUN_DEADLINE_SECONDS', '17400'))
        self.flush_schools = max(1, int(os.getenv('PLAN_FLUSH_SCHOOLS', '25')))

        self.use_browser = os.getenv('PLAN_USE_BROWSER', '1') == '1'
        self.use_static_fallback = os.getenv('PLAN_USE_STATIC_FALLBACK', '1') == '1'
        self.browser_headless = os.getenv('PLAN_HEADLESS', '1') == '1'
        self.browser_slow_mo = int(os.getenv('PLAN_BROWSER_SLOW_MO', '0') or 0)
        self.page_timeout_ms = int(os.getenv('PLAN_PAGE_TIMEOUT_MS', '20000'))
        self.max_combos = int(os.getenv('PLAN_MAX_COMBOS', '0') or 0)
        self.flush_combos = max(1, int(os.getenv('PLAN_FLUSH_COMBOS', '10')))
        self.page_size_hint = max(1, int(os.getenv('PLAN_PAGE_SIZE_HINT', '10')))
        self.wait_after_click_ms = int(os.getenv('PLAN_WAIT_AFTER_CLICK_MS', '900'))
        self.wait_after_nav_ms = int(os.getenv('PLAN_WAIT_AFTER_NAV_MS', '1800'))

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

        self.filter_specs = [
            {'key': 'batch', 'labels': ['批次']},
            {'key': 'type', 'labels': ['科类', '类型', '招生类型']},
            {'key': 'major_group', 'labels': ['专业组', '分组', '组别']},
            {'key': 'subject_requirements', 'labels': ['选科', '科目要求']},
        ]

    # ----------------------------
    # basic utils
    # ----------------------------

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

    # ----------------------------
    # old static api fallback
    # ----------------------------

    def get_plan_data_static(self, school_id, year, province_id):
        url = f'https://static-data.gaokao.cn/www/2.0/schoolspecialplan/{school_id}/{year}/{province_id}.json'
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get('code') == '0000' and 'data' in result:
                    return result['data']
            elif response.status_code == 404:
                return 'no_data'
        except Exception:
            pass
        return None

    def extract_records_from_static(self, school_id, year, province_id, province_name, data):
        records = []
        if not data or data == 'no_data' or not isinstance(data, dict):
            return records

        for plan_type, plan_info in data.items():
            if not isinstance(plan_info, dict):
                continue
            items = plan_info.get('item', [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                records.append({
                    'school_id': str(school_id),
                    'year': str(year),
                    'province_id': str(province_id),
                    'province': province_name,
                    'plan_type': plan_type,
                    'batch': item.get('local_batch_name'),
                    'type': item.get('type'),
                    'major': item.get('sp_name') or item.get('spname'),
                    'major_code': item.get('spcode'),
                    'major_group': item.get('sg_name'),
                    'major_group_code': item.get('sg_code'),
                    'major_group_info': item.get('sg_info'),
                    'level1_name': item.get('level1_name'),
                    'level2_name': item.get('level2_name'),
                    'level3_name': item.get('level3_name'),
                    'plan_number': item.get('num') or item.get('plan_num'),
                    'years': item.get('length') or item.get('years'),
                    'tuition': item.get('tuition'),
                    'note': item.get('note') or item.get('remark'),
                    'subject_requirements': None,
                    'source': 'static',
                    'source_filter': {},
                })
        return records

    # ----------------------------
    # merge / normalize
    # ----------------------------

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

    def _header_value(self, row_map, *keys):
        for key in keys:
            for k, v in row_map.items():
                if key in k:
                    return v
        return None

    def normalize_table_rows(self, school_id, year, province_id, province_name, headers, rows, source_filter):
        result = []
        norm_headers = [self._clean_text(h).replace('（', '(').replace('）', ')') for h in headers]

        for row in rows:
            cells = [self._clean_text(x) for x in row]
            if not any(cells):
                continue

            row_map = {}
            for idx, header in enumerate(norm_headers):
                row_map[header] = cells[idx] if idx < len(cells) else ''

            major = (
                self._header_value(row_map, '专业名称')
                or self._header_value(row_map, '专业')
                or self._header_value(row_map, '招生专业')
            )
            major_code = self._header_value(row_map, '专业代码', '代码')
            batch = self._header_value(row_map, '批次') or source_filter.get('batch')
            type_name = (
                self._header_value(row_map, '科类')
                or self._header_value(row_map, '类型')
                or self._header_value(row_map, '招生类型')
                or source_filter.get('type')
            )
            major_group = self._header_value(row_map, '专业组') or source_filter.get('major_group')
            plan_number = self._header_value(row_map, '招生计划', '计划数', '计划')
            years_value = self._header_value(row_map, '学制', '修业年限')
            tuition = self._header_value(row_map, '学费', '收费标准')
            note = self._header_value(row_map, '备注', '说明', '要求')
            subject_requirements = self._header_value(row_map, '选科', '科目要求') or source_filter.get('subject_requirements')

            if not major and not plan_number:
                continue

            result.append({
                'school_id': str(school_id),
                'year': str(year),
                'province_id': str(province_id),
                'province': province_name,
                'plan_type': 'browser',
                'batch': batch,
                'type': type_name,
                'major': major,
                'major_code': major_code,
                'major_group': major_group,
                'major_group_code': self._header_value(row_map, '专业组代码', '组代码'),
                'major_group_info': self._header_value(row_map, '专业组备注', '组备注'),
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
                'raw_row': row_map,
            })
        return result

    # ----------------------------
    # playwright helpers
    # ----------------------------

    def _start_playwright_browser(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError(
                '未安装 Playwright。请先执行: pip install playwright && playwright install chromium'
            ) from e

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
                      const norm = s => (s || '').replace(/\\s+/g, '').trim();
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
        self._page_wait(page, self.wait_after_nav_ms)
        self.dismiss_page_noise(page)

        self.try_click_text(page, '招生计划')
        self._page_wait(page, 800)

        self.try_click_text(page, str(year))
        self._page_wait(page, 800)

        self.try_click_text(page, province_name)
        self._page_wait(page, 1000)

        self.dismiss_page_noise(page)
        self.wait_table_ready(page)

    def wait_table_ready(self, page):
        candidates = [
            'table',
            '[role="table"]',
            'tbody tr',
            '.ant-table',
            '.el-table',
        ]
        for sel in candidates:
            try:
                page.wait_for_selector(sel, timeout=4000)
                return
            except Exception:
                continue
        self._page_wait(page, 1500)

    def try_click_text(self, page, text, scope_labels=None):
        text = self._clean_text(text)
        if not text:
            return False

        labels = scope_labels or []
        try:
            clicked = page.evaluate(
                """
                ({targetText, labels}) => {
                  const norm = s => (s || '').replace(/\\s+/g, '').trim();
                  const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const st = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                  };
                  const isClickable = el => {
                    if (!el) return false;
                    const tag = (el.tagName || '').toLowerCase();
                    const st = window.getComputedStyle(el);
                    return ['button', 'a', 'label', 'summary'].includes(tag)
                      || el.getAttribute('role') === 'button'
                      || st.cursor === 'pointer'
                      || typeof el.onclick === 'function'
                      || /btn|button|tab|item|option|radio|check|tag|chip/i.test(el.className || '');
                  };
                  const labelSet = (labels || []).map(norm).filter(Boolean);
                  const nodes = [...document.querySelectorAll('button,[role="button"],a,label,li,span,div')].filter(visible);
                  const exact = el => norm(el.innerText || el.textContent) === norm(targetText);

                  const findInsideContainer = () => {
                    if (!labelSet.length) return null;
                    const labelNodes = [...document.querySelectorAll('body *')].filter(el => {
                      if (!visible(el)) return false;
                      const t = norm(el.innerText || el.textContent);
                      return labelSet.includes(t) && el.children.length === 0;
                    });
                    for (const labelNode of labelNodes) {
                      let container = labelNode.parentElement;
                      for (let i = 0; i < 5 && container; i++, container = container.parentElement) {
                        const hit = [...container.querySelectorAll('button,[role="button"],a,label,li,span,div')]
                          .find(el => visible(el) && isClickable(el) && exact(el));
                        if (hit) return hit;
                      }
                    }
                    return null;
                  };

                  let hit = findInsideContainer();
                  if (!hit) {
                    hit = nodes.find(el => isClickable(el) && exact(el));
                  }
                  if (!hit) {
                    hit = nodes.find(el => exact(el));
                  }
                  if (!hit) return false;

                  hit.click();
                  return true;
                }
                """,
                {'targetText': text, 'labels': labels},
            )
            if clicked:
                self._page_wait(page)
                return True
        except Exception:
            pass

        try:
            page.get_by_text(text, exact=True).first.click(timeout=1200)
            self._page_wait(page)
            return True
        except Exception:
            return False

    def collect_filter_options(self, page, labels):
        try:
            options = page.evaluate(
                """
                (labels) => {
                  const norm = s => (s || '').replace(/\\s+/g, '').trim();
                  const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const st = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                  };
                  const isOption = el => {
                    if (!visible(el)) return false;
                    const tag = (el.tagName || '').toLowerCase();
                    const t = norm(el.innerText || el.textContent);
                    if (!t || t.length > 20) return false;
                    if (/^(展开|收起|重置|确定|搜索|清空|上一页|下一页|尾页|首页|共\\d+页|跳至|GO)$/i.test(t)) return false;
                    const st = window.getComputedStyle(el);
                    return ['button', 'a', 'label', 'li', 'span', 'div'].includes(tag)
                      && (
                        ['button', 'a', 'label'].includes(tag)
                        || el.getAttribute('role') === 'button'
                        || st.cursor === 'pointer'
                        || /btn|button|tab|item|option|radio|check|tag|chip/i.test(el.className || '')
                      );
                  };

                  const labelSet = (labels || []).map(norm).filter(Boolean);
                  const labelNodes = [...document.querySelectorAll('body *')].filter(el => {
                    if (!visible(el)) return false;
                    const t = norm(el.innerText || el.textContent);
                    return labelSet.includes(t) && el.children.length === 0;
                  });

                  const pickFromContainer = (container) => {
                    const arr = [];
                    const seen = new Set();
                    for (const el of container.querySelectorAll('button,[role="button"],a,label,li,span,div')) {
                      if (!isOption(el)) continue;
                      const t = norm(el.innerText || el.textContent);
                      if (!t || labelSet.includes(t)) continue;
                      if (seen.has(t)) continue;
                      seen.add(t);
                      arr.push(t);
                    }
                    return arr;
                  };

                  for (const labelNode of labelNodes) {
                    let container = labelNode.parentElement;
                    for (let i = 0; i < 5 && container; i++, container = container.parentElement) {
                      const opts = pickFromContainer(container);
                      if (opts.length >= 2 && opts.length <= 40) {
                        return opts;
                      }
                    }
                  }
                  return [];
                }
                """,
                labels,
            )
            if not isinstance(options, list):
                return []
            cleaned = []
            seen = set()
            for x in options:
                v = self._clean_text(x)
                if not v:
                    continue
                if v in seen:
                    continue
                seen.add(v)
                cleaned.append(v)
            return cleaned
        except Exception:
            return []

    def collect_filter_dimensions(self, page):
        dims = []
        for spec in self.filter_specs:
            opts = self.collect_filter_options(page, spec['labels'])
            all_text = None
            specific = []
            for x in opts:
                if x in {'全部', '不限', '全部批次', '全部类型', '全部专业组'} and not all_text:
                    all_text = x
                else:
                    specific.append(x)
            dims.append({
                'key': spec['key'],
                'labels': spec['labels'],
                'all_text': all_text,
                'options': specific,
            })
        return dims

    def build_filter_combos(self, dims):
        axes = []
        for dim in dims:
            values = [{'text': '__ALL__', 'labels': dim['labels'], 'key': dim['key'], 'all_text': dim['all_text']}]
            for opt in dim['options']:
                values.append({'text': opt, 'labels': dim['labels'], 'key': dim['key'], 'all_text': dim['all_text']})
            axes.append(values)

        if not axes:
            return [{}]

        combos = []
        for prod in itertools.product(*axes):
            combo = {}
            has_specific = False
            for item in prod:
                combo[item['key']] = {
                    'text': item['text'],
                    'labels': item['labels'],
                    'all_text': item['all_text'],
                }
                if item['text'] != '__ALL__':
                    has_specific = True
            combos.append(combo)

        combos = [self.combo_to_plain_dict(c) for c in combos]

        if self.max_combos > 0:
            combos = combos[:self.max_combos]
        if not combos:
            combos = [{}]
        if combos and {} not in combos:
            combos.insert(0, {})
        return combos

    def combo_to_plain_dict(self, combo):
        plain = {}
        for k, v in (combo or {}).items():
            plain[k] = {
                'text': v.get('text'),
                'labels': v.get('labels') or [],
                'all_text': v.get('all_text'),
            }
        return plain

    def combo_to_log_text(self, combo):
        if not combo:
            return '默认'
        parts = []
        for k in ['batch', 'type', 'major_group', 'subject_requirements']:
            item = combo.get(k)
            if not item:
                continue
            val = item.get('text')
            if val and val != '__ALL__':
                parts.append(f'{k}={val}')
        return ', '.join(parts) if parts else '默认'

    def apply_combo(self, page, combo):
        if not combo:
            return

        for key in ['batch', 'type', 'major_group', 'subject_requirements']:
            item = combo.get(key)
            if not item:
                continue
            text = item.get('text')
            labels = item.get('labels') or []
            all_text = item.get('all_text')

            if text == '__ALL__':
                if all_text:
                    self.try_click_text(page, all_text, scope_labels=labels)
                continue

            self.try_click_text(page, text, scope_labels=labels)
            self._page_wait(page, 1000)

        self.wait_table_ready(page)

    def table_snapshot(self, page):
        try:
            data = page.evaluate(
                """
                () => {
                  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                  const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const st = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                  };

                  const tables = [...document.querySelectorAll('table,[role="table"]')].filter(visible);
                  let best = null;
                  let bestRows = -1;

                  for (const table of tables) {
                    const headers = [...table.querySelectorAll('thead th')].map(th => norm(th.innerText || th.textContent)).filter(Boolean);
                    const rows = [...table.querySelectorAll('tbody tr')].map(tr =>
                      [...tr.querySelectorAll('td,th')].map(td => norm(td.innerText || td.textContent))
                    ).filter(r => r.some(Boolean));
                    if (rows.length > bestRows) {
                      best = {headers, rows};
                      bestRows = rows.length;
                    }
                  }

                  if (best && best.rows.length) {
                    return best;
                  }

                  const rowLike = [...document.querySelectorAll('tbody tr,.ant-table-row,.el-table__row,[role="row"]')].filter(visible);
                  if (rowLike.length) {
                    const rows = rowLike.map(tr =>
                      [...tr.querySelectorAll('td,th,[role="cell"],[role="gridcell"]')].map(td => norm(td.innerText || td.textContent))
                    ).filter(r => r.some(Boolean));
                    return {headers: [], rows};
                  }

                  return {headers: [], rows: []};
                }
                """
            )
            headers = data.get('headers') or []
            rows = data.get('rows') or []
            return headers, rows
        except Exception:
            return [], []

    def current_page_no(self, page):
        try:
            n = page.evaluate(
                """
                () => {
                  const norm = s => (s || '').replace(/\\s+/g, '').trim();
                  const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const st = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                  };
                  const active = [...document.querySelectorAll('.active,.is-active,.ant-pagination-item-active,.el-pager li.active,[aria-current="page"]')].find(visible);
                  if (!active) return null;
                  const t = norm(active.innerText || active.textContent);
                  const m = t.match(/^\\d+$/);
                  return m ? parseInt(m[0], 10) : null;
                }
                """
            )
            return int(n) if n else None
        except Exception:
            return None

    def goto_page_number(self, page, target_page):
        if target_page <= 1:
            return True

        for _ in range(target_page - 1):
            ok = self.click_next_page(page)
            if not ok:
                return False
        return True

    def click_next_page(self, page):
        try:
            old_signature = self.first_row_signature(page)
            clicked = page.evaluate(
                """
                () => {
                  const norm = s => (s || '').replace(/\\s+/g, '').trim();
                  const visible = el => {
                    if (!el) return false;
                    const rect = el.getBoundingClientRect();
                    const st = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                  };
                  const disabled = el => {
                    const cls = String(el.className || '');
                    return el.hasAttribute('disabled')
                      || el.getAttribute('aria-disabled') === 'true'
                      || /disabled|is-disabled|ant-pagination-disabled/.test(cls);
                  };
                  const candidates = [...document.querySelectorAll('button,a,li,span,div')].filter(visible);

                  const nextText = ['下一页', '下页', '›', '>', '下一页>'];
                  let hit = candidates.find(el => nextText.includes(norm(el.innerText || el.textContent)) && !disabled(el));
                  if (!hit) {
                    hit = candidates.find(el =>
                      !disabled(el)
                      && (/next/i.test(String(el.className || '')) || el.getAttribute('aria-label') === 'Next page')
                    );
                  }
                  if (!hit) return false;
                  hit.click();
                  return true;
                }
                """
            )
            if not clicked:
                return False

            self._page_wait(page, 1200)

            for _ in range(6):
                new_signature = self.first_row_signature(page)
                new_page_no = self.current_page_no(page)
                if new_signature and new_signature != old_signature:
                    return True
                if new_page_no:
                    return True
                self._page_wait(page, 400)
            return True
        except Exception:
            return False

    def first_row_signature(self, page):
        headers, rows = self.table_snapshot(page)
        if not rows:
            return ''
        first = rows[0]
        return ' | '.join(first[:6])

    def scrape_combo_pages(
        self,
        page,
        school_id,
        year,
        province_id,
        province_name,
        combo,
        start_page,
        started_at,
        school_ids,
        school_index,
        combo_index,
        province_payload,
    ):
        if start_page > 1:
            ok = self.goto_page_number(page, start_page)
            if not ok:
                return {
                    'status': 'partial',
                    'current_combo_index': combo_index,
                    'current_page': start_page,
                    'added_records': 0,
                }

        total_added = 0
        page_no = start_page
        seen_signatures = set()

        while True:
            if self.should_stop(started_at):
                return {
                    'status': 'partial',
                    'current_combo_index': combo_index,
                    'current_page': page_no,
                    'added_records': total_added,
                }

            headers, rows = self.table_snapshot(page)
            signature = self.first_row_signature(page)
            if signature:
                if signature in seen_signatures:
                    break
                seen_signatures.add(signature)

            source_filter = {
                'batch': None,
                'type': None,
                'major_group': None,
                'subject_requirements': None,
                'page': page_no,
            }
            for k, v in (combo or {}).items():
                raw = (v or {}).get('text')
                source_filter[k] = None if raw in {None, '', '__ALL__'} else raw

            records = self.normalize_table_rows(
                school_id=school_id,
                year=year,
                province_id=province_id,
                province_name=province_name,
                headers=headers,
                rows=rows,
                source_filter=source_filter,
            )
            added = self.merge_records(province_payload, records)
            total_added += added

            self.save_progress(
                year=year,
                province_id=province_id,
                target_school_ids=school_ids,
                current_school_index=school_index,
                current_combo_index=combo_index,
                current_page=page_no + 1,
                last_error=None,
                status='running',
            )

            if len(rows) < self.page_size_hint and page_no > 1:
                break

            moved = self.click_next_page(page)
            if not moved:
                break

            page_no += 1
            self.polite_sleep(0.5, 1.0)

        return {
            'status': 'done',
            'current_combo_index': combo_index + 1,
            'current_page': 1,
            'added_records': total_added,
        }

    def crawl_school_via_browser(
        self,
        page,
        school_id,
        year,
        province_id,
        province_name,
        province_payload,
        school_ids,
        school_index,
        started_at,
        resume_combo_index=0,
        resume_page=1,
    ):
        self.goto_school_rule_page(page, school_id, year, province_name)
        dims = self.collect_filter_dimensions(page)
        combos = self.build_filter_combos(dims)

        print(f'   学校 {school_id} 发现组合数: {len(combos)}')

        combo_start = max(0, int(resume_combo_index or 0))
        page_start = max(1, int(resume_page or 1))
        combo_added_total = 0

        for combo_index in range(combo_start, len(combos)):
            if self.should_stop(started_at):
                return {
                    'status': 'partial',
                    'current_combo_index': combo_index,
                    'current_page': 1,
                    'added_records': combo_added_total,
                }

            combo = combos[combo_index]
            self.goto_school_rule_page(page, school_id, year, province_name)
            self.apply_combo(page, combo)
            self._page_wait(page, 1000)

            start_page = page_start if combo_index == combo_start else 1

            print(f'      ↳ 组合 {combo_index + 1}/{len(combos)}: {self.combo_to_log_text(combo)}，起始页 {start_page}')

            outcome = self.scrape_combo_pages(
                page=page,
                school_id=school_id,
                year=year,
                province_id=province_id,
                province_name=province_name,
                combo=combo,
                start_page=start_page,
                started_at=started_at,
                school_ids=school_ids,
                school_index=school_index,
                combo_index=combo_index,
                province_payload=province_payload,
            )
            combo_added_total += outcome.get('added_records', 0)

            if outcome.get('status') != 'done':
                return outcome

            if (combo_index + 1) % self.flush_combos == 0:
                self.save_province_records(year, province_id, province_payload)
                self.save_progress(
                    year=year,
                    province_id=province_id,
                    target_school_ids=school_ids,
                    current_school_index=school_index,
                    current_combo_index=combo_index + 1,
                    current_page=1,
                    last_error=None,
                    status='running',
                )
                print(f'      ↻ 已阶段性保存，组合进度 {combo_index + 1}/{len(combos)}，当前 {len(province_payload["data"])} 条')

        return {
            'status': 'done',
            'current_combo_index': 0,
            'current_page': 1,
            'added_records': combo_added_total,
        }

    # ----------------------------
    # main crawl
    # ----------------------------

    def crawl_one_year(self, year, school_ids=None, province_ids=None):
        school_ids = [str(x) for x in (school_ids or self.load_default_school_ids())]
        province_ids = [str(x) for x in (province_ids or list(self.province_dict.keys()))]

        if not school_ids:
            print('⚠️  没有可用学校ID')
            return {
                'year': str(year),
                'status': 'skipped',
                'saved_documents': 0,
                'completed_schools': 0,
            }

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
        print(f'模式: {"browser_first" if self.use_browser else "static_only"}')
        print(f'静态兜底: {"开启" if self.use_static_fallback else "关闭"}')
        print(f'软截止: {self.format_duration(self.run_deadline_seconds)}')
        print(f'学校起始索引: {start_index + 1}/{len(school_ids)}')
        print(f"{'=' * 60}\n")

        playwright_ctx = None
        browser = None
        context = None
        page = None

        try:
            if self.use_browser:
                playwright_ctx, browser = self._start_playwright_browser()
                context = browser.new_context(
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/124.0.0.0 Safari/537.36'
                    ),
                    viewport={'width': 1440, 'height': 960},
                    locale='zh-CN',
                )
                page = context.new_page()
                page.set_default_timeout(self.page_timeout_ms)

            for school_index in range(start_index, len(school_ids)):
                if self.should_stop(started_at):
                    self.save_province_records(year, province_id, province_payload)
                    self.save_progress(
                        year=year,
                        province_id=province_id,
                        target_school_ids=school_ids,
                        current_school_index=school_index,
                        current_combo_index=0,
                        current_page=1,
                        last_error='run deadline reached',
                        status='partial',
                    )
                    print(f'⏸️ 接近 5 小时上限，已保存 {province_name} 和 progress，准备下一轮续跑')
                    return {
                        'year': str(year),
                        'status': 'partial',
                        'saved_documents': 0,
                        'completed_schools': school_index,
                    }

                school_id = school_ids[school_index]
                school_resume_combo = start_combo_index if school_index == start_index else 0
                school_resume_page = start_page if school_index == start_index else 1

                print(f'[{school_index + 1}/{len(school_ids)}] 学校 {school_id}')

                school_done = False
                school_added = 0

                if self.use_browser and page is not None:
                    try:
                        outcome = self.crawl_school_via_browser(
                            page=page,
                            school_id=school_id,
                            year=str(year),
                            province_id=province_id,
                            province_name=province_name,
                            province_payload=province_payload,
                            school_ids=school_ids,
                            school_index=school_index,
                            started_at=started_at,
                            resume_combo_index=school_resume_combo,
                            resume_page=school_resume_page,
                        )
                        school_added += outcome.get('added_records', 0)

                        if outcome.get('status') != 'done':
                            self.save_province_records(year, province_id, province_payload)
                            self.save_progress(
                                year=year,
                                province_id=province_id,
                                target_school_ids=school_ids,
                                current_school_index=school_index,
                                current_combo_index=outcome.get('current_combo_index', school_resume_combo),
                                current_page=outcome.get('current_page', school_resume_page),
                                last_error='run deadline reached or page interrupted',
                                status='partial',
                            )
                            print(f'⏸️ 学校 {school_id} 中断，已保存续跑位置')
                            return {
                                'year': str(year),
                                'status': 'partial',
                                'saved_documents': 0,
                                'completed_schools': school_index,
                            }

                        school_done = True
                    except Exception as e:
                        print(f'⚠️  浏览器抓取失败，学校 {school_id}: {e}')
                        school_done = False

                if not school_done and self.use_static_fallback:
                    data = self.get_plan_data_static(school_id, year, province_id)
                    if not self._first_logged and data and data != 'no_data' and isinstance(data, dict):
                        print(f"\n{'─' * 50}")
                        print('首次静态响应数据结构:')
                        print(f"{'─' * 50}")
                        print(f'data类型: {type(data).__name__}')
                        print(f'data包含键: {list(data.keys())}')
                        print(f"{'─' * 50}\n")
                        self._first_logged = True

                    if data and data != 'no_data' and isinstance(data, dict):
                        records = self.extract_records_from_static(school_id, year, province_id, province_name, data)
                        school_added += self.merge_records(province_payload, records)
                    school_done = True

                province_added_records += school_added

                self.save_progress(
                    year=year,
                    province_id=province_id,
                    target_school_ids=school_ids,
                    current_school_index=school_index + 1,
                    current_combo_index=0,
                    current_page=1,
                    last_error=None,
                    status='running',
                )

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
        return {
            'year': str(year),
            'status': 'done',
            'saved_documents': 1,
            'completed_schools': len(school_ids),
        }

    def crawl(self, school_ids=None, years=None, province_ids=None):
        if years is None:
            years_env = os.getenv('PLAN_YEARS', '2025,2024,2023')
            years = self.parse_years(years_env)
        else:
            years = self.parse_years(years)

        if not years:
            print('⚠️  未提供有效年份')
            return {
                'year': '',
                'status': 'skipped',
                'saved_documents': 0,
                'completed_schools': 0,
            }

        result = None
        for year in years:
            result = self.crawl_one_year(year=str(year), school_ids=school_ids, province_ids=province_ids)
            if result.get('status') in {'partial', 'paused'}:
                return result
        return result or {
            'year': '',
            'status': 'skipped',
            'saved_documents': 0,
            'completed_schools': 0,
        }


if __name__ == '__main__':
    import sys

    years_arg = sys.argv[1] if len(sys.argv) > 1 else None
    crawler = PlanCrawler()
    crawler.crawl(years=years_arg)