"""Automatic lifecycle; workers make API decisions, main thread owns physics."""
from dataclasses import asdict
import json
from pathlib import Path
import queue
import threading
import uuid
from datetime import datetime, timezone
from agents import decide
from engine import Match

VERSION = '0.2.0'


class MatchLog:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8] + '.jsonl')
        self.file = self.path.open('x', encoding='utf-8')

    def write(self, event, **data):
        self.file.write(json.dumps({'event': event, **data}, ensure_ascii=False, allow_nan=False) + '\n')
        self.file.flush()

    def close(self):
        self.file.close()


class Controller:
    def __init__(self, settings, directory='matches', max_turns=80, first_player=0, chooser=decide):
        self.settings = settings
        self.match = Match(max_turns, first_player)
        self.chooser = chooser
        self.log = MatchLog(directory)
        self.log.write('match_start', version=VERSION, mode=settings.mode,
                       models={'ChatGPT': settings.openai_model if settings.mode == 'api' else 'local-geometric-v0.2',
                               'Claude': settings.anthropic_model if settings.mode == 'api' else 'local-geometric-v0.2'},
                       initial_state=self.match.state())
        self.results = queue.Queue()
        self.busy = False
        self.closed = False
        self.summary = None
        self.status = 'Готов к автоматическому матчу'
        self.comment = ''
        self.last_move = None
        self.decision_count = 0
        self.failures = 0
        self.tokens = [0, 0]

    def request(self, background=True):
        if self.busy or self.match.board.active or self.match.rules.finished or self.closed:
            return
        state = self.match.state()
        self.busy = True
        self.status = state['player'] + ' выбирает удар...'
        self.log.write('decision_start', state=state)
        def work():
            try:
                self.results.put((self.chooser(state, self.settings), None))
            except Exception as exc:
                # Never write SDK exception messages, HTTP headers or API secrets.
                self.results.put((None, type(exc).__name__))
        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def tick(self, physics_steps=4, background=True, advance=True):
        if self.closed:
            return
        if self.busy:
            try:
                decision, error = self.results.get_nowait()
            except queue.Empty:
                return
            self.busy = False
            self.decision_count += 1
            player = self.match.rules.player
            if decision is not None:
                self.tokens[player] += sum(decision.usage.get(k, 0) for k in ('input_tokens', 'output_tokens'))
                self.log.write('decision', player=player, **asdict(decision))
                try:
                    self.match.board.shoot(decision.move, player)
                except ValueError:
                    error = 'InvalidPlacement'
                else:
                    self.last_move = decision.move
                    self.comment = decision.move['comment']
                    self.status = f"{self.match.state()['player']} [{decision.source}]: удар"
            if error:
                self.failures += 1
                resolution = self.match.forfeit_turn()
                self.log.write('decision_failed', player=player, error_type=error,
                               resolution=asdict(resolution), state=self.match.state())
                self.status = 'Ошибка решения: ' + error + '. Ход пропущен.'
        if self.match.board.active:
            for _ in range(physics_steps):
                self.match.board.step()
                if not self.match.board.active:
                    resolution = self.match.finish_shot()
                    self.log.write('shot_end', pocketed=self.match.board.pocketed,
                                   physics_steps=self.match.board.steps,
                                   physics_timeout=self.match.board.timed_out,
                                   resolution=asdict(resolution), state=self.match.state())
                    self.status = ', '.join(resolution.events) or 'Удар завершён'
                    break
        if self.match.rules.finished:
            self.summary = {'winner': self.match.rules.winner,
                            'reason': self.match.rules.finish_reason,
                            'scores': self.match.rules.scores, 'turns': self.match.rules.turn,
                            'decisions': self.decision_count, 'failures': self.failures,
                            'tokens': self.tokens}
            self.log.write('match_end', summary=self.summary, state=self.match.state())
            self.log.close()
            self.closed = True
        elif advance and not self.busy and not self.match.board.active:
            self.request(background)

    def abort(self):
        if not self.closed:
            self.log.write('match_aborted', state=self.match.state(), decision_pending=self.busy)
            self.log.close()
            self.closed = True


def run_headless(settings, directory='matches', max_turns=80, first_player=0):
    controller = Controller(settings, directory, max_turns, first_player)
    try:
        while not controller.closed:
            controller.tick(physics_steps=240, background=False)
        return {**controller.summary, 'log': str(controller.log.path)}
    finally:
        controller.abort()
