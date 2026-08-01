#!/usr/bin/env python3
"""Report Audit Tool for AI Berkshire.
数据抽检工具：从研究报告中抽取15%的财务数据点，与可靠信源比对，
通过则准出，不通过则打回并说明原因。
Zero external dependencies — uses only Python stdlib.
Requires Python >= 3.7.

Usage:
  python3 tools/report_audit.py extract --report reports/xxx.md
  python3 tools/report_audit.py verdict --results '[...]'
  python3 tools/report_audit.py extract --report reports/xxx.md --dry-run
"""
import argparse
import json
import math
import os
import re
import sys
from decimal import Decimal, Context, ROUND_HALF_EVEN
from random import Random

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)

_SIGN = r'[+\-−–－＋]?'
_KV_LABEL_RE = re.compile(
    r'(?P<label>[\u4e00-\u9fa5A-Za-z][^\|\n：:*]{1,30})[：:]\s*[~约]?\$?'
    r'(?P<num>' + _SIGN + r'[\d,，\.]+)\s*(?P<unit>亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?'
)

def _clean_num(s: str) -> float:
    s = s.replace(',', '').replace('，', '').strip()
    for ch in ('−', '–', '－'):
        s = s.replace(ch, '-')
    s = s.replace('＋', '+')
    try:
        return float(s)
    except ValueError:
        return None

def _is_valid_label(label: str) -> bool:
    label = label.strip()
    if len(label) < 2:
        return False
    if re.fullmatch(r'[\d\s年季度Q]+', label):
        return False
    if re.match(r'^[+\-\*#\|~\$>_`]', label):
        return False
    if '**' in label or '`' in label or '__' in label:
        return False
    if re.fullmatch(r'[+\-]?\d+(\.\d+)?%', label):
        return False
    _SKIP = {'来源', 'sources', 'source', '说明', '注意', '备注', '数据来源',
             'n/a', '—', '-', '/', '合计', 'total', '单位', '趋势'}
    if label.lower() in _SKIP:
        return False
    return True

def _parse_md_tables(lines: list) -> list:
    results = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if '|' in line and not re.match(r'^\|[\-\s\|:]+\|$', line):
            headers_raw = [h.strip().strip('*_').strip() for h in line.split('|')]
            headers_raw = [h for h in headers_raw if h]
            if i + 1 < len(lines) and re.match(r'^\|[\-\s\|:]+\|$', lines[i+1].strip()):
                i += 2
                while i < len(lines):
                    dline = lines[i].strip()
                    if not dline or not dline.startswith('|'):
                        break
                    cells = [c.strip().strip('*_~').strip() for c in dline.split('|')]
                    cells = [c for c in cells if c != '']
                    if len(cells) < 2:
                        i += 1
                        continue
                    row_label = cells[0]
                    for col_idx, cell in enumerate(cells[1:], start=1):
                        col_header = headers_raw[col_idx] if col_idx < len(headers_raw) else f'列{col_idx}'
                        m = re.search(
                            r'[~约]?\$?(' + _SIGN + r'[\d,，\.]+)\s*'
                            r'(亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?',
                            cell
                        )
                        if m:
                            val = _clean_num(m.group(1))
                            unit = (m.group(2) or '').strip()
                            if val is not None and val != 0 and abs(val) < 1e15:
                                results.append((row_label, col_header, val, unit, i + 1, dline))
                    i += 1
                continue
        i += 1
    return results

