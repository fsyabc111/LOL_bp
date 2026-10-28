"""Replay every game through the draft engine and summarise rule findings.

Run: python3 -m lolbp.check   (needs the local SQLite from scripts/build_dataset.py)
"""
from collections import Counter
import json

from .repository import Repository


def main():
    repo = Repository()
    sources, findings, examples = Counter(), Counter(), []
    for gameid in sorted(repo.games):
        game = repo.games[gameid]
        detail = repo.game_detail(gameid)
        sources[(game['year'], detail['sequence_source']['type'])] += 1
        for finding in detail['replay_findings']:
            for code in finding['reasons'] + finding.get('warnings', []):
                findings[(game['year'], game['league'], detail['rules']['fearless']['status'], code)] += 1
            if finding['reasons'] and len(examples) < 20:
                examples.append({'gameid': gameid, 'step': finding['step'], 'reasons': finding['reasons']})
    print(json.dumps({'games': len(repo.games), 'series': len(repo.series),
                      'irregular_series': sum(s['numbering'] != 'complete' for s in repo.series.values()),
                      'sequence_sources': {f'{y}/{t}': n for (y, t), n in sorted(sources.items())},
                      'findings': {'/'.join(k): n for k, n in sorted(findings.items())},
                      'illegal_examples': examples}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
