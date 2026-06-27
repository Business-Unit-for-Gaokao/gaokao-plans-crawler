import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Optional
from playwright.sync_api import sync_playwright

BASE = 'https://www.gaokao.cn/school/{school_id}/sturule'
AGGREGATE_GROUP_NAMES = {'全部', '综合'}


def clean_text(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '')).strip()


def safe_int(s: str):
    m = re.search(r'\d+', clean_text(s))
    return int(m.group()) if m else None


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, obj: Dict[str, Any]):
    ensure_dir(path.parent)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def load_school_ids(data_file: Path) -> List[int]:
    data = json.loads(data_file.read_text(encoding='utf-8'))
    return [int(x['school_id']) for x in data.get('data', []) if x.get('school_id') is not None]


def plan_root(page):
    root = page.locator("xpath=//span[contains(normalize-space(.),'招生计划')]/ancestor::div[contains(@class,'bgwhite')][1]").first
    if root.count() == 0:
        root = page.locator('div.bgwhite').filter(has=page.locator('table.tb-normal')).first
    return root


def dismiss_overlays(page):
    close_selectors = [
        '.main-nav_openVipOpModalBox__1My1E .icon_close', '.ant-modal-close',
        '.ant-modal-wrap .icon_close', '.ant-modal-wrap .anticon-close',
        '.activate-member_close__DskC5', '.activate-member_activateMember__3Aock .icon_close'
    ]
    hide_selectors = [
        'div.ant-modal-wrap', 'div.modal-transparent', 'div.commonModalwrap',
        '.ant-modal-mask', 'img[src*="thumb.png"]', '.activate-member_activateMember__3Aock'
    ]
    for _ in range(2):
        try:
            page.keyboard.press('Escape')
        except Exception:
            pass
        for sel in close_selectors:
            try:
                loc = page.locator(sel)
                for i in range(loc.count()):
                    item = loc.nth(i)
                    try:
                        if item.is_visible():
                            try:
                                item.click(timeout=500, force=True)
                            except Exception:
                                try:
                                    item.evaluate('(el) => el.click()')
                                except Exception:
                                    pass
                    except Exception:
                        pass
            except Exception:
                pass
        for sel in hide_selectors:
            try:
                loc = page.locator(sel)
                for i in range(loc.count()):
                    item = loc.nth(i)
                    try:
                        if not item.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        handle = item.element_handle()
                        if handle:
                            page.evaluate("""
                                (el) => {
                                  try { el.style.pointerEvents = 'none'; } catch(e) {}
                                  try { el.style.display = 'none'; } catch(e) {}
                                }
                            """, handle)
                    except Exception:
                        pass
            except Exception:
                pass
        page.wait_for_timeout(60)


def install_fast_mode(page):
    def handle_route(route):
        req = route.request
        if req.resource_type in ('image', 'font', 'media'):
            return route.abort()
        url = req.url
        blocked_hosts = ('google-analytics.com', 'googletagmanager.com', 'doubleclick.net', 'hotjar.com', 'facebook.net', 'baidu.com/hm.js')
        if any(h in url for h in blocked_hosts):
            return route.abort()
        return route.continue_()
    page.route('**/*', handle_route)
    page.add_init_script("""
        (() => {
          const style = document.createElement('style');
          style.textContent = `*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important;}`;
          document.documentElement.appendChild(style);
        })();
    """)


def safe_click(locator, page, timeout=2500):
    dismiss_overlays(page)
    try:
        locator.scroll_into_view_if_needed(timeout=timeout)
    except Exception:
        pass
    try:
        locator.click(timeout=timeout)
        return
    except Exception:
        pass
    dismiss_overlays(page)
    try:
        locator.evaluate('(el) => el.click()')
        return
    except Exception:
        pass
    locator.click(timeout=timeout, force=True)


def wait_plan_ready(page, timeout=15000):
    dismiss_overlays(page)
    root = plan_root(page)
    root.locator('table.tb-normal').wait_for(state='visible', timeout=timeout)
    page.wait_for_timeout(180)


