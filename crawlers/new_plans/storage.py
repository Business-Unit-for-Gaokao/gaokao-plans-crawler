import json
from pathlib import Path
from .utils import now_str, write_json_atomic, compact_dict


class SchoolPlanStore:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

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
                provinces.append({"province_id": pid, "province": pname})

        body = {
            "update_time": now_str(),
            "school_id": str(school_id),
            "years": years,
            "provinces": provinces,
            "count": len(records),
            "data": records,
        }
        write_json_atomic(file_path, body)

    def merge_records(self, school_payload, new_records):
        added = 0
        for item in new_records:
            item = compact_dict(item)
            key = self.build_record_key(item)
            if key in school_payload["existing_keys"]:
                continue
            school_payload["existing_keys"].add(key)
            school_payload["data"].append(item)
            added += 1
        return added
