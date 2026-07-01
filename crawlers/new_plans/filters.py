import itertools
from .utils import clean_text, normalize_filter_options


class FilterMixin:
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
        return clean_text(text)

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

    def _collect_visible_open_options(self, page):
        return page.evaluate(
            """
() => {
const norm = s => (s || '').replace(/\s+/g, ' ').trim();
const visible = el => {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  const st = window.getComputedStyle(el);
  return rect.width > 0 && rect.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
};

const optionSelectors = [
  '.score-plan_proSelectBox__3TLK5 .score-plan_item__1mtQ4',
  'li[role="option"]',
  '.ant-select-dropdown-menu-item',
  '.ant-select-item-option'
];

const nodes = [...document.querySelectorAll(optionSelectors.join(','))]
  .filter(el => visible(el));

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

    def collect_dropdown_options_by_index(self, page, select_index):
        current = self.get_selected_text_by_index(page, select_index)
        opened = self.open_select_by_index(page, select_index)
        if not opened:
            return [current] if current else []

        options = self._collect_visible_open_options(page)
        self.close_any_open_dropdown(page)

        if int(select_index) == 0:
            options = [clean_text(x) for x in options if clean_text(x)]
            dedup = []
            seen = set()
            for x in options:
                if x in seen:
                    continue
                seen.add(x)
                dedup.append(x)
            return dedup or ([current] if current else [])

        options = normalize_filter_options(options)
        if not options and current:
            return [current]
        return options

    def wait_selected_value(self, page, select_index, expected_text, timeout_ms=5000):
        import time
        start = time.time()
        expected_text = clean_text(expected_text)
        while (time.time() - start) * 1000 < timeout_ms:
            current = self.get_selected_text_by_index(page, select_index)
            if current == expected_text:
                return True
            self._page_wait(page, 150)
        return False

    def safe_select_dropdown_value(self, page, select_index, visible_text):
        visible_text = clean_text(visible_text)
        if not visible_text:
            return False

        current = self.get_selected_text_by_index(page, select_index)
        if current == visible_text:
            return True

        for _ in range(4):
            self.ensure_overlay_cleared(page)
            opened = self.open_select_by_index(page, select_index)
            if not opened:
                current = self.get_selected_text_by_index(page, select_index)
                if current == visible_text:
                    return True
                continue

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
const selectors = [
  '.score-plan_proSelectBox__3TLK5 .score-plan_item__1mtQ4',
  'li[role="option"]',
  '.ant-select-dropdown-menu-item',
  '.ant-select-item-option'
];
const nodes = [...document.querySelectorAll(selectors.join(','))].filter(el => visible(el));
const hit = nodes.find(el => norm(el.innerText || el.textContent) === norm(visibleText));
if (!hit) return false;
hit.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
hit.click();
return true;
}
""",
                {"visibleText": visible_text},
            )

            self.close_any_open_dropdown(page)
            if not picked:
                current = self.get_selected_text_by_index(page, select_index)
                if current == visible_text:
                    return True
                continue

            ok = self.wait_selected_value(page, select_index, visible_text, timeout_ms=5000)
            self._page_wait(page, 500)
            if ok:
                return True

        return self.get_selected_text_by_index(page, select_index) == visible_text

    def collect_major_groups(self, page, keep_all=True):
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
        groups = [clean_text(x) for x in groups if clean_text(x)]
        dedup = []
        seen = set()
        for x in groups:
            if x in seen:
                continue
            seen.add(x)
            dedup.append(x)
        if keep_all:
            return dedup
        return normalize_filter_options(dedup)

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
        return clean_text(text)

    def click_major_group(self, page, text):
        text = clean_text(text)
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
const norm = s => (s || '').replace(/\s+/g, '').trim();
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

        for _ in range(20):
            current = self.get_current_major_group(page)
            if current == text:
                self._page_wait(page, 600)
                return True
            self._page_wait(page, 200)
        return False

    def apply_combo(self, page, combo):
        self.ensure_overlay_cleared(page)
        current = self.get_current_filter_texts(page)

        type_item = (combo or {}).get("type")
        if type_item:
            target = clean_text(type_item.get("text"))
            if target and current.get("type") != target:
                if not self.safe_select_dropdown_value(page, 2, target):
                    return False
                self.wait_table_ready(page)

        current = self.get_current_filter_texts(page)
        batch_item = (combo or {}).get("batch")
        if batch_item:
            target = clean_text(batch_item.get("text"))
            if target and current.get("batch") != target:
                if not self.safe_select_dropdown_value(page, 3, target):
                    return False
                self.wait_table_ready(page)

        group_item = (combo or {}).get("major_group")
        if group_item:
            target = clean_text(group_item.get("text"))
            current_group = self.get_current_major_group(page)
            if target and current_group != target:
                if not self.click_major_group(page, target):
                    return False

        self.wait_table_ready(page)
        return True

    def ensure_combo_applied(self, page, combo):
        current = self.get_current_filter_texts(page)

        type_item = (combo or {}).get("type")
        if type_item:
            target = clean_text(type_item.get("text"))
            if target and clean_text(current.get("type")) != target:
                return False

        batch_item = (combo or {}).get("batch")
        if batch_item:
            target = clean_text(batch_item.get("text"))
            if target and clean_text(current.get("batch")) != target:
                return False

        group_item = (combo or {}).get("major_group")
        if group_item:
            target = clean_text(group_item.get("text"))
            current_group = self.get_current_major_group(page)
            if target and current_group != target:
                return False

        return True