def get_table_signature(page) -> str:
    root = plan_root(page)
    rows = root.locator('table.tb-normal tbody tr')
    count = rows.count()
    first_text = clean_text(rows.nth(0).text_content())[:160] if count else ''
    active = root.locator('.ant-pagination-item-active a').first
    pager = clean_text(active.text_content()) if active.count() else '1'
    return f'{pager}|{count}|{first_text}'


def wait_table_changed(page, before_sig: str, timeout=4500):
    page.wait_for_function(
        """
        ([prev]) => {
          const table = document.querySelector('table.tb-normal');
          if (!table) return false;
          const rows = table.querySelectorAll('tbody tr');
          if (!rows.length) return false;
          const active = document.querySelector('.ant-pagination-item-active a');
          const pageNo = active ? (active.innerText || '').trim() : '1';
          const first = ((rows[0].innerText || '').replace(/\s+/g, ' ').trim()).slice(0, 160);
          return `${pageNo}|${rows.length}|${first}` !== prev;
        }
        """,
        [before_sig],
        timeout=timeout
    )
    page.wait_for_timeout(120)


def reopen_school(page, school_id: int):
    url = BASE.format(school_id=school_id)
    page.goto(url, wait_until='domcontentloaded', timeout=45000)
    wait_plan_ready(page)


def get_select_boxes(page):
    return plan_root(page).locator('.ant-select-selection')


def get_selected_value(page, idx: int) -> str:
    boxes = get_select_boxes(page)
    if boxes.count() <= idx:
        return ''
    box = boxes.nth(idx)
    val = box.locator('.ant-select-selection-selected-value')
    if val.count():
        return clean_text(val.first.text_content())
    ph = box.locator('.ant-select-selection__placeholder')
    return clean_text(ph.first.text_content()) if ph.count() else ''


def open_select(page, idx: int):
    dismiss_overlays(page)
    boxes = get_select_boxes(page)
    if boxes.count() <= idx:
        raise RuntimeError(f'下拉框不足，索引={idx}')
    safe_click(boxes.nth(idx), page)
    page.wait_for_timeout(180)


def close_dropdown(page):
    try:
        page.keyboard.press('Escape')
    except Exception:
        pass
    page.wait_for_timeout(80)


def _visible_dropdown_options(page, idx: int) -> List[str]:
    if idx == 0:
        return page.evaluate("""
            () => {
              const drops = Array.from(document.querySelectorAll('div.ant-select-dropdown'))
                .filter(el => !el.classList.contains('ant-select-dropdown-hidden') && getComputedStyle(el).display !== 'none' && el.offsetParent !== null);
              const host = drops.map(d => d.querySelector('.score-plan_proSelectBox__3TLK5')).find(Boolean);
              if (!host) return [];
              return Array.from(host.querySelectorAll('.score-plan_item__1mtQ4')).map(x => (x.innerText || '').replace(/\s+/g,' ').trim()).filter(Boolean);
            }
        """) or []
    return page.evaluate("""
        () => {
          const drops = Array.from(document.querySelectorAll('div.ant-select-dropdown'))
            .filter(el => !el.classList.contains('ant-select-dropdown-hidden') && getComputedStyle(el).display !== 'none' && el.offsetParent !== null);
          const host = drops.find(d => d.querySelector('.ant-select-dropdown-menu-item'));
          if (!host) return [];
          return Array.from(host.querySelectorAll('.ant-select-dropdown-menu-item')).map(x => (x.innerText || '').replace(/\s+/g,' ').trim()).filter(Boolean);
        }
    """) or []


def get_dropdown_options(page, idx: int, fallback=None) -> List[str]:
    fallback = fallback or []
    try:
        open_select(page, idx)
        vals = [clean_text(x) for x in _visible_dropdown_options(page, idx) if clean_text(x)]
        close_dropdown(page)
        return vals or fallback
    except Exception:
        try:
            close_dropdown(page)
        except Exception:
            pass
        return fallback


