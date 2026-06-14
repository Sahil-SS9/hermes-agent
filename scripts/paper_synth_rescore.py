#!/usr/bin/env python3
"""Quick fix: fetch HF Daily Papers with correct parsing, re-score with fallback."""
import json, sys
from urllib.request import Request, urlopen
from datetime import datetime, timezone, timedelta

# Load existing scored papers
with open('/home/kensei/.hermes/runbooks/paper-synthesis/papers-20260613-0632.json') as f:
    data = json.load(f)

papers = data['papers']
arxiv_ids = {p['arxiv_id'] for p in papers}

# Fetch HF Daily
url = "https://huggingface.co/api/daily_papers?limit=30"
req = Request(url, headers={'User-Agent': 'KenseiAgent/2.1'})
hf_data = json.loads(urlopen(req, timeout=30).read().decode('utf-8'))

hf_papers = []
hf_ids = {}
for p in hf_data:
    paper_id = p.get('paper', {}).get('id', '')
    arxiv_id = paper_id.split('v')[0] if 'v' in paper_id else paper_id
    title = p.get('paper', {}).get('title', '')
    published = p.get('paper', {}).get('publishedAt', '')[:10]
    upvotes = p.get('paper', {}).get('upvotes', 0)
    
    hf_papers.append({
        'arxiv_id': arxiv_id,
        'title': title,
        'published': published,
        'upvotes': upvotes,
    })
    hf_ids[arxiv_id] = True

print(f"HF Daily papers found: {len(hf_papers)}")

# Cross-ref with our papers
hf_in_ours = [p for p in hf_papers if p['arxiv_id'] in arxiv_ids]
hf_not_in_ours = [p for p in hf_papers if p['arxiv_id'] not in arxiv_ids]
print(f"HF papers in our arXiv set: {len(hf_in_ours)}")
print(f"HF papers NOT in our arXiv set: {len(hf_not_in_ours)}")

for p in hf_in_ours:
    print(f"  MATCH: {p['arxiv_id']} — {p['title'][:80]} (↑{p['upvotes']})")

print("\n── Re-scoring with fallback quality weight (0.7, SemScholar unavailable) ──")

# Now re-score with fallback qw=0.7, and check HF cross-ref
D14_CUTOFF = datetime.now(timezone.utc) - timedelta(days=14)

rescored = []
for p in papers:
    aid = p['arxiv_id']
    base_rel = p['base_relevance']
    
    # Use fallback quality weight since Semantic Scholar was rate-limited
    qw = 0.7
    
    # If HF featured, bump to 0.9
    if aid in hf_ids:
        qw = 0.9
        p['hf_featured'] = True
    
    imp = p.get('implementation_multiplier', 1.0)
    final_score = round(base_rel * qw * imp, 2)
    
    if final_score >= 5.5:
        action = 'write_now'
    elif final_score >= 3.0:
        action = 'ask_first'
    elif final_score >= 1.5:
        action = 'file'
    else:
        action = 'skip'
    
    p['quality_weight'] = qw
    p['final_score'] = final_score
    p['action'] = action
    p['fallback_applied'] = True
    rescored.append(p)

rescored.sort(key=lambda x: x['final_score'], reverse=True)

# Summary
write_now = [p for p in rescored if p['action'] == 'write_now']
ask_first = [p for p in rescored if p['action'] == 'ask_first']
file_only = [p for p in rescored if p['action'] == 'file']
skipped = [p for p in rescored if p['action'] == 'skip']

print(f"Write Now (≥5.5): {len(write_now)}")
print(f"Ask First (3.0-5.4): {len(ask_first)}")
print(f"File (1.5-2.9): {len(file_only)}")
print(f"Skip (<1.5): {len(skipped)}")

print("\n── Ask First papers ──")
for p in ask_first:
    hf_flag = "★HF" if p['hf_featured'] else ""
    print(f"  {p['final_score']:.1f} {hf_flag} | {p['arxiv_id']}: {p['title'][:80]}")

print("\n── Top File papers ──")
for p in file_only[:10]:
    hf_flag = "★HF" if p['hf_featured'] else ""
    print(f"  {p['final_score']:.1f} {hf_flag} | {p['arxiv_id']}: {p['title'][:80]}")

# Save updated scoring
data['papers'] = rescored
data['ask_first_count'] = len(ask_first)
data['file_count'] = len(file_only)
data['write_now_count'] = len(write_now)
data['skip_count'] = len(skipped)
data['hf_daily_papers'] = len(hf_papers)
data['hf_matched'] = len(hf_in_ours)
data['hf_new'] = len(hf_not_in_ours)
data['fallback_applied'] = True

out_path = '/home/kensei/.hermes/runbooks/paper-synthesis/papers-scored-20260613.json'
with open(out_path, 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"\nSaved re-scored data to {out_path}")