def extract_data_points(md_text: str) -> list:
    points = []
    seen = set()
    def _add(label, val, unit, lineno, raw):
        label = re.sub(r'[\*_`]+', '', label).strip()
        if not _is_valid_label(label):
            return
        if val is None or val == 0 or abs(val) > 1e15:
            return
        if re.fullmatch(r'(20\d{2}|Q[1-4]|\d{4}\s*Q[1-4])', label.strip()):
            return
        key = f"{label}|{round(val,4)}|{unit}"
        if key in seen:
            return
        seen.add(key)
        points.append({
            'id': len(points) + 1,
            'label': label,
            'reported_value': val,
            'unit': unit,
            'raw_text': raw[:120],
            'line_number': lineno,
        })
    lines = md_text.split('\n')
    in_code = False
    for row_label, col_header, val, unit, lineno, raw in _parse_md_tables(lines):
        if not _is_valid_label(row_label):
            continue
        if col_header.upper() in ('YOY', 'YOY增速', '增速', '同比', '变化', '趋势', '说明', '备注'):
            continue
        label = f"{row_label} · {col_header}" if col_header and col_header != row_label else row_label
        _add(label, val, unit, lineno, raw)
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            continue
        if in_code or stripped.startswith('> ') or re.match(r'^#{1,6}\s', stripped):
            continue
        if '|' in stripped:
            continue
        for m in _KV_LABEL_RE.finditer(stripped):
            label = m.group('label')
            val = _clean_num(m.group('num'))
            unit = (m.group('unit') or '').strip()
            _add(label, val, unit, lineno, stripped)
    return points

def sample_points(points: list, ratio: float = 0.15, seed: int = None) -> list:
    n = max(3, min(30, math.ceil(len(points) * ratio)))
    n = min(n, len(points))
    rng = Random(seed)
    sampled = rng.sample(points, n)
    return sorted(sampled, key=lambda p: p['line_number'])

_TOLERANCE = 0.01

def _pct_diff(reported: float, fetched: float) -> float:
    if reported == 0:
        return 0.0 if fetched == 0 else float('inf')
    return abs(reported - fetched) / abs(reported)