def click_visible_option(page, idx: int, text: str) -> bool:
    if idx == 0:
        return bool(page.evaluate("""
            (target) => {
              const drops = Array.from(document.querySelectorAll('div.ant-select-dropdown'))
                .filter(el => !el.classList.contains('ant-select-dropdown-hidden') && getComputedStyle(el).display !== 'none' && el.offsetParent !== null);
              const host = drops.map(d => d.querySelector('.score-plan_proSelectBox__3TLK5')).find(Boolean);
              if (!host) return false;
              const items = Array.from(host.querySelectorAll('.score-plan_item__1mtQ4'));
              const el = items.find(x => (x.innerText || '').replace(/\s+/g,' ').trim() === target);
              if (!el) return false;
              el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              el.click();
              return true;
            }
        """, text))
    return bool(page.evaluate("""
        (target) => {
          const drops = Array.from(document.querySelectorAll('div.ant-select-dropdown'))
            .filter(el => !el.classList.contains('ant-select-dropdown-hidden') && getComputedStyle(el).display !== 'none' && el.offsetParent !== null);
          const host = drops.find(d => d.querySelector('.ant-select-dropdown-menu-item'));
          if (!host) return false;
          const items = Array.from(host.querySelectorAll('.ant-select-dropdown-menu-item'));
          const el = items.find(x => (x.innerText || '').replace(/\s+/g,' ').trim() === target);
          if (!el) return false;
          el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
          el.click();
          return true;
        }
    """, text))


def wait_selected_value(page, idx: int, target: str, timeout_ms=3200) -> bool:
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        if get_selected_value(page, idx) == target:
            return True
        page.wait_for_timeout(100)
    return False


def get_context_debug(page, idx: int) -> Dict[str, Any]:
    return {
        'idx': idx,
        'current': get_selected_value(page, idx),
        'options': get_dropdown_options(page, idx, fallback=[])
    }


def choose_dropdown_value(page, idx: int, text: str):
    current = get_selected_value(page, idx)
    if current == text:
        return
    last_error = None
    for _ in range(3):
        before = get_table_signature(page)
        try:
            open_select(page, idx)
            options = _visible_dropdown_options(page, idx)
            if idx == 0 and text not in options:
                close_dropdown(page)
                raise RuntimeError(f'省份下拉项不存在 target={text}')
            if idx != 0 and text not in options:
                close_dropdown(page)
                raise RuntimeError(f'下拉项不存在 idx={idx} target={text}')
            ok = click_visible_option(page, idx, text)
            if not ok:
                close_dropdown(page)
                raise RuntimeError(f'下拉点击失败 idx={idx} target={text}')
            if not wait_selected_value(page, idx, text):
                raise RuntimeError(f'下拉切换失败 idx={idx} target={text} current={get_selected_value(page, idx)}')
            try:
                wait_table_changed(page, before)
            except Exception:
                page.wait_for_timeout(200)
            return
        except Exception as e:
            last_error = e
            try:
                close_dropdown(page)
            except Exception:
                pass
            page.wait_for_timeout(180)
    raise last_error if last_error else RuntimeError(f'下拉切换失败 idx={idx} target={text} current={get_selected_value(page, idx)}')


def prepare_context(page, school_id: int, province: Optional[str] = None, year: Optional[str] = None, type_name: Optional[str] = None, batch_name: Optional[str] = None):
    reopen_school(page, school_id)
    if province:
        choose_dropdown_value(page, 0, province)
    if year:
        choose_dropdown_value(page, 1, year)
    if type_name:
        choose_dropdown_value(page, 2, type_name)
    if batch_name:
        choose_dropdown_value(page, 3, batch_name)


def wait_group_ready(page, timeout=5000):
    page.wait_for_function(
        """
        () => {
          const box = document.querySelector('.score-plan_groupList__1eMnJ');
          if (!box) return false;
          return box.querySelectorAll('.score-plan_item__1mtQ4').length > 0;
        }
        """,
        timeout=timeout
    )
    page.wait_for_timeout(120)


