from .browser import BrowserMixin
from .config import NewPlanConfig, PROVINCE_DICT, PROVINCE_NAME_TO_ID
from .filters import FilterMixin
from .parser import PlanTableParser
from .storage import SchoolPlanStore
from .utils import clean_text, load_default_school_ids, parse_province_ids, parse_years, polite_sleep


class NewPlanCrawler(BrowserMixin, FilterMixin):
    def __init__(self):
        self.config = NewPlanConfig()
        self.province_dict = PROVINCE_DICT
        self.province_name_to_id = PROVINCE_NAME_TO_ID
        self.store = SchoolPlanStore(self.config.output_dir)
        self.parser = PlanTableParser(page_size_hint=self.config.page_size_hint)

    def click_next_page(self, page):
        self.ensure_overlay_cleared(page)
        old_signature = self.parser.first_row_signature(page)
        old_page = self.parser.current_page_no(page)

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
            new_signature = self.parser.first_row_signature(page)
            new_page = self.parser.current_page_no(page)
            if new_page > old_page:
                return True
            if old_signature and new_signature and new_signature != old_signature:
                return True
        return True

    def scrape_current_combo(self, page, school_id, year, province_id, province_name, school_payload):
        total_added = 0
        seen_signatures = set()

        while True:
            self.ensure_overlay_cleared(page)

            rows = self.parser.table_snapshot(page)
            signature = self.parser.first_row_signature(page)

            if signature:
                if signature in seen_signatures:
                    break
                seen_signatures.add(signature)

            current_filters = self.get_current_filter_texts(page)
            current_group = self.get_current_major_group(page)
            if current_group:
                current_filters["major_group"] = current_group

            records = self.parser.normalize_table_rows(
                school_id=school_id,
                year=year,
                province_id=province_id,
                province_name=province_name,
                rows=rows,
                current_filters=current_filters,
            )
            total_added += self.store.merge_records(school_payload, records)

            page_no = self.parser.current_page_no(page)
            if len(rows) < self.config.page_size_hint and page_no > 1:
                break

            moved = self.click_next_page(page)
            if not moved:
                break

            polite_sleep()

        return total_added

    def _select_type_batch_group(self, page, province_name, year, type_text=None, batch_text=None, group_text=None):
        combo = {}
        if type_text:
            combo['type'] = {'text': type_text}
        if batch_text:
            combo['batch'] = {'text': batch_text}
        if group_text:
            combo['major_group'] = {'text': group_text}

        ok = self.set_base_filters(page, province_name, year)
        if not ok:
            return False

        applied = self.apply_combo(page, combo)
        if not applied:
            return False

        return self.ensure_combo_applied(page, combo)

    def _collect_type_options(self, page):
        current = self.get_current_filter_texts(page)
        options = self.collect_dropdown_options_by_index(page, 2)
        if not options and current.get("type"):
            return [clean_text(current.get("type"))]
        return [clean_text(x) for x in options if clean_text(x)] or [None]

    def _collect_batch_options(self, page):
        current = self.get_current_filter_texts(page)
        options = self.collect_dropdown_options_by_index(page, 3)
        if not options and current.get("batch"):
            return [clean_text(current.get("batch"))]
        return [clean_text(x) for x in options if clean_text(x)] or [None]

    def _collect_group_options(self, page):
        self.expand_major_groups_if_needed(page)
        groups = self.collect_major_groups(page, keep_all=True)
        groups = [clean_text(x) for x in groups if clean_text(x)]
        specific = [x for x in groups if x != "全部"]
        return specific or [None]

    def crawl_one_province_year(self, page, school_id, year, province_id, province_name, school_payload):
        ok = self.set_base_filters(page, province_name, year)
        if not ok:
            print(f" ⚠️ 省份 {province_name} / 年份 {year} 选择失败，跳过")
            return 0

        type_options = self._collect_type_options(page)
        year_added = 0
        path_index = 0

        print(f"年份 {year} 类型分支数: {len(type_options)}")

        for type_text in type_options:
            ok = self._select_type_batch_group(page, province_name, year, type_text=type_text)
            if not ok:
                print(f" ⚠️ 类型选择失败: {type_text or '默认'}")
                continue

            batch_options = self._collect_batch_options(page)

            for batch_text in batch_options:
                ok = self._select_type_batch_group(
                    page,
                    province_name,
                    year,
                    type_text=type_text,
                    batch_text=batch_text,
                )
                if not ok:
                    print(f" ⚠️ 批次选择失败: type={type_text or '默认'}, batch={batch_text or '默认'}")
                    continue

                group_options = self._collect_group_options(page)

                for group_text in group_options:
                    ok = self._select_type_batch_group(
                        page,
                        province_name,
                        year,
                        type_text=type_text,
                        batch_text=batch_text,
                        group_text=group_text,
                    )
                    if not ok:
                        print(
                            f" ⚠️ 组合应用失败: "
                            f"type={type_text or '默认'}, batch={batch_text or '默认'}, major_group={group_text or '默认'}"
                        )
                        continue

                    path_index += 1
                    parts = []
                    if type_text:
                        parts.append(f"type={type_text}")
                    if batch_text:
                        parts.append(f"batch={batch_text}")
                    if group_text:
                        parts.append(f"major_group={group_text}")
                    log_text = ", ".join(parts) if parts else "默认"
                    print(f" ↳ 路径 {path_index}: {log_text}")

                    added = self.scrape_current_combo(
                        page=page,
                        school_id=school_id,
                        year=year,
                        province_id=province_id,
                        province_name=province_name,
                        school_payload=school_payload,
                    )
                    year_added += added

                    if path_index % self.config.flush_combos == 0:
                        self.store.save_school_records(school_id, school_payload)
                        print(f" ↻ 已阶段性保存学校 {school_id}，当前累计 {len(school_payload['data'])} 条")

        return year_added
