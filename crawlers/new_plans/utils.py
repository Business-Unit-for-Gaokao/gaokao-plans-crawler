import json
import os
import random
import time
from pathlib import Path
from .config import PROVINCE_DICT, PROVINCE_NAME_TO_ID


def now_str():
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


def polite_sleep(min_delay=0.4, max_delay=0.9):
    time.sleep(random.uniform(min_delay, max_delay))


def clean_text(value):
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split()).strip()


def write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def compact_dict(data):
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            vv = compact_dict(v)
            if vv in (None, "", {}, []):
                continue
            out[k] = vv
        return out

    if isinstance(data, list):
        arr = []
        for x in data:
            xx = compact_dict(x)
            if xx in (None, "", {}, []):
                continue
            arr.append(xx)
        return arr

    return data


def parse_years(years_input, default_years):
    if years_input is None:
        return default_years[:]

    if isinstance(years_input, list):
        arr = [str(y).strip() for y in years_input if str(y).strip()]
        return arr or default_years[:]

    if isinstance(years_input, str):
        raw = years_input.strip()
        if not raw:
            return default_years[:]
        if "-" in raw:
            start, end = raw.split("-", 1)
            start = int(start.strip())
            end = int(end.strip())
            if start >= end:
                return [str(y) for y in range(start, end - 1, -1)]
            return [str(y) for y in range(end, start - 1, -1)]
        if "," in raw:
            arr = [x.strip() for x in raw.split(",") if x.strip()]
            return arr or default_years[:]
        return [raw]

    return default_years[:]


def parse_province_ids(province_ids_input):
    all_ids = list(PROVINCE_DICT.keys())

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
        if item in PROVINCE_DICT:
            pid = item
        elif item in PROVINCE_NAME_TO_ID:
            pid = PROVINCE_NAME_TO_ID[item]
        else:
            continue
        if pid not in seen:
            seen.add(pid)
            result.append(pid)

    return result or all_ids


def normalize_filter_options(options):
    cleaned = []
    seen = set()
    for x in options or []:
        v = clean_text(x)
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


def load_default_school_ids():
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