def get_groups(page) -> List[str]:
    try:
        wait_group_ready(page, timeout=3500)
    except Exception:
        return ['全部']
    vals = page.evaluate("""
        () => {
          const box = document.querySelector('.score-plan_groupList__1eMnJ');
          if (!box) return [];
          return Array.from(box.querySelectorAll('.score-plan_item__1mtQ4'))
            .map(x => (x.innerText || '').replace(/\s+/g, ' ').trim())
            .filter(Boolean);
        }
    """)
    return vals or ['全部']


def choose_groups_to_collect(groups: List[str], force_all_groups: bool) -> List[str]:
    groups = [clean_text(g) for g in groups if clean_text(g)]
    if not groups:
        return ['全部']
    if force_all_groups:
        return groups
    detail_groups = [g for g in groups if g not in AGGREGATE_GROUP_NAMES]
    return detail_groups or groups


def get_active_group(page) -> str:
    try:
        return page.evaluate("""
            () => {
              const el = document.querySelector('.score-plan_groupList__1eMnJ .score-plan_active__2pQaY');
              return el ? (el.innerText || '').replace(/\s+/g, ' ').trim() : '';
            }
        """) or ''
    except Exception:
        return ''


def get_total_pages(page) -> int:
    loc = plan_root(page).locator('.ant-pagination-item a')
    nums = []
    for x in loc.all_text_contents():
        x = clean_text(x)
        if x.isdigit():
            nums.append(int(x))
    return max(nums) if nums else 1


def get_current_page(page) -> int:
    try:
        txt = page.evaluate("""
            () => {
              const active = document.querySelector('.ant-pagination-item-active a');
              return active ? (active.innerText || '').trim() : '1';
            }
        """)
        return int(txt) if str(txt).isdigit() else 1
    except Exception:
        return 1


def ensure_first_page(page) -> bool:
    if get_current_page(page) == 1:
        return True
    root = plan_root(page)
    before = get_table_signature(page)
    first_btn = root.locator('button.first_page').first
    if first_btn.count() and 'disable' not in (first_btn.get_attribute('class') or ''):
        try:
            safe_click(first_btn, page)
            try:
                wait_table_changed(page, before)
            except Exception:
                page.wait_for_timeout(250)
        except Exception:
            pass
    if get_current_page(page) == 1:
        return True
    p1 = root.locator('.ant-pagination-item a', has_text='1').first
    if p1.count():
        try:
            before = get_table_signature(page)
            safe_click(p1, page)
            try:
                wait_table_changed(page, before)
            except Exception:
                page.wait_for_timeout(250)
        except Exception:
            pass
    return get_current_page(page) == 1


def goto_page(page, target: int) -> bool:
    if get_current_page(page) == target:
        return True
    root = plan_root(page)

    def click_and_check(locator) -> bool:
        before = get_table_signature(page)
        safe_click(locator, page)
        try:
            wait_table_changed(page, before)
        except Exception:
            page.wait_for_timeout(250)
        return get_current_page(page) == target

    direct = root.locator('.ant-pagination-item a', has_text=str(target)).first
    if direct.count() and click_and_check(direct):
        return True
    if target == 1 and ensure_first_page(page):
        return True
    while get_current_page(page) < target:
        next_btn = root.locator('.ant-pagination-next').first
        if next_btn.count() == 0 or 'ant-pagination-disabled' in (next_btn.get_attribute('class') or ''):
            break
        before = get_table_signature(page)
        safe_click(next_btn, page)
        try:
            wait_table_changed(page, before)
        except Exception:
            page.wait_for_timeout(250)
        if get_current_page(page) == target:
            return True
    direct = root.locator('.ant-pagination-item a', has_text=str(target)).first
    return click_and_check(direct) if direct.count() else get_current_page(page) == target


