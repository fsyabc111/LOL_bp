"""Candidate comparison for the side to act: several dimensions side by side, no single "best" score.

Backtests (scripts/evaluate_draft_factors.py) found that none of these dimensions separates winners from losers
on its own, so the output is a structured comparison for the user's judgment, never a win probability:

- habit: how likely professional teams in this situation take it (the next-action model)
- player: the acting side's player in the role it would fill, and how much that player uses it
- lane: expected 15-minute gold against the opponent's laner in that role (or its lane average if none yet)
- profile: frontline and damage mix after the pick
- responses: the opponent's most likely next actions if it is picked (the next-action model again)
- for bans: how much the opponent would want it now, their player's comfort, the lane threat to our picks,
  and whether we would want it ourselves (opportunity cost)

Candidates are the model's top choices plus a few the dimensions single out (player comfort for picks, the
opponent's most wanted for bans), each tagged with why it is listed.
"""
from . import draft
from .composition import assign_roles
from .history import ROLES, other

ROLE_ZH = {'top': '上单', 'jng': '打野', 'mid': '中单', 'bot': '下路', 'sup': '辅助'}


class Recommender:
    def __init__(self, predictor, composer):
        self.predictor, self.composer = predictor, composer

    def recommend(self, gameid, actions, fearless_override=None, version=None, top=8, extra=3):
        predictor, composer = self.predictor, self.composer
        model = predictor.version(version)
        ranking = predictor.rank(gameid, actions, model, fearless_override)
        if ranking is None: return None
        slot, context, history = ranking.slot, ranking.context, predictor.history
        side, opp = slot.side, other(slot.side)
        own_picks, opp_picks = context.picks(side, actions), context.picks(opp, actions)
        lane = history.lane_averages(context.cutoff, composer.tau, composer.settings['smoothing']['champion'])
        listed = [(c, 'model') for c in ranking.champions[:top]]
        rules, _, _ = predictor.repo.draft_rules(gameid, fearless_override)
        series_follows = 'simulation' not in predictor.repo.games[gameid]  # a simulation is a single game: nothing to carry over
        own_want = predictor.rank_as(gameid, actions, model, side, 'pick', fearless_override)
        opp_want = predictor.rank_as(gameid, actions, model, opp, 'pick', fearless_override)
        if slot.action == 'pick' and not context.sides[side]['generic']:  # a generic side has no players to be comfortable
            comfort = sorted(ranking.champions, key=lambda c: -self._comfort(context, side, ranking.open_own, history.column[c])[3])
            listed += [(c, 'player') for c in comfort if c not in dict(listed)][:extra]
        elif opp_want:
            listed += [(c, 'deny') for c in opp_want.champions if c not in dict(listed) and c in ranking.position][:extra]
        out = []
        for c, why in listed:
            col = history.column[c]; rank, prob = ranking.rank_of(c)
            item = {'champion': c, 'listed_for': why, 'habit': {'rank': rank, 'probability': round(prob, 4)}}
            if slot.action == 'pick':
                role, share, name, _ = self._comfort(context, side, ranking.open_own, col)
                if not context.sides[side]['generic']: item['player'] = {'role': role, 'name': name, 'share': round(share, 4)}
                item['lane'] = self._lane(lane, role, col, opp_picks, context, composer, history)
                before, after = composer.profile(own_picks), composer.profile(own_picks + [col])
                item['profile'] = {'frontline': [before.get('frontline', 0), after['frontline']],
                                   'magic_share': [before.get('magic_share'), after['magic_share']]}
                item['responses'] = self._responses(gameid, actions, slot, c, model, fearless_override)
                item['fearless_cost'] = series_follows and rules.fearless == draft.FEARLESS_PICKS_BOTH
            else:
                found = opp_want and opp_want.rank_of(c)
                item['deny'] = found and {'rank': found[0], 'probability': round(found[1], 4)}
                role, share, name, _ = self._comfort(context, opp, ranking.open_opp, col)
                if not context.sides[opp]['generic']: item['opponent_player'] = {'role': role, 'name': name, 'share': round(share, 4)}
                item['threat'] = self._lane(lane, role, col, own_picks, context, composer, history)
                mine = own_want and own_want.rank_of(c)
                item['own_interest'] = mine and {'rank': mine[0], 'probability': round(mine[1], 4)}
            out.append(item)
        return {'model': model.summary(), 'slot': {'step': slot.step, 'side': side, 'action': slot.action, 'phase': ranking.phase,
                                                   'team': context.sides[side]['name'], 'opponent': context.sides[opp]['name']},
                'cutoff': context.cutoff, 'candidates': out, 'notes': context.notes(side)}

    @staticmethod
    def _comfort(context, side, opens, col):
        """Role the champion would most likely fill for `side`, that player's (smoothed) share of games on it, the
        player's name, and the share weighted by how open that role still is (for ranking comfort picks)."""
        players = context.sides[side]['players']
        r = max(range(len(ROLES)), key=lambda r: opens[r] * context.role_prob[col][r])
        share = players[r]['share'][col]
        return ROLES[r], share, players[r]['name'], opens[r] * share

    @staticmethod
    def _lane(lane, role, col, facing_picks, context, composer, history):
        """Lane expectation in `role` against the champion the other side has there (if any), with sample sizes."""
        r = ROLES.index(role)
        facing = dict(assign_roles(context.role_prob, facing_picks)[0]).get(role)
        games = composer.champion(col, role, context.cutoff)['lane_games']
        out = {'role': role, 'strength': round(lane[r][col]), 'games': games, 'enough': games >= composer.settings['min_games']['champion']}
        if facing is not None:
            out.update(against=history.champions[facing], edge=round(lane[r][col] - lane[r][facing]),
                       against_games=composer.champion(facing, role, context.cutoff)['lane_games'])
            out['enough'] = out['enough'] and out['against_games'] >= composer.settings['min_games']['champion']
        return out

    def _responses(self, gameid, actions, slot, champion, model, fearless_override):
        """The next slot's three most likely actions after this pick (often the opponent's)."""
        after = actions + (draft.Action(slot.step, slot.side, slot.action, champion),)
        ranking = self.predictor.rank(gameid, after, model, fearless_override)
        if ranking is None: return None
        return {'step': ranking.slot.step, 'side': ranking.slot.side, 'action': ranking.slot.action,
                'top': [{'champion': c, 'probability': round(p, 4)} for c, p in zip(ranking.champions[:3], ranking.probabilities[:3])]}
