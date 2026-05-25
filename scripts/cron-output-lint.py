#!/usr/bin/env python3
"""Lint active Discord cron prompts/scripts for output-format regressions.

Default mode checks current prompts + scripts only. Use --latest to include the latest
historical cron output, which may still fail until a cron naturally reruns.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

JOBS = Path('/home/kensei/.hermes/cron/jobs.json')
SCRIPTS = Path('/home/kensei/.hermes/scripts')
OUTPUT = Path('/home/kensei/.hermes/cron/output')

BAD_PATTERNS = {
    'telegram_html_tags': re.compile(r'<(?:b|code|blockquote)(?:\s|>|/)', re.I),
    'raw_html_visible': re.compile(r'<!doctype html|<html[\s>]|<style[\s>]', re.I),
    'process_narration_literal': re.compile(r"Now I'll|I will write|I'll write", re.I),
    'memory_leak_literal': re.compile(r'<memory-context>|Mnemosyne Context', re.I),
}

# Visible-output-only check. This is intentionally NOT applied to prompts/scripts,
# because prompts need to mention examples and HTML attachment internals.
BAD_VISIBLE_DATE = re.compile(
    r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+'
    r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
    r'|\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    r'|\d{4}-\d{2}-\d{2}'
)

FIRST_LINE_TS = re.compile(r'^.+ · \d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$')


def scan_text(text: str) -> list[str]:
    return [name for name, rx in BAD_PATTERNS.items() if rx.search(text or '')]


def latest_response(job_id: str) -> str:
    out_dir = OUTPUT / job_id
    if not out_dir.exists():
        return ''
    files = sorted(out_dir.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return ''
    text = files[0].read_text(errors='ignore')
    if '## Response' in text:
        return text.split('## Response', 1)[1].strip()
    if '\n---\n\n' in text:
        return text.split('\n---\n\n', 1)[1].strip()
    # Failed run logs include prompt summaries/errors. Don't treat them as delivered output.
    if '(FAILED)' in text[:200] or '**Status:** script failed' in text:
        return ''
    return text.strip()


def scan_visible_output(text: str) -> list[str]:
    if not text:
        return []
    if text.strip() == '[SILENT]':
        return []
    hits = scan_text(text)
    if BAD_VISIBLE_DATE.search(text):
        hits.append('non_uk_visible_date')
    first = next((line.strip() for line in text.splitlines() if line.strip()), '')
    if first and not first.startswith('#') and not FIRST_LINE_TS.match(first):
        # Allow local-only / failure metadata logs to pass; this linter targets delivered summaries.
        hits.append('first_line_missing_ddmmyy_hhmmss')
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--latest', action='store_true', help='also scan latest historical output files')
    args = parser.parse_args()

    data = json.loads(JOBS.read_text())
    rows = []
    for job in data.get('jobs', []):
        if not job.get('enabled'):
            continue
        deliver = job.get('deliver') or ''
        if not (deliver.startswith('discord') or deliver in {'origin', 'all'}):
            continue

        script_hits: list[str] = []
        script = job.get('script')
        if script:
            script_path = SCRIPTS / script
            if script_path.exists():
                script_hits = scan_text(script_path.read_text(errors='ignore'))

        prompt_hits = scan_text(job.get('prompt') or '')
        latest_hits = scan_visible_output(latest_response(job.get('id', ''))) if args.latest else []
        if prompt_hits or script_hits or latest_hits:
            rows.append({
                'job': job.get('name'),
                'id': job.get('id'),
                'mode': 'no_agent' if job.get('no_agent') else 'llm',
                'prompt': prompt_hits,
                'script': script_hits,
                'latest_output': latest_hits,
            })

    print(json.dumps({'issues': rows, 'count': len(rows), 'latest_checked': args.latest}, indent=2))
    return 1 if rows else 0


if __name__ == '__main__':
    raise SystemExit(main())
