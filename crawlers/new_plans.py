# crawlers/new_plans.py
import itertools
import json
import os
import random
import time
from pathlib import Path


class NewPlanCrawler:
    def __init__(self):
        self.output_dir = Path(os.getenv("NEW_PLAN_DATA_DIR", "data/new_plans_by_school"))

        self.flush_schools = max(1, int(os.getenv("NEW_PLAN_FLUSH_SCHOOLS", "10")))
        self.flush_combos = max(1, int(os.getenv("NEW_PLAN_FLUSH_COMBOS", "10")))

        self.browser_headless = os.getenv("NEW_PLAN_HEADLESS", "0") == "1"
        self.browser_slow_mo = int(os.getenv("NEW_PLAN_BROWSER_SLOW_MO", "0") or 0)
        self.page_timeout_ms = int(os.getenv("NEW_PLAN_PAGE_TIMEOUT_MS", "30000"))
        self.wait_after_click_ms = int(os.getenv("NEW_PLAN_WAIT_AFTER_CLICK_MS", "800"))
        self.wait_after_nav_ms = int(os.getenv("NEW_PLAN_WAIT_AFTER_NAV_MS", "1800"))
        self.page_size_hint = max(1, int(os.getenv("NEW_PLAN_PAGE_SIZE_HINT", "10")))
        self.max_combos = int(os.getenv("NEW_PLAN_MAX_COMBOS", "0") or 0)

        self.browser_mode = os.getenv("NEW_PLAN_BROWSER_MODE", "chrome").strip().lower()
        self.cdp_url = os.getenv("NEW_PLAN_CDP_URL", "http://127.0.0.1:9222").strip()
        self.require_login = os.getenv("NEW_PLAN_REQUIRE_LOGIN", "1") == "1"
        self.login_wait_seconds = int(os.getenv("NEW_PLAN_LOGIN_WAIT_SECONDS", "300"))

        self.default_years = ["2025", "2024", "2023", "2022", "2021"]

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
        self.province_name_to_id = {v: k for k, v in self.province_dict.items()}

    # ----------------------------
    # basic utils
    # ----------------------------

    def now_str(self):
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

    def polite_sleep(self, min_delay=0.4, max_delay=0.9):
        time.sleep(random.uniform(min_delay, max_delay))

    def _clean_text(self, value):
        if value is None:
            return ""
        return " ".join(str(value).replace("\u3000", " ").split()).strip()

    def write_json_atomic(self, path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def compact_dict(self, data):
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                vv = self.compact_dict(v)
                if vv in (None, "", {}, []):
                    continue
                out[k] = vv
            return out
        if isinstance(data, list):
            arr = []
            for x in data:
                xx = self.compact_dict(x)
                if xx in (None, "", {}, []):
                    continue
                arr.append(xx)
            return arr
        return data

    def parse_years(self, years_input):
        if years_input is None:
            return self.default_years[:]

        if isinstance(years_input, list):
            arr = [str(y).strip() for y in years_input if str(y).strip()]
            return arr or self.default_years[:]

        if isinstance(years_input, str):
            raw = years_input.strip()
            if not raw:
                return self.default_years[:]
            if "-" in raw:
                start, end = raw.split("-", 1)
                start = int(start.strip())
                end = int(end.strip())
                if start >= end:
                    return [str(y) for y in range(start, end - 1, -1)]
                return [str(y) for y in range(end, start - 1, -1)]
            if "," in raw:
                arr = [x.strip() for x in raw.split(",") if x.strip()]
                return arr or self.default_years[:]
            return [raw]

        return self.default_years[:]

    def parse_province_ids(self, province_ids_input):
        all_ids = list(self.province_dict.keys())

        if province_ids_input is None:
            return all_ids

        if isinstance(province_ids_input, list):
            raw_items = [str(x).strip() for x in province_ids_input if str(x).strip()]
        elif isinstance(province_ids_input, str):
            raw = province_ids_input.strip()
            if not raw or raw.lower() in {"all", "全国"}:
                return all_ids
            raw_items = [x.strip() for x in raw.split(",") if x.strip()]
        else:
            return all_ids

        result = []
        seen = set()
        for item in raw_items:
            if item in self.province_dict:
                pid = item
            elif item in self.province_name_to_id:
                pid = self.province_name_to_id[item]
            else:
                continue
            if pid not in seen:
                seen.add(pid)
                result.append(pid)

        return result or all_ids

    def normalize_filter_options(self, options):
        cleaned = []
        seen = set()
        for x in options or []:
            v = self._clean_text(x)
            if not v or v in seen:
                continue
            seen.add(v)
            cleaned.append(v)

        specific = [x for x in cleaned if x != "全部"]
        if specific:
            return specific
        if "全部" in cleaned:
            return ["全部"]
        return []

    def load_default_school_ids(self):
        schools_file = Path(os.getenv("SCHOOL_DATA_FILE", "data/schools.json"))
        if not schools_file.exists():
            print(f"⚠️ 未找到 schools.json: {schools_file}")
            return []

        with open(schools_file, "r", encoding="utf-8") as f:
            payload = json.load(f)

        if isinstance(payload, list):
            schools = payload
        elif isinstance(payload, dict):
            schools = payload.get("data", [])
            if not schools and payload.get("school_id"):
                schools = [payload]
        else:
            schools = []

        school_ids = []
        for item in schools:
            if isinstance(item, dict) and item.get("school_id"):
                school_ids.append(str(item["school_id"]))

        def sort_key(x):
            return (0, int(x)) if x.isdigit() else (1, x)

        school_ids = sorted(dict.fromkeys(school_ids), key=sort_key)

        sample_count = int(os.getenv("SAMPLE_SCHOOLS", "0") or 0)
        if sample_count > 0:
            school_ids = school_ids[:sample_count]

        return school_ids

    # ----------------------------
    # output by school
    # ----------------------------

    def get_school_file_path(self, school_id):
        return self.output_dir / f"{school_id}.json"

    def build_record_key(self, item):
        return (
            str(item.get("school_id") or ""),
            str(item.get("year") or ""),
            str(item.get("province_id") or ""),
            str(item.get("type") or ""),
            str(item.get("batch") or ""),
            str(item.get("major_group") or ""),
            str(item.get("major_name") or ""),
            str(item.get("major_remark") or ""),
            str(item.get("subject_requirements") or ""),
            str(item.get("plan_number") or ""),
            str(item.get("education_years") or ""),
            str(item.get("tuition") or ""),
            str(item.get("admission_rate_text") or ""),
        )

    def load_school_records(self, school_id):
        path = self.get_school_file_path(school_id)
        records = []

        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    records = payload.get("data", []) or []
                elif isinstance(payload, list):
                    records = payload
            except Exception as e:
                print(f"⚠️ 读取已有学校文件失败，改为重建: {path} - {e}")
                records = []

        existing_keys = {self.build_record_key(item) for item in records if isinstance(item, dict)}
        return {
            "school_id": str(school_id),
            "data": records,
            "existing_keys": existing_keys,
        }

    def save_school_records(self, school_id, payload):
        file_path = self.get_school_file_path(school_id)
        records = payload.get("data", [])[:]

        def sort_key(x):
            year = str(x.get("year") or "")
            province_id = str(x.get("province_id") or "")
            type_name = str(x.get("type") or "")
            batch = str(x.get("batch") or "")
            group = str(x.get("major_group") or "")
            major = str(x.get("major_name") or "")
            year_key = -int(year) if year.isdigit() else 0
            return (year_key, province_id, type_name, batch, group, major)

        records.sort(key=sort_key)

        years = []
        provinces = []
        province_seen = set()

        for item in records:
            y = str(item.get("year") or "")
            if y and y not in years:
                years.append(y)

            pid = str(item.get("province_id") or "")
            pname = str(item.get("province") or "")
            pkey = (pid, pname)
            if pid and pkey not in province_seen:
                province_seen.add(pkey)
                provinces.append({
                    "province_id": pid,
                    "province": pname
                })

        body = {
            "update_time": self.now_str(),
            "school_id": str(school_id),
            "years": years,
            "provinces": provinces,
            "count": len(records),
            "data": records,
        }
        self.write_json_atomic(file_path, body)

    def merge_records(self, school_payload, new_records):
        added = 0
        for item in new_records:
            item = self.compact_dict(item)
            key = self.build_record_key(item)
            if key in school_payload["existing_keys"]:
                continue
            school_payload["existing_keys"].add(key)
            school_payload["data"].append(item)
            added += 1
        return added

    # ----------------------------
    # playwright
    # ----------------------------

    def _start_playwright_browser(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError(
                "未安装 Playwright。请先执行: pip install playwright && python -m playwright install chromium"
            ) from e

        p = sync_playwright().start()

        if self.browser_mode == "cdp":
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            return p, browser, True

        if self.browser_mode == "chrome":
            browser = p.chromium.launch(
                channel="chrome",
                headless=self.browser_headless,
                slow_mo=self.browser_slow_mo,
                args=["--disable-blink-features=AutomationControlled"],
            )
            return p, browser, False

        browser = p.chromium.launch(
            headless=self.browser_headless,
            slow_mo=self.browser_slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
        )
        return p, browser, False

    def new_page(self, context):
        page = context.new_page()
        page.set_default_timeout(self.page_timeout_ms)
        return page

    def school_rule_url(self, school_id):
        return f"https://www.gaokao.cn/school/{school_id}/sturule"

    def _page_wait(self, page, ms=None):
        page.wait_for_timeout(ms if ms is not None else self.wait_after_click_ms)

    def dismiss_page_noise(self, page):
        texts = ["我知道了", "知道了", "关闭", "稍后再说", "同意", "允许"]
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
                    self._page_wait(page, 300)
            except Exception:
                pass

    def close_login_popup(self, page):
        try:
            closed = page.evaluate(
                """
                () => {
                  const popup = document.querySelector('.login-popup_loginPopup__d_xjJ');
                  if (!popup) return false;
                  const closeBtn = popup.querySelector('.login-popup_closeBox__3eUq5');
                  if (!closeBtn) return false;
                  closeBtn.click();
                  return true;
                }
                """
            )
            if closed:
                self._page_wait(page, 300)
                return True
        except Exception:
            pass
        return False

    def has_login_entry(self, page):
        try:
            return bool(page.evaluate(
                """
                () => {
                  const norm = s => (s || '').replace(/\\s+/g, '').trim();
                  const nodes = [...document.querySelectorAll('span,div,a,button')];
                  return nodes.some(el => norm(el.innerText || el.textContent) === '登录/注册');
                }
                """
            ))
        except Exception:
            return False

    def is_logged_in(self, page):
        try:
            has_login = self.has_login_entry(page)
            has_popup = bool(page.evaluate(
                "() => !!document.querySelector('.login-popup_loginPopup__d_xjJ')"
            ))
            return (not has_login) and (not has_popup)
        except Exception:
            return False

    def wait_for_manual_login(self, page):
        if not self.require_login:
            return True

        self.close_login_popup(page)

        if self.is_logged_in(page):
            print("✅ 检测到已登录，继续抓取")
            return True

        print("⚠️ 当前需要登录后再抓取")
        print("请在打开的浏览器里手动点击“登录/注册”，扫码登录后不要关闭浏览器")
        print(f"最多等待 {self.login_wait_seconds} 秒...")

        start = time.time()
        while time.time() - start < self.login_wait_seconds:
            try:
                if self.is_logged_in(page):
                    print("✅ 登录成功，开始继续抓取")
                    self._page_wait(page, 800)
                    return True
            except Exception:
                pass
            time.sleep(1.0)

        raise RuntimeError("等待手动登录超时，请重新运行后登录")

    def ensure_overlay_cleared(self, page):
        self.dismiss_page_noise(page)

    def goto_school_rule_page(self, page, school_id):
        page.goto(self.school_rule_url(school_id), wait_until="domcontentloaded", timeout=self.page_timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        self._page_wait(page, self.wait_after_nav_ms)
        self.ensure_overlay_cleared(page)
        page.wait_for_selector("body", state="attached", timeout=self.page_timeout_ms)
        self.wait_for_manual_login(page)
        self.wait_plan_root(page)
        self.wait_table_ready(page)

    def wait_plan_root(self, page):
        for _ in range(20):
            self.ensure_overlay_cleared(page)
            ok = page.evaluate(
                """
                () => {
                  const root = [...document.querySelectorAll('div.bgwhite')]
                    .find(b => (b.innerText || '').includes('招生计划'));
                  return !!root;
                }
                """
            )
            if ok:
                return
            self._page_wait(page, 300)
        raise RuntimeError("未找到招生计划模块")

    def wait_table_ready(self, page):
        for _ in range(25):
            self.ensure_overlay_cleared(page)
            ok = page.evaluate(
                """
                () => {
                  const root = [...document.querySelectorAll('div.bgwhite')]
                    .find(b => (b.innerText || '').includes('招生计划'));
                  if (!root) return false;
                  const table = root.querySelector('table.tb-normal');
                  const selects = root.querySelectorAll('.ant-select-selection--single');
                  return !!table && selects.length >= 4;
                }
                """
            )
            if ok:
                return
            self._page_wait(page, 300)
        raise RuntimeError("招生计划表格或筛选控件未加载完成")

    def get_current_filter_texts(self, page):
        data = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return {};
              const sels = [...root.querySelectorAll('.ant-select-selection-selected-value')];
              const read = i => sels[i] ? (sels[i].innerText || sels[i].textContent || '').trim() : '';
              return {
                province: read(0),
                year: read(1),
                type: read(2),
                batch: read(3)
              };
            }
            """
        )
        return data if isinstance(data, dict) else {}

    def get_selected_text_by_index(self, page, select_index):
        text = page.evaluate(
            """
            ({selectIndex}) => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return '';
              const vals = [...root.querySelectorAll('.ant-select-selection-selected-value')];
              const node = vals[selectIndex];
              return node ? (node.innerText || node.textContent || '').trim() : '';
            }
            """,
            {"selectIndex": int(select_index)},
        )
        return self._clean_text(text)

    def get_dropdown_id_by_index(self, page, select_index):
        dropdown_id = page.evaluate(
            """
            ({selectIndex}) => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return '';
              const sels = [...root.querySelectorAll('.ant-select-selection--single')];
              const target = sels[selectIndex];
              if (!target) return '';
              return target.getAttribute('aria-controls') || '';
            }
            """,
            {"selectIndex": int(select_index)},
        )
        return self._clean_text(dropdown_id)

    def open_select_by_index(self, page, select_index):
        self.ensure_overlay_cleared(page)
        clicked = page.evaluate(
            """
            ({selectIndex}) => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return false;
              const sels = [...root.querySelectorAll('.ant-select-selection--single')];
              const target = sels[selectIndex];
              if (!target) return false;
              target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
              target.click();
              return true;
            }
            """,
            {"selectIndex": int(select_index)},
        )
        if clicked:
            self._page_wait(page, 300)
        return bool(clicked)

    def close_any_open_dropdown(self, page):
        try:
            page.locator("body").click(position={"x": 8, "y": 8})
            self._page_wait(page, 150)
        except Exception:
            pass

    def collect_dropdown_options_by_index(self, page, select_index):
        current = self.get_selected_text_by_index(page, select_index)
        opened = self.open_select_by_index(page, select_index)
        if not opened:
            return [current] if current else []

        dropdown_id = self.get_dropdown_id_by_index(page, select_index)

        options = page.evaluate(
            """
            ({dropdownId}) => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
              const root = document.getElementById(dropdownId);
              if (!root) return [];
              const nodes = [...root.querySelectorAll('li[role="option"], .ant-select-dropdown-menu-item, .ant-select-item-option')];
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
            """,
            {"dropdownId": dropdown_id},
        )

        self.close_any_open_dropdown(page)
        options = self.normalize_filter_options(options)
        if not options and current:
            return [current]
        return options

    def wait_selected_value(self, page, select_index, expected_text, timeout_ms=5000):
        start = time.time()
        expected_text = self._clean_text(expected_text)
        while (time.time() - start) * 1000 < timeout_ms:
            current = self.get_selected_text_by_index(page, select_index)
            if current == expected_text:
                return True
            self._page_wait(page, 150)
        return False

    def safe_select_dropdown_value(self, page, select_index, visible_text):
        visible_text = self._clean_text(visible_text)
        if not visible_text:
            return False

        current = self.get_selected_text_by_index(page, select_index)
        if current == visible_text:
            return True

        for _ in range(3):
            self.ensure_overlay_cleared(page)

            opened = self.open_select_by_index(page, select_index)
            if not opened:
                current = self.get_selected_text_by_index(page, select_index)
                if current == visible_text:
                    return True
                continue

            dropdown_id = self.get_dropdown_id_by_index(page, select_index)
            if not dropdown_id:
                self.close_any_open_dropdown(page)
                continue

            picked = page.evaluate(
                """
                ({dropdownId, visibleText}) => {
                  const norm = s => (s || '').replace(/\\s+/g, '').trim();
                  const root = document.getElementById(dropdownId);
                  if (!root) return false;
                  const nodes = [...root.querySelectorAll('li[role="option"], .ant-select-dropdown-menu-item, .ant-select-item-option')];
                  const hit = nodes.find(el => norm(el.innerText || el.textContent) === norm(visibleText));
                  if (!hit) return false;
                  hit.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                  hit.click();
                  return true;
                }
                """,
                {"dropdownId": dropdown_id, "visibleText": visible_text},
            )

            if not picked:
                self.close_any_open_dropdown(page)
                current = self.get_selected_text_by_index(page, select_index)
                if current == visible_text:
                    return True
                continue

            ok = self.wait_selected_value(page, select_index, visible_text, timeout_ms=5000)
            self._page_wait(page, 500)
            if ok:
                return True

        return self.get_selected_text_by_index(page, select_index) == visible_text

    def collect_major_groups(self, page):
        groups = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return [];
              const wrap = root.querySelector('.score-plan_groupList__1eMnJ');
              if (!wrap) return [];
              return [...wrap.querySelectorAll('.score-plan_item__1mtQ4')]
                .map(el => (el.innerText || el.textContent || '').trim())
                .filter(Boolean);
            }
            """
        )
        return self.normalize_filter_options(groups)

    def expand_major_groups_if_needed(self, page):
        try:
            expanded = page.evaluate(
                """
                () => {
                  const root = [...document.querySelectorAll('div.bgwhite')]
                    .find(b => (b.innerText || '').includes('招生计划'));
                  if (!root) return false;
                  const btn = root.querySelector('.score-plan_showMore__cYw23');
                  if (!btn) return false;
                  const txt = (btn.innerText || btn.textContent || '').trim();
                  if (txt.includes('展开')) {
                    btn.click();
                    return true;
                  }
                  return false;
                }
                """
            )
            if expanded:
                self._page_wait(page, 500)
        except Exception:
            pass

    def get_current_major_group(self, page):
        text = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return '';
              const active = root.querySelector('.score-plan_item__1mtQ4.score-plan_active__2pQaY');
              return active ? (active.innerText || active.textContent || '').trim() : '';
            }
            """
        )
        return self._clean_text(text)

    def click_major_group(self, page, text):
        text = self._clean_text(text)
        if not text:
            return False

        current = self.get_current_major_group(page)
        if current == text:
            return True

        self.ensure_overlay_cleared(page)
        self.expand_major_groups_if_needed(page)

        clicked = page.evaluate(
            """
            ({targetText}) => {
              const norm = s => (s || '').replace(/\\s+/g, '').trim();
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return false;
              const nodes = [...root.querySelectorAll('.score-plan_item__1mtQ4')];
              const hit = nodes.find(el => norm(el.innerText || el.textContent) === norm(targetText));
              if (!hit) return false;
              hit.click();
              return true;
            }
            """,
            {"targetText": text},
        )
        if not clicked:
            return False

        for _ in range(12):
            current = self.get_current_major_group(page)
            if current == text:
                self._page_wait(page, 400)
                return True
            self._page_wait(page, 150)
        return False

    def set_base_filters(self, page, province_name, year):
        self.ensure_overlay_cleared(page)
        ok1 = self.safe_select_dropdown_value(page, 0, province_name)
        ok2 = self.safe_select_dropdown_value(page, 1, str(year))
        self.wait_table_ready(page)
        current = self.get_current_filter_texts(page)
        return current.get("province") == province_name and current.get("year") == str(year) and ok1 and ok2

    def collect_available_provinces(self, page):
        current = self.get_current_filter_texts(page)
        options = self.collect_dropdown_options_by_index(page, 0)
        if not options and current.get("province"):
            return [self._clean_text(current.get("province"))]
        return options

    def collect_available_years(self, page):
        current = self.get_current_filter_texts(page)
        options = self.collect_dropdown_options_by_index(page, 1)
        if not options and current.get("year"):
            return [self._clean_text(current.get("year"))]
        return options

    def collect_filter_dimensions(self, page):
        current = self.get_current_filter_texts(page)

        type_options = self.collect_dropdown_options_by_index(page, 2)
        batch_options = self.collect_dropdown_options_by_index(page, 3)

        if not type_options and current.get("type"):
            type_options = [self._clean_text(current.get("type"))]
        if not batch_options and current.get("batch"):
            batch_options = [self._clean_text(current.get("batch"))]

        self.expand_major_groups_if_needed(page)
        major_group_options = self.collect_major_groups(page)

        dims = []

        type_options = [x for x in type_options if x]
        batch_options = [x for x in batch_options if x]
        major_group_options = [x for x in major_group_options if x]

        if len(type_options) > 1:
            dims.append({"key": "type", "mode": "select", "select_index": 2, "options": type_options})

        if len(batch_options) > 1:
            dims.append({"key": "batch", "mode": "select", "select_index": 3, "options": batch_options})

        if len(major_group_options) > 1:
            dims.append({"key": "major_group", "mode": "chips", "options": major_group_options})

        return dims

    def build_filter_combos(self, dims):
        axes = []
        for dim in dims:
            values = []
            for opt in dim.get("options", []):
                values.append({
                    "key": dim["key"],
                    "mode": dim["mode"],
                    "text": opt,
                    "select_index": dim.get("select_index"),
                })
            if values:
                axes.append(values)

        if not axes:
            return [{}]

        combos = []
        for prod in itertools.product(*axes):
            combo = {}
            for item in prod:
                combo[item["key"]] = {
                    "mode": item["mode"],
                    "text": item["text"],
                    "select_index": item.get("select_index"),
                }
            combos.append(combo)

        if self.max_combos > 0:
            combos = combos[:self.max_combos]

        return combos or [{}]

    def combo_to_log_text(self, combo):
        if not combo:
            return "默认"
        parts = []
        for k in ["type", "batch", "major_group"]:
            item = combo.get(k) or {}
            val = item.get("text")
            if val:
                parts.append(f"{k}={val}")
        return ", ".join(parts) if parts else "默认"

    def apply_combo(self, page, combo):
        self.ensure_overlay_cleared(page)
        current = self.get_current_filter_texts(page)

        type_item = (combo or {}).get("type")
        if type_item:
            target = self._clean_text(type_item.get("text"))
            if target and current.get("type") != target:
                if not self.safe_select_dropdown_value(page, 2, target):
                    return False

        current = self.get_current_filter_texts(page)
        batch_item = (combo or {}).get("batch")
        if batch_item:
            target = self._clean_text(batch_item.get("text"))
            if target and current.get("batch") != target:
                if not self.safe_select_dropdown_value(page, 3, target):
                    return False

        group_item = (combo or {}).get("major_group")
        if group_item:
            target = self._clean_text(group_item.get("text"))
            current_group = self.get_current_major_group(page)
            if target and current_group != target:
                if not self.click_major_group(page, target):
                    return False

        self.wait_table_ready(page)
        return True

    def table_snapshot(self, page):
        data = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return {rows: []};

              const table = root.querySelector('table.tb-normal');
              if (!table) return {rows: []};

              const rows = [...table.querySelectorAll('tbody tr')].map(tr => {
                const tds = [...tr.querySelectorAll('td')];
                if (tds.length < 3) return null;

                const majorTd = tds[0];
                const h3 = majorTd.querySelector('h3');
                const pList = [...majorTd.querySelectorAll('p')]
                  .map(x => (x.innerText || x.textContent || '').trim())
                  .filter(Boolean);
                const xk = majorTd.querySelector('.score-plan_xkyq__16ULz');

                const feeTd = tds[2];
                const feePs = [...feeTd.querySelectorAll('p')]
                  .map(x => (x.innerText || x.textContent || '').trim())
                  .filter(Boolean);

                const rateTd = tds[3] || null;
                const rateText = rateTd ? (rateTd.innerText || rateTd.textContent || '').replace(/\\s+/g, ' ').trim() : '';

                return {
                  major_name: h3 ? (h3.innerText || h3.textContent || '').trim() : '',
                  major_remark: pList.join('；'),
                  subject_requirements: xk ? (xk.innerText || xk.textContent || '').trim() : '',
                  plan_number: (tds[1].innerText || tds[1].textContent || '').replace(/\\s+/g, ' ').trim(),
                  education_years: feePs[0] || '',
                  tuition: feePs[1] || '',
                  admission_rate_text: rateText || ''
                };
              }).filter(Boolean);

              return {rows};
            }
            """
        )
        return data.get("rows") or []

    def first_row_signature(self, page):
        rows = self.table_snapshot(page)
        if not rows:
            return ""
        first = rows[0]
        return " | ".join([
            self._clean_text(first.get("major_name")),
            self._clean_text(first.get("plan_number")),
            self._clean_text(first.get("education_years")),
            self._clean_text(first.get("tuition")),
        ])

    def current_page_no(self, page):
        n = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
              if (!root) return null;
              const active = root.querySelector('.ant-pagination-item-active a, .ant-pagination-item-active');
              if (!active) return 1;
              const t = (active.innerText || active.textContent || '').trim();
              return /^\\d+$/.test(t) ? parseInt(t, 10) : 1;
            }
            """
        )
        return int(n) if n else 1

    def click_next_page(self, page):
        self.ensure_overlay_cleared(page)
        old_signature = self.first_row_signature(page)
        old_page = self.current_page_no(page)

        clicked = page.evaluate(
            """
            () => {
              const root = [...document.querySelectorAll('div.bgwhite')]
                .find(b => (b.innerText || '').includes('招生计划'));
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

        for _ in range(15):
            self._page_wait(page, 250)
            new_signature = self.first_row_signature(page)
            new_page = self.current_page_no(page)
            if new_page > old_page:
                return True
            if old_signature and new_signature and new_signature != old_signature:
                return True
        return True

    def normalize_table_rows(self, school_id, year, province_id, province_name, rows, current_filters):
        result = []

        for row in rows:
            major_name = self._clean_text(row.get("major_name"))
            major_remark = self._clean_text(row.get("major_remark"))
            subject_requirements = self._clean_text(row.get("subject_requirements"))
            plan_number = self._clean_text(row.get("plan_number"))
            education_years = self._clean_text(row.get("education_years"))
            tuition = self._clean_text(row.get("tuition"))
            rate_text = self._clean_text(row.get("admission_rate_text"))

            if not major_name and not plan_number:
                continue

            item = {
                "school_id": str(school_id),
                "year": str(year),
                "province_id": str(province_id),
                "province": province_name,
                "type": self._clean_text(current_filters.get("type")),
                "batch": self._clean_text(current_filters.get("batch")),
                "major_group": self._clean_text(current_filters.get("major_group")),
                "major_name": major_name,
                "major_remark": major_remark,
                "subject_requirements": subject_requirements,
                "plan_number": plan_number,
                "education_years": education_years,
                "tuition": tuition,
            }

            if rate_text and rate_text != "录取率":
                item["admission_rate_text"] = rate_text

            result.append(self.compact_dict(item))

        return result

    def scrape_current_combo(self, page, school_id, year, province_id, province_name, school_payload):
        total_added = 0
        seen_signatures = set()

        while True:
            self.ensure_overlay_cleared(page)

            rows = self.table_snapshot(page)
            signature = self.first_row_signature(page)

            if signature:
                if signature in seen_signatures:
                    break
                seen_signatures.add(signature)

            current_filters = self.get_current_filter_texts(page)
            current_group = self.get_current_major_group(page)
            if current_group:
                current_filters["major_group"] = current_group

            records = self.normalize_table_rows(
                school_id=school_id,
                year=year,
                province_id=province_id,
                province_name=province_name,
                rows=rows,
                current_filters=current_filters,
            )
            total_added += self.merge_records(school_payload, records)

            page_no = self.current_page_no(page)
            if len(rows) < self.page_size_hint and page_no > 1:
                break

            moved = self.click_next_page(page)
            if not moved:
                break

            self.polite_sleep()

        return total_added

    def crawl_one_province_year(self, page, school_id, year, province_id, province_name, school_payload):
        ok = self.set_base_filters(page, province_name, year)
        if not ok:
            print(f"   ⚠️ 省份 {province_name} / 年份 {year} 选择失败，跳过")
            return 0

        dims = self.collect_filter_dimensions(page)
        combos = self.build_filter_combos(dims)

        print(f"      年份 {year} 组合数: {len(combos)}")

        year_added = 0
        for combo_index, combo in enumerate(combos, 1):
            ok = self.set_base_filters(page, province_name, year)
            if not ok:
                print(f"         ⚠️ 基础筛选重置失败: {province_name} / {year}")
                continue

            applied = self.apply_combo(page, combo)
            if not applied:
                print(f"         ⚠️ 组合应用失败: {self.combo_to_log_text(combo)}")
                continue

            print(f"         ↳ 组合 {combo_index}/{len(combos)}: {self.combo_to_log_text(combo)}")

            added = self.scrape_current_combo(
                page=page,
                school_id=school_id,
                year=year,
                province_id=province_id,
                province_name=province_name,
                school_payload=school_payload,
            )
            year_added += added

            if combo_index % self.flush_combos == 0:
                self.save_school_records(school_id, school_payload)
                print(f"         ↻ 已阶段性保存学校 {school_id}，当前累计 {len(school_payload['data'])} 条")

        return year_added

    def recover_page_if_needed(self, context, page, school_id):
        if page is not None:
            try:
                if not page.is_closed():
                    return page
            except Exception:
                pass
        page = self.new_page(context)
        self.goto_school_rule_page(page, school_id)
        return page

    def crawl_school_national(self, context, page, school_id, years, target_province_ids):
        school_payload = self.load_school_records(school_id)
        school_added = 0

        page = self.recover_page_if_needed(context, page, school_id)
        self.goto_school_rule_page(page, school_id)

        available_province_names = self.collect_available_provinces(page)
        target_province_names = [
            self.province_dict[pid]
            for pid in target_province_ids
            if self.province_dict.get(pid) in available_province_names
        ]

        if not target_province_names:
            print(f"   ℹ️ 学校 {school_id} 没有命中的省份选项")
            self.save_school_records(school_id, school_payload)
            return page, 0, len(school_payload["data"])

        for province_name in target_province_names:
            province_id = self.province_name_to_id[province_name]
            print(f"   省份 {province_name} ({province_id})")

            try:
                page = self.recover_page_if_needed(context, page, school_id)
                selected = self.safe_select_dropdown_value(page, 0, province_name)
                self.wait_table_ready(page)
                if not selected:
                    print(f"      ⚠️ 省份 {province_name} 选择失败，跳过")
                    continue

                available_years = self.collect_available_years(page)
                target_years = [y for y in years if y in available_years]

                if not target_years:
                    print(f"      ℹ️ 省份 {province_name} 没有命中的年份")
                    continue

                for year in target_years:
                    retried = False
                    while True:
                        try:
                            page = self.recover_page_if_needed(context, page, school_id)
                            school_added += self.crawl_one_province_year(
                                page=page,
                                school_id=school_id,
                                year=str(year),
                                province_id=province_id,
                                province_name=province_name,
                                school_payload=school_payload,
                            )
                            self.save_school_records(school_id, school_payload)
                            break
                        except Exception as e:
                            msg = str(e)
                            if (not retried) and ("closed" in msg.lower()):
                                retried = True
                                print(f"      ⚠️ 页面被关闭，重开后重试: {province_name} / {year}")
                                page = self.new_page(context)
                                self.goto_school_rule_page(page, school_id)
                                continue
                            self.save_school_records(school_id, school_payload)
                            print(f"      ⚠️ 省份 {province_name} 年份 {year} 失败: {e}")
                            break

            except Exception as e:
                print(f"      ⚠️ 省份 {province_name} 处理失败: {e}")
                self.save_school_records(school_id, school_payload)
                continue

        self.save_school_records(school_id, school_payload)
        return page, school_added, len(school_payload["data"])

    def crawl(self, school_ids=None, years=None, province_ids=None):
        school_ids = [str(x) for x in (school_ids or self.load_default_school_ids())]
        years = self.parse_years(years)
        province_ids = self.parse_province_ids(province_ids)

        if not school_ids:
            print("⚠️ 没有可用学校ID")
            return {"status": "skipped", "completed_schools": 0}

        self.output_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'=' * 60}")
        print("启动 new_plans 爬虫")
        print(f"年份: {','.join(years)}")
        print(f"省份数: {len(province_ids)}")
        print(f"学校数: {len(school_ids)}")
        print(f"浏览器模式: {self.browser_mode}")
        print(f"{'=' * 60}\n")

        playwright_ctx = None
        browser = None
        context = None
        page = None
        use_existing_context = False
        finished = 0

        try:
            playwright_ctx, browser, use_existing_context = self._start_playwright_browser()

            if use_existing_context and browser.contexts:
                context = browser.contexts[0]
            else:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 960},
                    locale="zh-CN",
                )

            page = self.new_page(context)

            for idx, school_id in enumerate(school_ids, 1):
                print(f"[{idx}/{len(school_ids)}] 学校 {school_id}")

                try:
                    page, added, total = self.crawl_school_national(
                        context=context,
                        page=page,
                        school_id=school_id,
                        years=years,
                        target_province_ids=province_ids,
                    )
                    print(f"   ✅ 学校 {school_id} 完成，本轮新增 {added} 条，累计 {total} 条")
                    finished += 1
                except Exception as e:
                    print(f"   ⚠️ 学校 {school_id} 失败: {e}")
                    try:
                        if page is None or page.is_closed():
                            page = self.new_page(context)
                    except Exception:
                        page = self.new_page(context)

                if idx % self.flush_schools == 0:
                    print(f"   ↻ 已处理学校 {idx}/{len(school_ids)}")

                self.polite_sleep()

        finally:
            try:
                if page is not None and not page.is_closed():
                    page.close()
            except Exception:
                pass
            try:
                if context is not None and not use_existing_context:
                    context.close()
            except Exception:
                pass
            try:
                if browser is not None and not use_existing_context:
                    browser.close()
            except Exception:
                pass
            try:
                if playwright_ctx is not None:
                    playwright_ctx.stop()
            except Exception:
                pass

        return {"status": "done", "completed_schools": finished}


if __name__ == "__main__":
    import sys

    years_arg = sys.argv[1] if len(sys.argv) > 1 else None
    provinces_arg = sys.argv[2] if len(sys.argv) > 2 else None

    crawler = NewPlanCrawler()
    crawler.crawl(years=years_arg, province_ids=provinces_arg)