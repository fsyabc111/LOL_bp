"""Local HTTP API for replay and manual branching. Run: .venv/bin/uvicorn lolbp.api:app --port 8000"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import draft
from .branches import BranchNotFound, BranchStore
from .repository import ROOT, Repository

WEB_DIST = ROOT / 'web/dist'


class BranchCreate(BaseModel):
    gameid: str
    fork_step: int
    name: str = ''
    fearless_override: str | None = None


class BranchAction(BaseModel):
    champion: str | None = None


def create_app(repository=None, store=None):
    repo = repository or Repository()
    branches = store or BranchStore()
    app = FastAPI(title='LOL BP')

    def game_or_404(gameid):
        if gameid not in repo.games: raise HTTPException(404, f'unknown game {gameid}')

    def state_payload(rules, actions):
        return {**draft.summary(rules, actions), 'unavailable': draft.availability(rules, actions, repo.champions)}

    def branch_or_404(branch_id):
        try: return branches.get(branch_id)
        except BranchNotFound: raise HTTPException(404, f'unknown branch {branch_id}')

    def branch_payload(branch):
        rules, actions = branches.actions(repo, branch)
        return {'branch': {k: v for k, v in branch.items() if k != 'actions_json'}, 'state': state_payload(rules, actions),
                'rules': repo.resolve_rules(branch['gameid'], branch['fearless_override'])}

    @app.get('/api/meta')
    def meta():
        leagues = sorted({g['league'] for g in repo.games.values()}); years = sorted({g['year'] for g in repo.games.values()})
        return {'leagues': leagues, 'years': years, 'games': len(repo.games), 'series': len(repo.series),
                'oe_order_accuracy': repo.accuracy, 'champion_catalog_version': '16.20.1',
                'champion_pool_note': 'Pool is the 16.20.1 catalog for every game; older patches may list champions not yet released.'}

    @app.get('/api/champions')
    def champions():
        return sorted(repo.champions.values(), key=lambda c: c['name'])

    @app.get('/api/series')
    def series(league: str | None = None, year: str | None = None, q: str | None = None, limit: int = 200):
        return repo.list_series(league, year, q, limit)

    @app.get('/api/games/{gameid}')
    def game(gameid: str):
        game_or_404(gameid)
        return repo.game_detail(gameid)

    @app.get('/api/games/{gameid}/state')
    def game_state(gameid: str, step: int = 20):
        game_or_404(gameid)
        steps, _, _ = repo.sequence(gameid)
        if not 0 <= step <= len(steps): raise HTTPException(422, 'step out of range')
        rules, _, _ = repo.draft_rules(gameid)
        actions = tuple(draft.Action(s['step'], s['side'], s['action'], s['champion']) for s in steps[:step])
        return state_payload(rules, actions)

    @app.get('/api/branches')
    def list_branches(gameid: str | None = None):
        return [{k: v for k, v in b.items() if k != 'actions_json'} for b in branches.list(gameid)]

    @app.post('/api/branches', status_code=201)
    def create_branch(body: BranchCreate):
        game_or_404(body.gameid)
        if body.fearless_override not in (None, draft.FEARLESS_PICKS_BOTH, draft.FEARLESS_NONE):
            raise HTTPException(422, 'fearless_override must be picks_both_teams, none or null')
        try: branch_id = branches.create(repo, body.gameid, body.fork_step, body.name or f'step {body.fork_step} branch', body.fearless_override)
        except ValueError as error: raise HTTPException(422, str(error))
        return branch_payload(branches.get(branch_id))

    @app.get('/api/branches/{branch_id}')
    def get_branch(branch_id: int):
        return branch_payload(branch_or_404(branch_id))

    @app.post('/api/branches/{branch_id}/actions')
    def add_action(branch_id: int, body: BranchAction):
        branch_or_404(branch_id)
        try: branches.append(repo, branch_id, body.champion)
        except draft.IllegalAction as error: raise HTTPException(409, {'reasons': error.reasons})
        return branch_payload(branches.get(branch_id))

    @app.post('/api/branches/{branch_id}/undo')
    def undo(branch_id: int):
        branch_or_404(branch_id)
        try: branches.undo(branch_id)
        except ValueError as error: raise HTTPException(409, str(error))
        return branch_payload(branches.get(branch_id))

    @app.delete('/api/branches/{branch_id}', status_code=204)
    def delete_branch(branch_id: int):
        branch_or_404(branch_id); branches.delete(branch_id)

    if WEB_DIST.is_dir():
        app.mount('/assets', StaticFiles(directory=WEB_DIST / 'assets'), name='assets')

        @app.get('/{path:path}', include_in_schema=False)
        def spa(path: str):
            return FileResponse(WEB_DIST / 'index.html')

    return app


app = create_app() if Path(ROOT / 'data/processed/lol_bp.sqlite3').exists() else None