def click_group(page, text: str):
    for _ in range(3):
        try:
            wait_group_ready(page, timeout=3500)
        except Exception:
            return False
        ensure_first_page(page)
        current = get_active_group(page)
        if current == text:
            return True
        if text in AGGREGATE_GROUP_NAMES and current in ('', *AGGREGATE_GROUP_NAMES):
            return True
        before = get_table_signature(page)
        ok = page.evaluate("""
            (target) => {
              const box = document.querySelector('.score-plan_groupList__1eMnJ');
              if (!box) return false;
              const items = Array.from(box.querySelectorAll('.score-plan_item__1mtQ4'));
              const el = items.find(x => (x.innerText || '').replace(/\s+/g, ' ').trim() === target);
              if (!el) return false;
              el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
              el.click();
              return true;
            }
        """, text)
        if not ok:
            loc = plan_root(page).locator('.score-plan_groupList__1eMnJ .score-plan_item__1mtQ4', has_text=text).first
            if loc.count() == 0:
                return False
            try:
                safe_click(loc, page)
            except Exception:
                return False
        try:
            wait_table_changed(page, before)
        except Exception:
            page.wait_for_timeout(250)
        active = get_active_group(page)
        if text not in AGGREGATE_GROUP_NAMES and active == text:
            return True
        if text in AGGREGATE_GROUP_NAMES and active in ('', *AGGREGATE_GROUP_NAMES):
            return True
    return False


def extract_rows_bulk(page, school_id: int, province: str, year: str, type_name: str, batch_name: str, group_name: str):
    rows = page.evaluate("""
        () => {
          const trs = Array.from(document.querySelectorAll('table.tb-normal tbody tr'));
          return trs.map(tr => {
            const tds = tr.querySelectorAll('td');
            if (tds.length < 3) return null;
            const info = tds[0];
            const h3 = info.querySelector('h3');
            const ps = Array.from(info.querySelectorAll('p')).map(x => (x.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
            const xk = info.querySelector('.score-plan_xkyq__16ULz');
            const study = Array.from(tds[2].querySelectorAll('p')).map(x => (x.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
            return {
              major_name: h3 ? (h3.innerText || '').replace(/\s+/g, ' ').trim() : '',
              major_remark: ps.join(' '),
              subject_requirement: xk ? (xk.innerText || '').replace(/\s+/g, ' ').trim() : '',
              plan_count_text: (tds[1].innerText || '').replace(/\s+/g, ' ').trim(),
              duration: study[0] || '',
              tuition: study[1] || ''
            };
          }).filter(Boolean);
        }
    """)
    out = []
    for r in rows:
        out.append({
            'school_id': school_id,
            'province': province,
            'year': year,
            'type': type_name,
            'batch': batch_name,
            'group': group_name,
            'major_name': clean_text(r.get('major_name', '')),
            'major_remark': clean_text(r.get('major_remark', '')),
            'subject_requirement': clean_text(r.get('subject_requirement', '')),
            'plan_count': safe_int(r.get('plan_count_text', '')),
            'duration': clean_text(r.get('duration', '')),
            'tuition': clean_text(r.get('tuition', '')),
        })
    return out


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    cols = ['school_id','province','year','type','batch','group','major_name','major_remark','subject_requirement','plan_count','duration','tuition']
    for row in rows:
        key = tuple(row.get(k) for k in cols)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def log_error(errors_file: Path, code: str, stage: str, school_id: int, province=None, year=None, type_name=None, batch=None, group=None, err=None, debug=None, worker_id=None):
    append_jsonl(errors_file, {
        'error_code': code,
        'worker_id': worker_id,
        'school_id': school_id,
        'province': province,
        'year': year,
        'type': type_name,
        'batch': batch,
        'group': group,
        'stage': stage,
        'error': str(err) if err else '',
        'debug': debug or {}
    })


def discover_provinces(page, school_id: int) -> List[str]:
    reopen_school(page, school_id)
    vals = get_dropdown_options(page, 0, fallback=[])
    if vals:
        return vals
    current = get_selected_value(page, 0)
    return [current] if current else []


