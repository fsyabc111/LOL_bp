"""Read-only access to the curated dataset for replay: games, series, sequences, rules, champions.

Sequence source per game: Leaguepedia per-step evidence when it agrees with OE final sets, else the
OE per-team columns laid out on the template (measured agreement in oe-order-accuracy.json). Every
rule field carries a status: observed (rulebook), practice_observed, assumed or unknown.
"""
from collections import defaultdict
import datetime
import json
from pathlib import Path
import sqlite3
import sys

from . import draft

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from assemble_sample import applicable_rules  # noqa: E402  (shared rule-applicability logic)

DB = 'data/processed/lol_bp.sqlite3'
SEQUENCES = 'data/curated/bp_sequences.jsonl'
CONTEXT = 'data/curated/match_context.jsonl'
RESTRICTIONS = 'data/curated/event_restrictions.jsonl'
RULES = 'data/curated/rules.json'
ACCURACY = 'data/curated/oe-order-accuracy.json'
AVAILABILITY = 'data/curated/champion_availability.json'
CATALOG_VERSION = '16.20.1'
LEAGUES = ('LCK', 'LPL', 'WLDs')
SERIES_GAP_HOURS = 6
ICON_URL = 'https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{key}.png'


def plain(name):
    return ''.join(ch for ch in (name or '').casefold() if ch.isalnum())


def parse_time(value):
    return datetime.datetime.strptime(value[:19], '%Y-%m-%d %H:%M:%S')