def render_verdict(results: list, report_name: str = "") -> dict:
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    print('=' * 70)
    print(f'{BOLD}报告数据抽检 — 准出/打回判决{RESET}')
    if report_name:
        print(f'报告：{report_name}')
    print('=' * 70)
    print()
    fail_items = []
    warn_items = []
    for item in results:
        label = item.get('label', '?')
        reported = float(item.get('reported_value', 0))
        unit = item.get('unit', '')
        fetched = item.get('fetched_value')
        source = item.get('fetched_source', '?')
        fetched2 = item.get('fetched_value2')
        source2 = item.get('fetched_source2', '')
        if fetched is None:
            print(f'  ⬜ [{item["id"]:>2}] {label[:35]:35s} {reported:>12.2f} {unit}  →  [未提供核验值，跳过]')
            continue
        fetched = float(fetched)
        diff1 = _pct_diff(reported, fetched)
        diff2 = None
        if fetched2 is not None:
            fetched2 = float(fetched2)
            diff2 = _pct_diff(reported, fetched2)
        pass1 = diff1 <= _TOLERANCE
        pass2 = (diff2 is None) or (diff2 <= _TOLERANCE)
        if pass1 and pass2:
            status = f'{GREEN}✅ 通过{RESET}'
            detail = f'{source}: {fetched:.2f} (偏差 {diff1*100:.2f}%)'
            if diff2 is not None:
                detail += f'  |  {source2}: {fetched2:.2f} (偏差 {diff2*100:.2f}%)'
        elif not pass1 and not pass2:
            status = f'{RED}❌ 不通过{RESET}'
            detail = f'{source}: {fetched:.2f} (偏差 {diff1*100:.2f}%)'
            if diff2 is not None:
                detail += f'  |  {source2}: {fetched2:.2f} (偏差 {diff2*100:.2f}%)'
            fail_items.append({
                'id': item['id'], 'label': label,
                'reported': reported, 'unit': unit,
                'fetched': fetched, 'source': source,
                'fetched2': fetched2, 'source2': source2,
                'diff1_pct': round(diff1 * 100, 2),
                'diff2_pct': round(diff2 * 100, 2) if diff2 is not None else None,
                'raw_text': item.get('raw_text', ''),
                'line_number': item.get('line_number', 0),
            })
        else:
            status = f'{YELLOW}⚠️  警告{RESET}'
            detail = f'{source}: {fetched:.2f} (偏差 {diff1*100:.2f}%)'
            if diff2 is not None:
                detail += f'  |  {source2}: {fetched2:.2f} (偏差 {diff2*100:.2f}%)'
            warn_items.append({
                'id': item['id'], 'label': label,
                'reported': reported, 'unit': unit,
                'diff1_pct': round(diff1 * 100, 2),
                'diff2_pct': round(diff2 * 100, 2) if diff2 is not None else None,
            })
        print(f'  {status} [{item["id"]:>2}] {label[:35]:35s}  报告: {reported:>12.2f} {unit}')
        print(f'              {" " * 38}{detail}')
    print()
    print('-' * 70)
    total = len([r for r in results if r.get('fetched_value') is not None])
    fail_count = len(fail_items)
    warn_count = len(warn_items)
    pass_count = total - fail_count - warn_count
    print(f'  抽检总数: {total}  |  通过: {GREEN}{pass_count}{RESET}  |  警告: {YELLOW}{warn_count}{RESET}  |  不通过: {RED}{fail_count}{RESET}')
    print()
    if fail_count == 0:
        print(f'{BOLD}{GREEN}【准出】所有抽检数据通过，报告可发布。{RESET}')
        verdict = 'PASS'
    else:
        print(f'{BOLD}{RED}【打回】{fail_count} 个数据点核验不通过，报告需修正后重审。{RESET}')
        print()
        print(f'{BOLD}打回原因：{RESET}')
        for fi in fail_items:
            print(f'  ❌ 第 {fi["line_number"]} 行 | {fi["label"]}')
            print(f'     报告值：{fi["reported"]} {fi["unit"]}')
            print(f'     {fi["source"]}：{fi["fetched"]}  (偏差 {fi["diff1_pct"]}%)')
            if fi.get('fetched2') is not None:
                print(f'     {fi["source2"]}：{fi["fetched2"]}  (偏差 {fi["diff2_pct"]}%)')
            print(f'     原文：{fi["raw_text"][:80]}')
            print()
        verdict = 'FAIL'
    if warn_count > 0:
        print(f'{YELLOW}注意：{warn_count} 个数据点两来源结果不一致，请人工复核口径差异。{RESET}')
    print('=' * 70)
    return {
        'verdict': verdict,
        'pass_count': pass_count,
        'warn_count': warn_count,
        'fail_count': fail_count,
        'total': total,
        'fail_items': fail_items,
        'warn_items': warn_items,
    }

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    parser = argparse.ArgumentParser(description='Report Audit Tool')
    sub = parser.add_subparsers(dest="command")
    ext = sub.add_parser("extract", help="从报告中提取数据点")
    ext.add_argument("--report", required=True)
    ext.add_argument("--dry-run", action="store_true")
    ver = sub.add_parser("verdict", help="输出准出/打回判决")
    ver.add_argument("--results", required=True)
    ver.add_argument("--report-name", default="")
    args = parser.parse_args()
    if args.command == "extract":
        report_path = args.report
        if not os.path.exists(report_path):
            print(f"❌ 报告文件不存在: {report_path}")
            sys.exit(1)
        with open(report_path, "r", encoding="utf-8") as f:
            text = f.read()
        points = extract_data_points(text)
        print(f"共提取 {len(points)} 个数据点")
        sampled = sample_points(points, 0.15)
        print(f"随机抽样 {len(sampled)} 个 (15%)")
        print()
        print(json.dumps(sampled, ensure_ascii=False, indent=2))
        if args.dry_run:
            sys.exit(0)
        print()
        print("=" * 70)
        print("抽检清单已输出。请对每个数据点补充 fetched_value 和 fetched_source，")
        print("然后执行: python3 tools/report_audit.py verdict --results '...'")
    elif args.command == "verdict":
        results = json.loads(args.results)
        render_verdict(results, args.report_name)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()