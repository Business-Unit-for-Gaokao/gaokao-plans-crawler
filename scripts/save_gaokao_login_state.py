from playwright.sync_api import sync_playwright

LOGIN_URL = 'https://www.gaokao.cn/'
STATE_FILE = 'storage_state.json'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(LOGIN_URL, wait_until='domcontentloaded')
    input('请在浏览器中完成登录，然后按回车保存登录态...')
    context.storage_state(path=STATE_FILE)
    browser.close()
    print(f'已保存登录态: {STATE_FILE}')