def crawl_school_provinces(page, school_id: int, provinces: List[str], out_root: Path, resume: bool, errors_file: Path, all_groups: bool, worker_id: int):
    for province in provinces:
        try:
            prepare_context(page, school_id, province=province)
        except Exception as e:
            debug = get_context_debug(page, 0) if plan_root(page).count() else {}
            log_error(errors_file, 'province_select', 'province_loop', school_id, province=province, err=e, debug=debug, worker_id=worker_id)
            continue

        years = get_dropdown_options(page, 1, fallback=[])
        if not years:
            years = [get_selected_value(page, 1)] if get_selected_value(page, 1) else []
        for year in years:
            school_year_dir = out_root / str(school_id) / str(year)
            out_file = school_year_dir / f'{province}.json'
            if resume and out_file.exists():
                continue
            all_rows = []
            try:
                prepare_context(page, school_id, province=province, year=year)
            except Exception as e:
                debug = get_context_debug(page, 1) if plan_root(page).count() else {}
                log_error(errors_file, 'year_select', 'province_loop', school_id, province=province, year=year, err=e, debug=debug, worker_id=worker_id)
                continue

            types = get_dropdown_options(page, 2, fallback=[])
            if not types:
                types = [get_selected_value(page, 2)] if get_selected_value(page, 2) else ['']

            for type_name in types:
                try:
                    prepare_context(page, school_id, province=province, year=year, type_name=type_name if type_name else None)
                except Exception as e:
                    debug = get_context_debug(page, 2) if plan_root(page).count() else {}
                    log_error(errors_file, 'type_select', 'province_loop', school_id, province=province, year=year, type_name=type_name, err=e, debug=debug, worker_id=worker_id)
                    continue

                batches = get_dropdown_options(page, 3, fallback=[])
                if not batches:
                    batches = [get_selected_value(page, 3)] if get_selected_value(page, 3) else ['']

                for batch_name in batches:
                    try:
                        prepare_context(page, school_id, province=province, year=year, type_name=type_name if type_name else None, batch_name=batch_name if batch_name else None)
                    except Exception as e:
                        debug = get_context_debug(page, 3) if plan_root(page).count() else {}
                        log_error(errors_file, 'batch_select', 'province_loop', school_id, province=province, year=year, type_name=type_name, batch=batch_name, err=e, debug=debug, worker_id=worker_id)
                        continue

                    raw_groups = get_groups(page)
                    groups = choose_groups_to_collect(raw_groups, all_groups)
                    for group_name in groups:
                        try:
                            prepare_context(page, school_id, province=province, year=year, type_name=type_name if type_name else None, batch_name=batch_name if batch_name else None)
                            raw_groups = get_groups(page)
                            groups_now = choose_groups_to_collect(raw_groups, all_groups)
                            if group_name not in groups_now and group_name not in AGGREGATE_GROUP_NAMES:
                                log_error(errors_file, 'group_missing', 'group_switch', school_id, province=province, year=year, type_name=type_name, batch=batch_name, group=group_name, err='专业组缺失', debug={'groups': groups_now}, worker_id=worker_id)
                                continue
                            actual_group = group_name
                            if group_name not in AGGREGATE_GROUP_NAMES:
                                if not click_group(page, group_name):
                                    log_error(errors_file, 'group_switch', 'group_switch', school_id, province=province, year=year, type_name=type_name, batch=batch_name, group=group_name, err='专业组切换失败，已跳过该组', debug={'groups': groups_now}, worker_id=worker_id)
                                    continue
                                actual_group = get_active_group(page) or group_name
                            else:
                                actual_group = get_active_group(page) or group_name

                            if not ensure_first_page(page):
                                log_error(errors_file, 'goto_page_1', 'goto_page', school_id, province=province, year=year, type_name=type_name, batch=batch_name, group=actual_group, err='切组后无法回到第1页', worker_id=worker_id)
                                continue

                            total_pages = get_total_pages(page)
                            all_rows.extend(extract_rows_bulk(page, school_id, province, year, type_name, batch_name, actual_group))
                            for pno in range(2, total_pages + 1):
                                if not goto_page(page, pno):
                                    log_error(errors_file, 'goto_page_n', 'goto_page', school_id, province=province, year=year, type_name=type_name, batch=batch_name, group=actual_group, err=f'无法跳转到第{pno}页', worker_id=worker_id)
                                    break
                                all_rows.extend(extract_rows_bulk(page, school_id, province, year, type_name, batch_name, actual_group))
                        except Exception as e:
                            log_error(errors_file, 'group_or_page_exception', 'group_switch', school_id, province=province, year=year, type_name=type_name, batch=batch_name, group=group_name, err=e, worker_id=worker_id)
                            continue

            ensure_dir(school_year_dir)
            data = dedupe_rows(all_rows)
            out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'[OK] school={school_id} province={province} year={year} rows={len(data)}')


