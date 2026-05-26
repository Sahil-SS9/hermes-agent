#!/usr/bin/env python3
"""
Wiki On Complete — post-processing step that reads recently completed kanban tasks
and updates the corresponding LLM-WIKI repo entry with 'implemented' adoption_status.

Runs after the quality gate as a no_agent=true cron at X:15 past each hour.

Scans kanban tasks completed in the last 2 hours. If the task result or body
references a wiki repo page (via "wiki:" or "repo:" prefix), updates that page's
frontmatter to adoption_status: implemented and tags: [implemented].
"""
import sqlite3, json, re, os, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

KANBAN_DB = Path("/home/kensei/.hermes/kanban.db")
WIKI_REPOS = Path("/home/kensei/wiki/repos")

TZ = timezone(timedelta(hours=1))
now = datetime.now(TZ)
cutoff = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp())

def find_wiki_reference(text):
    """Extract repo short-name from text matching wiki:short-name or repo:owner/repo."""
    if not text:
        return None
    m = re.search(r'wiki:(\S+)', text)
    if m:
        return m.group(1)
    m = re.search(r'repo:(\S+)', text)
    if m:
        full = m.group(1)
        short = full.split('/')[-1] if '/' in full else full
        return short.lower()
    return None

def update_wiki_page(repo_name):
    """Update a wiki repo page's frontmatter to mark it as implemented."""
    page_path = WIKI_REPOS / f"{repo_name}.md"
    if not page_path.exists():
        print(f"SKIP: wiki page not found: {page_path}")
        return False
    
    content = page_path.read_text()
    
    # Check if already implemented
    if 'adoption_status: implemented' in content:
        print(f"SKIP: {repo_name} already implemented")
        return False
    
    # Update frontmatter adoption_status
    updated = re.sub(
        r'(adoption_status:\s*)\S+',
        r'\1implemented',
        content
    )
    
    # Add implemented tag if not present
    if 'implemented' not in updated:
        updated = re.sub(
            r'(tags:\s*\[.*?)\]',
            r'\1, implemented]',
            updated
        )
    
    updated = re.sub(
        r'(updated:\s*)\S+',
        f'\\1{now.strftime("%Y-%m-%d")}',
        updated
    )
    
    # Add what_we_did note if empty
    if 'what_we_did: ""' in updated:
        updated = updated.replace(
            'what_we_did: ""',
            f'what_we_did: "Built and deployed via kanban pipeline. Completed {now.strftime("%Y-%m-%d")}."'
        )
    
    page_path.write_text(updated)
    print(f"UPDATED: {repo_name} → adoption_status: implemented")
    return True

def main():
    if not KANBAN_DB.exists():
        print("SKIP: kanban DB not found")
        return
    
    conn = sqlite3.connect(str(KANBAN_DB))
    cur = conn.cursor()
    
    # Find tasks completed in the last 2 hours with wiki references
    cur.execute("""
        SELECT id, title, result, body
        FROM tasks
        WHERE status = 'done'
          AND completed_at >= ?
          AND (result LIKE '%wiki:%' OR result LIKE '%repo:%' 
               OR body LIKE '%wiki:%' OR body LIKE '%repo:%')
        ORDER BY completed_at DESC
    """, (cutoff,))
    
    tasks = cur.fetchall()
    if not tasks:
        print("SILENT: no completed tasks with wiki references")
        conn.close()
        return
    
    updated_count = 0
    for task_id, title, result, body in tasks:
        ref = find_wiki_reference(result) or find_wiki_reference(body) or find_wiki_reference(title)
        if ref and update_wiki_page(ref):
            updated_count += 1
    
    conn.close()
    
    if updated_count > 0:
        print(f"DONE: updated {updated_count} wiki repo pages to 'implemented'")
    else:
        print("SILENT: no wiki pages updated (references found but pages missing or already implemented)")

if __name__ == "__main__":
    main()