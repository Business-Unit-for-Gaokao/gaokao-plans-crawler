from playwright.sync_api import sync_playwright
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--state-file', default='storage_state.json')
parser.add_argument('--url', default='https://www.gaokao.cn/school/140/sturule')
parser.add_argument('--headless', action='store_true')
args = parser.parse_args()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=args.headless)
    context = browser.new_context(storage_state=args.state_file)
    page = context.new_page()
    page.goto(args.url, wait_until='domcontentloaded')
    page.wait_for_timeout(5000)
    print('当前页面标题:', page.title())
    print('当前URL:', page.url)
    input('页面已打开。请手工检查页面，完成后按回车退出...')
    browser.close()
