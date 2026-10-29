"""Local HTTP API for replay, manual branching, next-action predictions, prediction feedback and composition evaluation.

Run: .venv/bin/uvicorn lolbp.api:app --port 8000
"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import draft, feedback as fb
from .branches import BranchNotFound, BranchStore
from .composition import Composer
from .predict import ModelError, Predictor
from .repository import ROOT, Repository

WEB_DIST = ROOT / 'web/dist'


class BranchCreate(BaseModel):
    gameid: str
    fork_step: int
    name: str = ''
    fearless_override: str | None = None


class BranchAction(BaseModel):
    champion: str | None = None


class FeedbackCreate(BaseModel):
    gameid: str
    step: int | None = None          # replay: number of recorded actions before the predicted slot
    branch_id: int | None = None     # branch: its current state is used instead of step
    version: str | None = None
    kind: str
    champion: str | None = None
    expect_rank: int | None = None
    note: str = ''


def create_app(repository=None, store=None, predictor=None, feedback_store=None, composer=None):
    repo = repository or Repository()
    branches = store or BranchStore()
    predictions = predictor or Predictor(repo)
    feedback = feedback_store or fb.FeedbackStore()
    compositions = composer or Composer(repo, predictions)
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

    def history_actions(gameid, step):
        steps, _, _ = repo.sequence(gameid)
        if not 0 <= step <= len(steps): raise HTTPException(422, 'step out of range')
        return steps, tuple(draft.Action(s['step'], s['side'], s['action'], s['champion']) for s in steps[:step])

    def model_or_422(version):
        try: return predictions.version(version)
        except ModelError as error: raise HTTPException(422, str(error))

    def game_label(gameid):
        game = repo.games.get(gameid)
        if not game: return None
        return {'date': game['date'][:10], 'league': game['league'], 'blue': game['teams']['Blue']['name'],
                'red': game['teams']['Red']['name'], 'game_number': game['game_number']}

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

    @app.get('/api/models')
    def models():
        settings = predictions.settings()
        versions = []
        for model in predictions.versions().values():
            path = predictions.models_dir / 'reports' / f'{model.version}.validation.json'
            report = json.loads(path.read_text()) if path.exists() else None
            current = bool(report) and report.get('model_sha256') == model.sha256
            versions.append({**model.summary(), 'validation_stale': bool(report) and not current,
                             'validation': {k: report['overall'][k] for k in ('decisions', 'top1', 'top3', 'top5', 'top10')} if current else None})
        return {'default': settings.get('default'), 'feedback_top_k': settings.get('feedback_top_k', 5), 'versions': versions}

    @app.get('/api/games/{gameid}/predictions')
    def game_predictions(gameid: str, step: int, version: str | None = None, top: int = 10):
        game_or_404(gameid)
        steps, actions = history_actions(gameid, step)
        return predictions.predict(gameid, actions, None, model_or_422(version).version, max(1, min(top, 50)), {s['step']: s['champion'] for s in steps})

    @app.get('/api/branches/{branch_id}/predictions')
    def branch_predictions(branch_id: int, version: str | None = None, top: int = 10):
        branch = branch_or_404(branch_id)
        _, actions = branches.actions(repo, branch)
        return predictions.predict(branch['gameid'], actions, branch['fearless_override'], model_or_422(version).version, max(1, min(top, 50)))

    def composition_payload(gameid, actions):
        out = compositions.evaluate(gameid, actions)
        path = repo.root / 'models/composition/reports' / f"{out['settings_version']}.validation.json"
        report = json.loads(path.read_text()) if path.exists() else None
        out['backtest'] = report and {'lane_r': report['lane_gold15']['matchup']['pearson_r'], 'lane_n': report['lane_gold15']['matchup']['n'],
                                      'win_auc': report['win_auc']['early_gold_expectation'], 'duo_auc': report['win_auc']['duo_win_residuals'],
                                      'reference_auc': report['win_auc']['reference_actual_gold15'], 'range': report['range']}
        return out

    @app.get('/api/games/{gameid}/composition')
    def game_composition(gameid: str, step: int = 20):
        game_or_404(gameid)
        _, actions = history_actions(gameid, step)
        return composition_payload(gameid, actions)

    @app.get('/api/branches/{branch_id}/composition')
    def branch_composition(branch_id: int):
        branch = branch_or_404(branch_id)
        _, actions = branches.actions(repo, branch)
        return composition_payload(branch['gameid'], actions)

    @app.get('/api/feedback')
    def list_feedback(version: str | None = None):
        model = model_or_422(version)
        existing = {b['id'] for b in branches.list()}
        return [{**record, 'game': game_label(record['gameid']), 'recheck': fb.recheck(predictions, record, model),
                 'branch_exists': bool(record.get('branch')) and record['branch']['id'] in existing}
                for record in reversed(feedback.list())]

    @app.post('/api/feedback', status_code=201)
    def create_feedback(body: FeedbackCreate):
        game_or_404(body.gameid)
        model = model_or_422(body.version)
        if body.branch_id is not None:
            branch = branch_or_404(body.branch_id)
            if branch['gameid'] != body.gameid: raise HTTPException(422, 'branch belongs to another game')
            _, actions = branches.actions(repo, branch)
            override, source, info = branch['fearless_override'], 'branch', {'id': branch['id'], 'name': branch['name']}
        elif body.step is not None:
            _, actions = history_actions(body.gameid, body.step)
            override, source, info = None, 'replay', None
        else:
            raise HTTPException(422, 'step or branch_id is required')
        try:
            record = fb.build(predictions, body.gameid, actions, override, model, body.kind, body.champion, body.expect_rank,
                              body.note, source, info, predictions.settings().get('feedback_top_k', 5))
        except ValueError as error: raise HTTPException(422, str(error))
        return feedback.add(record)

    @app.delete('/api/feedback/{feedback_id}', status_code=204)
    def delete_feedback(feedback_id: int):
        try: feedback.delete(feedback_id)
        except KeyError: raise HTTPException(404, f'unknown feedback {feedback_id}')

    if WEB_DIST.is_dir():
        app.mount('/assets', StaticFiles(directory=WEB_DIST / 'assets'), name='assets')

        @app.get('/{path:path}', include_in_schema=False)
        def spa(path: str):
            return FileResponse(WEB_DIST / 'index.html')

    return app


app = create_app() if Path(ROOT / 'data/processed/lol_bp.sqlite3').exists() else None