class Repository:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self._load_champions()
        self.rules = json.loads((self.root / RULES).read_text())
        self.template = next(t for t in self.rules['templates'] if t['id'] == 'snake_20')
        path = self.root / ACCURACY
        self.accuracy = json.loads(path.read_text())['overall'] if path.exists() else None
        path = self.root / AVAILABILITY
        self.released = ({p: frozenset(v['champion_ids']) & frozenset(self.champions) for p, v in json.loads(path.read_text())['patches'].items()}
                         if path.exists() else {})
        self._load_games()
        self._load_evidence()
        self._group_series()

    # -- loading -------------------------------------------------------------------------
    def _load_champions(self):
        base = self.root / 'data/curated/static' / CATALOG_VERSION
        en = json.loads((base / 'en_US/champion.json').read_text())['entities']
        zh = {e['id']: e for e in json.loads((base / 'zh_CN/champion.json').read_text())['entities']}
        self.champions, self.aliases = {}, {}
        for entity in en:
            cid = str(entity['id'])
            self.champions[cid] = {'id': cid, 'key': entity['source_key'], 'name': entity['name'],
                                   'name_zh': zh.get(entity['id'], {}).get('title') or entity['name'],
                                   'icon': ICON_URL.format(version=CATALOG_VERSION, key=entity['source_key'])}
            for alias in [entity['name'], entity['source_key']] + entity.get('aliases', []): self.aliases[plain(alias)] = cid

    def champion_id(self, name):
        if name is None: return None
        return self.aliases.get(plain(name), 'unknown:' + name)

    def _load_games(self):
        connection = sqlite3.connect(self.root / DB)
        self.games = {}
        placeholders = ','.join('?' * len(LEAGUES))
        for gameid, league, date, patch, number, structural, winner in connection.execute(
                f'SELECT gameid, league_raw, date_raw, patch_raw, game_number_raw, structural_valid, winner_side FROM games WHERE league_raw IN ({placeholders})', LEAGUES):
            self.games[gameid] = {'gameid': gameid, 'league': league, 'date': date, 'year': date[:4], 'patch': patch,
                                  'game_number': int(number) if (number or '').isdigit() else None,
                                  'structural_valid': bool(structural), 'winner_side': winner, 'teams': {}}
        for gameid, side, name, first, result, picks, bans in connection.execute(
                'SELECT gameid, side, team_name, first_pick_raw, result, picks_raw_json, bans_raw_json FROM team_drafts'):
            if gameid in self.games:
                self.games[gameid]['teams'][side] = {'side': side, 'name': name, 'first_pick': first == '1', 'result': result,
                                                     'picks': json.loads(picks), 'bans': json.loads(bans)}
        connection.close()
        self.games = {k: g for k, g in self.games.items() if g['structural_valid'] and set(g['teams']) == {'Blue', 'Red'}}

    def _load_evidence(self):
        self.evidence = defaultdict(list)
        path = self.root / SEQUENCES
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    item = json.loads(line); self.evidence[item['oe_gameid']].append(item)
        self.restrictions = defaultdict(list)
        path = self.root / RESTRICTIONS
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    item = json.loads(line); self.restrictions[item['oe_gameid']].append(item)
        self.contexts = {}
        path = self.root / CONTEXT
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    item = json.loads(line); self.contexts[item['oe_gameid']] = item

    def _group_series(self):
        """Group by the series key embedded in gameids like '11896-11896_game_1' when present;
        otherwise chain a team pair's games in one league less than SERIES_GAP_HOURS apart."""
        by_pair = defaultdict(list)
        for game in self.games.values():
            pair = tuple(sorted(t['name'] for t in game['teams'].values()))
            prefix, sep, _ = game['gameid'].partition('_game_')
            by_pair[(game['league'], pair, prefix if sep else None)].append(game)
        self.series = {}
        for (league, pair, _), games in by_pair.items():
            games.sort(key=lambda g: (g['date'], g['game_number'] or 0))
            current = []
            for game in games:
                if current and (parse_time(game['date']) - parse_time(current[-1]['date'])).total_seconds() > SERIES_GAP_HOURS * 3600:
                    self._add_series(league, pair, current); current = []
                current.append(game)
            if current: self._add_series(league, pair, current)

    def _add_series(self, league, pair, games):
        series_id = f"{league}:{games[0]['gameid']}"
        numbers = [g['game_number'] for g in games]
        complete = numbers == list(range(1, len(games) + 1))
        self.series[series_id] = {'series_id': series_id, 'league': league, 'year': games[0]['year'], 'date': games[0]['date'][:10],
                                  'teams': list(pair), 'gameids': [g['gameid'] for g in games],
                                  'numbering': 'complete' if complete else 'gaps_or_duplicates'}
        for game in games: game['series_id'] = series_id

    # -- per-game resolution -------------------------------------------------------------
    def _tournament(self, gameid):
        if gameid in self.contexts: return self.contexts[gameid].get('tournament', ''), self.contexts[gameid].get('evidence_status')
        items = self.evidence.get(gameid, [])
        if len(items) == 1: return items[0]['source']['title'].removesuffix('/Picks and Bans'), 'source_record_verified'
        return '', None

    def sequence(self, gameid):
        """Return (steps with champion ids, first_selection_side, source descriptor)."""
        game = self.games[gameid]
        items = self.evidence.get(gameid, [])
        if len(items) == 1 and self._evidence_matches_oe(items[0], game):
            item = items[0]
            source = {'type': 'leaguepedia', 'locator': item['source']['locator'], 'revid': item['source']['revid'],
                      'unordered_step_groups': item.get('unordered_step_groups', [])}
            steps = [{**s, 'champion': self.champion_id(s['champion'])} for s in item['steps']]
            return steps, item['first_selection_side'], source
        first = [side for side, t in game['teams'].items() if t['first_pick']]
        first_side = first[0] if len(first) == 1 else 'Blue'
        columns = {side: {'pick': list(t['picks']), 'ban': list(t['bans'])} for side, t in game['teams'].items()}
        steps = []
        for slot in draft.slots_from_template(self.template, first_side):
            steps.append({'step': slot.step, 'side': slot.side, 'action': slot.action,
                          'champion': self.champion_id(columns[slot.side][slot.action].pop(0))})
        source = {'type': 'oe_columns', 'note': 'OE per-team columns on snake_20; order agreement measured against Leaguepedia',
                  'measured_agreement': (self.accuracy or {}).get('equal_modulo_unordered_groups_rate'),
                  'first_selection_from': 'oe_firstPick' if len(first) == 1 else 'unknown_defaulted_blue',
                  'conflict': 'leaguepedia_disagrees_with_oe_sets' if items else None}
        return steps, first_side, source

    def _evidence_matches_oe(self, item, game):
        for side, team in game['teams'].items():
            for action, names in (('pick', team['picks']), ('ban', team['bans'])):
                ours = sorted(str(self.champion_id(s['champion'])) for s in item['steps'] if s['side'] == side and s['action'] == action)
                if ours != sorted(str(self.champion_id(n)) for n in names): return False
        return True

    def resolve_rules(self, gameid, fearless_override=None):
        game = self.games[gameid]
        tournament, evidence_status = self._tournament(gameid)
        context = {'tournament': tournament, 'evidence_status': evidence_status}
        candidates = applicable_rules({'league_raw': game['league'], 'date_raw': game['date']}, context, self.rules)
        by_id = {r['rule_id']: r for r in self.rules['rules']}
        usable = [by_id[c['rule_id']] for c in candidates if c['applicability_status'] in ('observed', 'inferred')]
        def documented(field):
            """Prefer an observed rulebook value, then an inferred one; return (value, status, rule_id)."""
            for wanted in ('observed', 'inferred'):
                for rule in usable:
                    value = rule.get(field, {})
                    if value.get('status') == wanted and value.get('value') is not None: return value['value'], wanted, rule['rule_id']
            return None, None, None
        template, status, rule_id = documented('draft_template')
        template_field = ({'value': template, 'status': status, 'source': rule_id} if template else
                          {'value': 'snake_20', 'status': 'practice_observed',
                           'source': 'Leaguepedia per-step tables: all 2,376 linked 2024-2026 games follow snake_20; rulebook not obtained'})
        scope, status, rule_id = documented('cross_game_ban_scope')
        if scope:
            fearless = {'value': draft.FEARLESS_PICKS_BOTH if scope == 'picks_by_both_teams_for_remainder_of_match' else scope,
                        'status': status, 'source': rule_id}
        elif int(game['year']) >= 2025:
            fearless = {'value': draft.FEARLESS_PICKS_BOTH, 'status': 'assumed',
                        'source': 'Riot 2025 Fearless announcements (background evidence); event rulebook not obtained'}
        else:
            fearless = {'value': draft.FEARLESS_NONE, 'status': 'assumed',
                        'source': 'pre-2025 tournament draft; repeated picks observed across series games'}
        if fearless_override in (draft.FEARLESS_PICKS_BOTH, draft.FEARLESS_NONE):
            fearless = {'value': fearless_override, 'status': 'user_assumption', 'source': 'branch setting', 'default': fearless}
        disabled, status, rule_id = documented('event_disabled_champions')
        listed = self.restrictions.get(gameid, [])
        if disabled is not None:
            disabled_field = {'value': disabled, 'status': status, 'source': rule_id}
        elif len(listed) == 1:
            item = listed[0]
            disabled_field = {'value': item['disabled'], 'status': 'community_listed',
                              'source': f"Leaguepedia SetPatch: {item['source']['locator']}", 'listed_patch': item['listed_patch'],
                              'hotfix': item['hotfix']}
        else:
            disabled_field = {'value': [], 'status': 'unknown' if not listed else 'conflicting_sources',
                              'source': 'no event-disabled list linked to this game; nothing is blocked'}
        return {'tournament': tournament or None, 'candidate_rules': candidates, 'template': template_field,
                'fearless': fearless, 'disabled_champions': disabled_field}

    def series_context(self, gameid):
        game = self.games[gameid]
        series = self.series[game['series_id']]
        index = series['gameids'].index(gameid)
        prior = series['gameids'][:index]
        consumed = []
        for prior_id in prior:
            steps, _, _ = self.sequence(prior_id)
            consumed += [s['champion'] for s in steps if s['action'] == 'pick']
        expected = list(range(1, index + 1))
        numbers = [self.games[g]['game_number'] for g in prior]
        return {'series_id': series['series_id'], 'position': index + 1, 'prior_gameids': prior, 'consumed': sorted(set(consumed)),
                'prior_status': 'complete' if numbers == expected else 'incomplete_or_irregular'}

    def draft_rules(self, gameid, fearless_override=None):
        _, first_side, _ = self.sequence(gameid)
        resolved = self.resolve_rules(gameid, fearless_override)
        context = self.series_context(gameid)
        disabled = frozenset(self.champion_id(name) for name in resolved['disabled_champions']['value'] or [])
        rules = draft.DraftRules(slots=draft.slots_from_template(self.template, first_side), fearless=resolved['fearless']['value'],
                                 consumed=frozenset(context['consumed']), disabled=disabled,
                                 known=frozenset(self.champions), released=self.released.get(self.games[gameid]['patch'], frozenset()))
        return rules, resolved, context

    def game_detail(self, gameid, fearless_override=None):
        game = self.games[gameid]
        steps, first_side, source = self.sequence(gameid)
        rules, resolved, context = self.draft_rules(gameid, fearless_override)
        _, findings = draft.replay(rules, steps)
        return {'game': {k: v for k, v in game.items() if k != 'teams'},
                'teams': {side: {'name': t['name'], 'result': t['result']} for side, t in game['teams'].items()},
                'first_selection_side': first_side, 'sequence': steps, 'sequence_source': source,
                'rules': resolved, 'series': context, 'replay_findings': findings}

    def list_series(self, league=None, year=None, query=None, limit=200):
        items = [s for s in self.series.values()
                 if (not league or s['league'] == league) and (not year or s['year'] == year)
                 and (not query or any(query.casefold() in t.casefold() for t in s['teams']))]
        items.sort(key=lambda s: s['date'], reverse=True)
        out = []
        for s in items[:limit]:
            games = [{'gameid': g, 'game_number': self.games[g]['game_number'], 'winner_side': self.games[g]['winner_side'],
                      'blue': self.games[g]['teams']['Blue']['name'], 'red': self.games[g]['teams']['Red']['name'],
                      'patch': self.games[g]['patch'], 'has_leaguepedia': len(self.evidence.get(g, [])) == 1} for g in s['gameids']]
            out.append({**s, 'games': games})
        return out
