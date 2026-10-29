"""KR high-elo solo queue aggregates (scripts/collect_kr_soloq.py) as known at a game's date.

For a game on Leaguepedia patch P, presence is (picks + bans) per sampled game over P's solo queue days strictly
before the game's date; the change compares it with the previous patch that has data (its whole window, which
ended before P was released). Patches without a file give no signal.
"""
import json
from pathlib import Path

from .patches import order_key

DIRECTORY = 'data/curated/kr_soloq'


class SoloQueue:
    def __init__(self, root):
        self.patches = {}
        for path in sorted(Path(root, DIRECTORY).glob('*.json')):
            data = json.loads(path.read_text())
            if 'days' in data: self.patches[data['patch']] = data
        self.order = sorted(self.patches, key=order_key)

    def presence(self, patch, before=None):
        """{champion id: (picks + bans) / games} over the patch's days before `before` (all days if None), and games."""
        data = self.patches.get(patch)
        if not data: return {}, 0
        games, counts = 0, {}
        for day, v in data['days'].items():
            if before is not None and day >= before: continue
            games += v['games']
            for c, (picks, bans) in v['champions'].items(): counts[c] = counts.get(c, 0) + picks + bans
        return ({c: n / games for c, n in counts.items()} if games else {}), games

    def previous(self, patch):
        earlier = [p for p in self.order if order_key(p) < order_key(patch)]
        return earlier[-1] if earlier else None
