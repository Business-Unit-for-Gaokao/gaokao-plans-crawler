import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NewPlanConfig:
    output_dir: Path = field(default_factory=lambda: Path(os.getenv("NEW_PLAN_DATA_DIR", "data/new_plans_by_school")))
    flush_schools: int = field(default_factory=lambda: max(1, int(os.getenv("NEW_PLAN_FLUSH_SCHOOLS", "10"))))
    flush_combos: int = field(default_factory=lambda: max(1, int(os.getenv("NEW_PLAN_FLUSH_COMBOS", "10"))))

    browser_headless: bool = field(default_factory=lambda: os.getenv("NEW_PLAN_HEADLESS", "0") == "1")
    browser_slow_mo: int = field(default_factory=lambda: int(os.getenv("NEW_PLAN_BROWSER_SLOW_MO", "0") or 0))
    page_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEW_PLAN_PAGE_TIMEOUT_MS", "30000")))
    wait_after_click_ms: int = field(default_factory=lambda: int(os.getenv("NEW_PLAN_WAIT_AFTER_CLICK_MS", "800")))
    wait_after_nav_ms: int = field(default_factory=lambda: int(os.getenv("NEW_PLAN_WAIT_AFTER_NAV_MS", "1800")))
    page_size_hint: int = field(default_factory=lambda: max(1, int(os.getenv("NEW_PLAN_PAGE_SIZE_HINT", "10"))))
    max_combos: int = field(default_factory=lambda: int(os.getenv("NEW_PLAN_MAX_COMBOS", "0") or 0))

    browser_mode: str = field(default_factory=lambda: os.getenv("NEW_PLAN_BROWSER_MODE", "chrome").strip().lower())
    cdp_url: str = field(default_factory=lambda: os.getenv("NEW_PLAN_CDP_URL", "http://127.0.0.1:9222").strip())
    require_login: bool = field(default_factory=lambda: os.getenv("NEW_PLAN_REQUIRE_LOGIN", "1") == "1")
    login_wait_seconds: int = field(default_factory=lambda: int(os.getenv("NEW_PLAN_LOGIN_WAIT_SECONDS", "300")))

    default_years: list[str] = field(default_factory=lambda: ["2025", "2024", "2023", "2022", "2021"])


PROVINCE_DICT = {
    '11': '北京', '12': '天津', '13': '河北', '14': '山西', '15': '内蒙古',
    '21': '辽宁', '22': '吉林', '23': '黑龙江',
    '31': '上海', '32': '江苏', '33': '浙江', '34': '安徽', '35': '福建', '36': '江西', '37': '山东',
    '41': '河南', '42': '湖北', '43': '湖南',
    '44': '广东', '45': '广西', '46': '海南',
    '50': '重庆', '51': '四川', '52': '贵州', '53': '云南', '54': '西藏',
    '61': '陕西', '62': '甘肃', '63': '青海', '64': '宁夏', '65': '新疆',
    '71': '台湾', '81': '香港', '82': '澳门',
}

PROVINCE_NAME_TO_ID = {v: k for k, v in PROVINCE_DICT.items()}
