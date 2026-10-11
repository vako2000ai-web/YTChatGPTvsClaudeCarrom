"""Testable house rules for v0.2; NOT a complete official tournament ruleset."""
from dataclasses import dataclass, field
from board import COLORS

RULESET = 'showdown-house-v0.2'


@dataclass
class Resolution:
    returned: list[int] = field(default_factory=list)
    foul: bool = False
    keep_turn: bool = False
    events: list[str] = field(default_factory=list)


class Rules:
    def __init__(self, max_turns=80, first_player=0):
        if max_turns < 1 or first_player not in (0, 1):
            raise ValueError('Invalid match limits or first player')
        self.max_turns = max_turns
        self.player = first_player
        self.turn = 0
        self.banked = [[], []]
        self.debt = [0, 0]
        self.queen_pending = None
        self.queen_owner = None
        self.finished = False
        self.winner = None
        self.finish_reason = None

    @property
    def scores(self):
        return [len(bank) for bank in self.banked]

    def snapshot(self):
        return {'ruleset': RULESET, 'player_index': self.player,
                'turn': self.turn, 'max_turns': self.max_turns,
                'banked': [list(b) for b in self.banked], 'scores': self.scores,
                'penalty_debt': list(self.debt), 'queen_pending': self.queen_pending,
                'queen_owner': self.queen_owner, 'finished': self.finished,
                'winner': self.winner, 'finish_reason': self.finish_reason}

    def resolve(self, pocketed, invalid=False):
        if self.finished:
            raise RuntimeError('Match already finished')
        player = self.player
        result = Resolution(foul=invalid or any(kind == 'striker' for _, kind in pocketed))
        own = []
        queen = False
        for coin_id, kind in pocketed:
            if kind in COLORS:
                owner = COLORS.index(kind)
                self.banked[owner].append(coin_id)
                if owner == player:
                    own.append(coin_id)
            elif kind == 'queen':
                queen = True

        def return_queen():
            result.returned.append(0)
            self.queen_pending = None
            result.events.append('queen_returned')

        if result.foul:
            result.events.append('invalid_move' if invalid else 'striker_foul')
            # Invalid API moves lose the turn but do not incur striker penalties.
            if not invalid:
                for coin_id in own:
                    self.banked[player].remove(coin_id)
                    result.returned.append(coin_id)
                if self.banked[player]:
                    result.returned.append(self.banked[player].pop())
                else:
                    self.debt[player] += 1
            if queen or self.queen_pending == player:
                return_queen()
        else:
            while self.debt[player] and own:
                coin_id = own.pop(0)
                self.banked[player].remove(coin_id)
                result.returned.append(coin_id)
                self.debt[player] -= 1
                result.events.append('penalty_paid')
            if self.queen_pending == player:
                if own:
                    self.queen_owner = player
                    self.queen_pending = None
                    result.events.append('queen_covered')
                else:
                    return_queen()
            if queen:
                if own:
                    self.queen_owner = player
                    result.events.append('queen_covered')
                else:
                    self.queen_pending = player
                    result.events.append('queen_needs_cover')
            result.keep_turn = bool(own) or self.queen_pending == player

        # House rule: the last coin cannot finish the board before queen coverage.
        for owner in (0, 1):
            if len(self.banked[owner]) == 9:
                if self.queen_owner is not None:
                    self.finished = True
                    self.winner = owner
                    self.finish_reason = 'all_own_coins_pocketed'
                    break
                result.returned.append(self.banked[owner].pop())
                result.events.append('last_coin_returned_before_queen')
        self.turn += 1
        if not self.finished and self.turn >= self.max_turns:
            if self.queen_pending is not None:
                return_queen()
            self.finished = True
            self.finish_reason = 'turn_limit_draw'
        if not result.keep_turn or result.foul:
            self.player = 1 - player
        return result