def split_list(items: List[str], n: int) -> List[List[str]]:
    n = max(1, n)
    buckets = [[] for _ in range(n)]
    for i, item in enumerate(items):
        buckets[i % n].append(item)
    return [b for b in buckets if b]


def run_worker(worker_id: int, school_id: int, provinces: List[str], args_dict: Dict[str, Any]):
    out_root = Path(args_dict['output_dir'])
    errors_file = out_root / '_meta' / f'errors_worker_{worker_id}.jsonl'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args_dict['headless'])
        context = browser.new_context(storage_state=args_dict['state_file'])
        page = context.new_page()
        page.set_viewport_size({'width': 1440, 'height': 1100})
        install_fast_mode(page)
        try:
            crawl_school_provinces(page, school_id, provinces, out_root, args_dict['resume'], errors_file, args_dict['all_groups'], worker_id)
        except Exception as e:
            log_error(out_root / '_meta' / 'errors_parallel.jsonl', 'worker_exception', 'parallel_worker', school_id, err=e, debug={'worker_id': worker_id, 'provinces': provinces}, worker_id=worker_id)
        finally:
            browser.close()
    return {'worker_id': worker_id, 'provinces': provinces}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-file', default='data.json')
    parser.add_argument('--output-dir', default='plans')
    parser.add_argument('--state-file', default='storage_state.json')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--all-groups', action='store_true')
    parser.add_argument('--workers', type=int, default=1, help='建议 2-6')
    args = parser.parse_args()

    data_file = Path(args.data_file)
    out_root = Path(args.output_dir)
    ensure_dir(out_root / '_meta')
    school_ids = load_school_ids(data_file)
    if args.limit > 0:
        school_ids = school_ids[:args.limit]

    for school_id in school_ids:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=args.headless)
            context = browser.new_context(storage_state=args.state_file)
            page = context.new_page()
            page.set_viewport_size({'width': 1440, 'height': 1100})
            install_fast_mode(page)
            try:
                provinces = discover_provinces(page, school_id)
            except Exception as e:
                log_error(out_root / '_meta' / 'errors_parallel.jsonl', 'discover_provinces', 'parallel_worker', school_id, err=e)
                browser.close()
                continue
            browser.close()

        if not provinces:
            log_error(out_root / '_meta' / 'errors_parallel.jsonl', 'empty_provinces', 'parallel_worker', school_id, err='未发现可选省份')
            continue

        if args.workers <= 1 or len(provinces) == 1:
            args_dict = {'output_dir': args.output_dir, 'state_file': args.state_file, 'resume': args.resume, 'headless': args.headless, 'all_groups': args.all_groups}
            run_worker(1, school_id, provinces, args_dict)
            continue

        args_dict = {'output_dir': args.output_dir, 'state_file': args.state_file, 'resume': args.resume, 'headless': args.headless, 'all_groups': args.all_groups}
        province_buckets = split_list(provinces, min(args.workers, len(provinces)))
        with ThreadPoolExecutor(max_workers=len(province_buckets)) as ex:
            futures = [ex.submit(run_worker, i, school_id, bucket, args_dict) for i, bucket in enumerate(province_buckets, 1)]
            for fu in as_completed(futures):
                try:
                    fu.result()
                except Exception as e:
                    log_error(out_root / '_meta' / 'errors_parallel.jsonl', 'parallel_future', 'parallel_worker', school_id, err=e)


if __name__ == '__main__':
    main()
