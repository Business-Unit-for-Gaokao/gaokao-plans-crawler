#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path


def load_jsonl(path: Path):
    rows = []
    with path.open('r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                rows.append({
                    '_bad_line': True,
                    '_file': str(path),
                    '_line_no': line_no,
                    '_raw': line,
                    '_error': str(e),
                })
    return rows


def normalize(obj):
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [normalize(x) for x in obj]
    return obj


def dedupe_key(obj, mode='exact'):
    if mode == 'exact':
        return json.dumps(normalize(obj), ensure_ascii=False, sort_keys=True)

    keys = ['school_id', 'province', 'year', 'type', 'batch', 'group', 'stage', 'error']
    slim = {k: obj.get(k) for k in keys if k in obj}
    return json.dumps(normalize(slim), ensure_ascii=False, sort_keys=True)


def main():
    parser = argparse.ArgumentParser(description='去重 _meta 目录下的 jsonl 错误日志')
    parser.add_argument('--meta-dir', default='data/v13_plans/_meta')
    parser.add_argument('--pattern', default='*.jsonl')
    parser.add_argument('--mode', choices=['exact', 'logical'], default='logical')
    parser.add_argument('--output', default='data/v13_plans/_meta/dedupe_summary.json')
    parser.add_argument('--merged-output', default='data/v13_plans/_meta/deduped_errors.jsonl')
    args = parser.parse_args()

    meta_dir = Path(args.meta_dir)
    files = sorted(meta_dir.glob(args.pattern))
    if not files:
        raise SystemExit(f'未找到文件: {meta_dir}/{args.pattern}')

    all_rows = []
    per_file = {}
    repeated = Counter()

    for path in files:
        rows = load_jsonl(path)
        per_file[str(path)] = len(rows)
        all_rows.extend([{**row, '_source_file': str(path)} for row in rows])

    seen = set()
    deduped = []

    for row in all_rows:
        key = dedupe_key(row, args.mode)
        if key in seen:
            repeated[key] += 1
            continue
        seen.add(key)
        deduped.append(row)

    Path(args.merged_output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.merged_output, 'w', encoding='utf-8') as f:
        for row in deduped:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    stage_counter = Counter(row.get('stage', 'UNKNOWN') for row in deduped if isinstance(row, dict))
    error_counter = Counter(row.get('error', 'UNKNOWN') for row in deduped if isinstance(row, dict))

    summary = {
        'meta_dir': str(meta_dir),
        'pattern': args.pattern,
        'mode': args.mode,
        'input_files': [str(p) for p in files],
        'per_file_rows': per_file,
        'total_rows': len(all_rows),
        'deduped_rows': len(deduped),
        'duplicate_rows_removed': len(all_rows) - len(deduped),
        'top_stages': stage_counter.most_common(20),
        'top_errors': error_counter.most_common(20),
        'duplicate_key_count': len(repeated),
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()