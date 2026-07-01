from .utils import clean_text, compact_dict


class PlanTableParser:
    def __init__(self, page_size_hint=10):
        self.page_size_hint = page_size_hint

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
const rateText = rateTd ? (rateTd.innerText || rateTd.textContent || '').replace(/\s+/g, ' ').trim() : '';

return {
major_name: h3 ? (h3.innerText || h3.textContent || '').trim() : '',
major_remark: pList.join('；'),
subject_requirements: xk ? (xk.innerText || xk.textContent || '').trim() : '',
plan_number: (tds[1].innerText || tds[1].textContent || '').replace(/\s+/g, ' ').trim(),
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
            clean_text(first.get("major_name")),
            clean_text(first.get("plan_number")),
            clean_text(first.get("education_years")),
            clean_text(first.get("tuition")),
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
return /^\d+$/.test(t) ? parseInt(t, 10) : 1;
}
"""
        )
        return int(n) if n else 1

    def normalize_table_rows(self, school_id, year, province_id, province_name, rows, current_filters):
        result = []
        for row in rows:
            major_name = clean_text(row.get("major_name"))
            major_remark = clean_text(row.get("major_remark"))
            subject_requirements = clean_text(row.get("subject_requirements"))
            plan_number = clean_text(row.get("plan_number"))
            education_years = clean_text(row.get("education_years"))
            tuition = clean_text(row.get("tuition"))
            rate_text = clean_text(row.get("admission_rate_text"))

            if not major_name and not plan_number:
                continue

            item = {
                "school_id": str(school_id),
                "year": str(year),
                "province_id": str(province_id),
                "province": province_name,
                "type": clean_text(current_filters.get("type")),
                "batch": clean_text(current_filters.get("batch")),
                "major_group": clean_text(current_filters.get("major_group")),
                "major_name": major_name,
                "major_remark": major_remark,
                "subject_requirements": subject_requirements,
                "plan_number": plan_number,
                "education_years": education_years,
                "tuition": tuition,
            }

            if rate_text and rate_text != "录取率":
                item["admission_rate_text"] = rate_text

            result.append(compact_dict(item))
        return result
