import time


class BrowserMixin:
    def _start_playwright_browser(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError(
                "未安装 Playwright。请先执行: pip install playwright && python -m playwright install chromium"
            ) from e

        p = sync_playwright().start()

        if self.config.browser_mode == "cdp":
            browser = p.chromium.connect_over_cdp(self.config.cdp_url)
            return p, browser, True

        if self.config.browser_mode == "chrome":
            browser = p.chromium.launch(
                channel="chrome",
                headless=self.config.browser_headless,
                slow_mo=self.config.browser_slow_mo,
                args=["--disable-blink-features=AutomationControlled"],
            )
            return p, browser, False

        browser = p.chromium.launch(
            headless=self.config.browser_headless,
            slow_mo=self.config.browser_slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
        )
        return p, browser, False

    def new_page(self, context):
        page = context.new_page()
        page.set_default_timeout(self.config.page_timeout_ms)
        return page

    def school_rule_url(self, school_id):
        return f"https://www.gaokao.cn/school/{school_id}/sturule"

    def _page_wait(self, page, ms=None):
        page.wait_for_timeout(ms if ms is not None else self.config.wait_after_click_ms)

    def dismiss_page_noise(self, page):
        texts = ["我知道了", "知道了", "关闭", "稍后再说", "同意", "允许"]
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
const norm = s => (s || '').replace(/\s+/g, '').trim();
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
        if not self.config.require_login:
            return True

        self.close_login_popup(page)

        if self.is_logged_in(page):
            print("✅ 检测到已登录，继续抓取")
            return True

        print("⚠️ 当前需要登录后再抓取")
        print("请在打开的浏览器里手动点击“登录/注册”，扫码登录后不要关闭浏览器")
        print(f"最多等待 {self.config.login_wait_seconds} 秒...")

        start = time.time()
        while time.time() - start < self.config.login_wait_seconds:
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
        page.goto(self.school_rule_url(school_id), wait_until="domcontentloaded", timeout=self.config.page_timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        self._page_wait(page, self.config.wait_after_nav_ms)
        self.ensure_overlay_cleared(page)
        page.wait_for_selector("body", state="attached", timeout=self.config.page_timeout_ms)
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
