"""Champion changes from patch notes, as known at a game's date.

Records come from data/curated/patch_changes.jsonl (scripts/collect_leaguepedia_patches.py) and OE patch names are
translated with data/curated/patch_mapping.json, both from Leaguepedia. For a game on patch P, the "fresh" changes
are those of every patch page after the previous patch professionals played (before the game's date) up to and
including P, so patches the leagues skipped still count; blocks dated after the game (mid-patch updates) do not.
"""
import json
from pathlib import Path
import re

CHANGES = 'data/curated/patch_changes.jsonl'
MAPPING = 'data/curated/patch_mapping.json'
PRO = re.compile(r'\bpro\b|pro play|competitive|professional|esports|high[- ]level|elite')


def order_key(name):
    """Release order of Leaguepedia patch names: 25.S1.1 < 25.S1.3 < 25.04 < ... < 26.01."""
    year, _, rest = name.partition('.')
    if rest.startswith('S1.'): return (int(year), 0, int(rest[3:]))
    return (int(year), 1, int(rest))


class PatchNotes:
    def __init__(self, root):
        changes, mapping = Path(root) / CHANGES, Path(root) / MAPPING
        self.available = changes.exists() and mapping.exists()
        self.records = [json.loads(line) for line in changes.read_text().splitlines() if line.strip()] if self.available else []
        self.mapping = {k: v['leaguepedia'] for k, v in json.loads(mapping.read_text())['mapping'].items()} if self.available else {}
        self.pages = sorted({r['patch'] for r in self.records}, key=order_key)

    def fresh(self, history, gameid):
        """(champion column -> {'net': +n buffs / -n nerfs, 'records': [...]}, Leaguepedia patches covered) for a game."""
        game = history.games[gameid]
        current = self.mapping.get(game['patch'])
        if current is None: return {}, []
        previous = None
        for g in reversed(history.order):  # most recent earlier-dated game on a different patch
            if g['date'] < game['date'] and g['patch'] != game['patch'] and g['patch'] in self.mapping:
                if order_key(self.mapping[g['patch']]) < order_key(current): previous = self.mapping[g['patch']]; break
        covered = [p for p in self.pages if order_key(p) <= order_key(current) and (previous is None or order_key(p) > order_key(previous))]
        if previous is None: covered = [current] if current in self.pages else []
        out = {}
        for r in self.records:
            if r['patch'] not in covered or (r['date'] and r['date'] > game['date']): continue
            col = history.column.get(r['champion_id'])
            if col is None: continue
            entry = out.setdefault(col, {'net': 0, 'pro': False, 'records': []})
            entry['net'] += {'buff': 1, 'nerf': -1}.get(r['direction'], 0); entry['records'].append(r)
            entry['pro'] = entry['pro'] or bool(PRO.search(r['context'].lower()))  # notes that name pro / competitive play
        return out, covered
