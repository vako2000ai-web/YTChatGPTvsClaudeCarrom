"""25 points / 8 boards / best of 3 games, independent of render and API."""
from dataclasses import dataclass, field
import random


@dataclass
class Tournament:
    first_breaker: int = 0
    points: list[int] = field(default_factory=lambda: [0, 0])
    games: list[int] = field(default_factory=lambda: [0, 0])
    boards: int = 0
    game_number: int = 1
    total_boards: int = 0
    finished: bool = False
    winner: int | None = None
    midgame_swapped: bool = False
    sides_swapped: bool = False
    history: list[dict] = field(default_factory=list)
    toss_seed: int = 0
    extra_breaker: int | None = None
    round_stage: str = 'pre-quarter'

    @property
    def breaker(self):
        if self.extra_breaker is not None:
            return self.extra_breaker
        return self.first_breaker ^ ((self.game_number - 1) % 2) ^ (self.boards % 2)

    @property
    def seats(self):
        swapped = self.sides_swapped ^ self.midgame_swapped
        return (1, 0) if swapped else (0, 1)

    def snapshot(self):
        return {'points': list(self.points), 'games': list(self.games), 'boards': self.boards,
                'game_number': self.game_number, 'breaker': self.breaker,
                'seats': list(self.seats), 'finished': self.finished, 'winner': self.winner,
                'toss_seed': self.toss_seed, 'round_stage': self.round_stage,
                'extra_breaker': self.extra_breaker}

    def record_board(self, winner, award):
        if self.finished or winner not in (0, 1) or not 0 <= award <= 12:
            raise ValueError('Invalid board result')
        self.points[winner] += award
        self.boards += 1
        self.total_boards += 1
        self.history.append({'game': self.game_number, 'board': self.boards,
                             'winner': winner, 'award': award, 'points': list(self.points)})
        if self.game_number == 3 and not self.midgame_swapped and (max(self.points) >= 13 or
                (self.round_stage == 'pre-quarter' and self.boards >= 4)):
            self.midgame_swapped = True
        if self.boards >= 8 and self.points[0] == self.points[1]:
            self.extra_breaker = random.Random(f'{self.toss_seed}:{self.game_number}:{self.boards}').randrange(2)
            self.history[-1]['extra_board_toss'] = self.extra_breaker
        # Tied eighth board means an extra board. No fabricated score tiebreak.
        if max(self.points) >= 25 or (self.boards >= 8 and self.points[0] != self.points[1]):
            game_winner = 0 if self.points[0] > self.points[1] else 1
            self.games[game_winner] += 1
            if self.games[game_winner] == 2:
                self.finished, self.winner = True, game_winner
            else:
                self.game_number += 1
                self.points = [0, 0]
                self.boards = 0
                self.midgame_swapped = False
                self.sides_swapped = not self.sides_swapped
                self.extra_breaker = None

    def referee(self, event, offender):
        if self.finished or offender not in (0, 1):
            raise ValueError('Invalid match referee event')
        winner = 1 - offender
        if event in ('concede_match', 'disqualification'):
            self.finished, self.winner = True, winner
            self.history.append({'event': event, 'winner': winner})
        elif event == 'concede_game':
            self.games[winner] += 1
            self.history.append({'event': event, 'game': self.game_number, 'winner': winner})
            if self.games[winner] >= 2:
                self.finished, self.winner = True, winner
            else:
                self.game_number += 1
                self.boards, self.points = 0, [0, 0]
                self.midgame_swapped, self.extra_breaker = False, None
                self.sides_swapped = not self.sides_swapped
        else:
            raise ValueError('Unknown match referee event')
