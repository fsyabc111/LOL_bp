"""Pure draft state machine: template slots, legality checks and immutable action sequences.

Champions are identified by Data Dragon numeric keys as strings. A ban may be empty (None);
a pick never is. Rules carry their own evidence status so callers can show what is assumed.
"""
from dataclasses import dataclass

FEARLESS_PICKS_BOTH = 'picks_both_teams'
FEARLESS_NONE = 'none'


@dataclass(frozen=True)
class Slot:
    step: int
    side: str
    action: str


@dataclass(frozen=True)
class DraftRules:
    slots: tuple
    fearless: str = FEARLESS_NONE
    consumed: frozenset = frozenset()   # picked in earlier games of the series
    disabled: frozenset = frozenset()   # event-disabled champions, when known
    known: frozenset = frozenset()      # champion pool; empty means "do not check membership"
    released: frozenset = frozenset()   # champions out on the game's patch; empty means "do not check"


@dataclass(frozen=True)
class Action:
    step: int
    side: str
    action: str
    champion: object = None


class IllegalAction(ValueError):
    def __init__(self, reasons):
        super().__init__(', '.join(reasons)); self.reasons = reasons


def slots_from_template(template, first_selection_side):
    """Map template draft teams A/B onto map sides; A is the first-selecting team."""
    other = 'Red' if first_selection_side == 'Blue' else 'Blue'
    side = {'A': first_selection_side, 'B': other}
    return tuple(Slot(a['step'], side[a['draft_team']], a['action']) for a in template['actions'])


def next_slot(rules, actions):
    return rules.slots[len(actions)] if len(actions) < len(rules.slots) else None


def used(actions):
    return {a.champion for a in actions if a.champion is not None}


def check(rules, actions, champion):
    """Return (blocking reasons, warnings) for placing champion in the next slot."""
    slot = next_slot(rules, actions)
    if slot is None: return ['draft_complete'], []
    reasons, warnings = [], []
    if champion is None:
        if slot.action == 'pick': reasons.append('empty_pick')
        return reasons, warnings
    if rules.known and champion not in rules.known: reasons.append('unknown_champion')
    elif rules.released and champion not in rules.released: reasons.append('not_released')
    if champion in used(actions): reasons.append('already_used_this_game')
    if champion in rules.disabled: reasons.append('event_disabled')
    if rules.fearless == FEARLESS_PICKS_BOTH and champion in rules.consumed:
        # Picking a consumed champion is illegal; banning one only wastes the ban.
        if slot.action == 'pick': reasons.append('fearless_consumed')
        else: warnings.append('ban_wasted_on_consumed')
    return reasons, warnings


def apply(rules, actions, champion):
    reasons, _ = check(rules, actions, champion)
    if reasons: raise IllegalAction(reasons)
    slot = next_slot(rules, actions)
    return tuple(actions) + (Action(slot.step, slot.side, slot.action, champion),)


def replay(rules, steps):
    """Apply a recorded sequence; return (actions applied, findings for illegal steps).

    History is never rewritten: an illegal recorded step is reported and still applied, since
    the record may be right and the rule assumption wrong.
    """
    actions, findings = (), []
    for step in sorted(steps, key=lambda s: s['step']):
        slot = next_slot(rules, actions)
        if slot is None or (slot.side, slot.action) != (step['side'], step['action']):
            findings.append({'step': step['step'], 'reasons': ['template_mismatch']})
            return actions, findings
        reasons, warnings = check(rules, actions, step['champion'])
        if reasons or warnings: findings.append({'step': step['step'], 'reasons': reasons, 'warnings': warnings})
        actions += (Action(slot.step, slot.side, slot.action, step['champion']),)
    return actions, findings


def summary(rules, actions):
    board = {side: {'bans': [], 'picks': []} for side in ('Blue', 'Red')}
    for a in actions: board[a.side]['bans' if a.action == 'ban' else 'picks'].append({'step': a.step, 'champion': a.champion})
    slot = next_slot(rules, actions)
    return {'board': board, 'step': len(actions), 'complete': slot is None,
            'next': None if slot is None else {'step': slot.step, 'side': slot.side, 'action': slot.action},
            'actions': [{'step': a.step, 'side': a.side, 'action': a.action, 'champion': a.champion} for a in actions]}


def availability(rules, actions, pool):
    """Blocking reasons and warnings for every champion in pool at the next slot."""
    result = {}
    for champion in pool:
        reasons, warnings = check(rules, actions, champion)
        if reasons or warnings: result[champion] = {'reasons': reasons, 'warnings': warnings}
    return result
