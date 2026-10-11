"""ICF 2004 singles laws. Human actions use explicit referee events in 2D.

Source: https://www.indiancarrom.co.in/laws-of-carrom/
Rule numbers are recorded in events. Virtual umpire always notices violations,
demands available extra points and places returns by the declared legal policy.
"""
from rules import Rules, Resolution

PROFILES = {'icf': ('icf-2004-singles', 15), 'aicf-senior': ('aicf-senior-singles', 10)}


class OfficialRules(Rules):
    def __init__(self, max_turns=800, first_player=0, game_scores=(0, 0), profile='icf', seats=(0, 1)):
        super().__init__(max_turns, first_player)
        self.ruleset, self.stroke_seconds = PROFILES[profile]
        self.game_scores = list(game_scores)
        self.colours = ['black', 'black']
        self.colours[first_player] = 'white'
        self.seats = list(seats)
        self.break_made = False
        self.break_attempts = 0
        self.due_recovered = [False, False]
        self.passes = [0, 0]
        self.points = [0, 0]
        self.cancelled = False

    def snapshot(self):
        state = super().snapshot()
        state.update(ruleset=self.ruleset, game_scores=list(self.game_scores),
                     colour_by_player=list(self.colours), seat_by_player=list(self.seats),
                     stroke_seconds=self.stroke_seconds, break_made=self.break_made,
                     break_attempts=self.break_attempts, due_recovered=list(self.due_recovered),
                     board_points=list(self.points), cancelled=self.cancelled)
        return state

    def _bonus(self, winner):
        return 3 if self.game_scores[winner] < 22 else 0

    def _end(self, winner, points, rule, result):
        self.finished, self.winner = True, winner
        self.points[winner] = min(12, points)
        self.finish_reason = rule
        self.debt = [0, 0]  # Law 55: outstanding dues are written off.
        result.events.append(rule)

    def _return(self, coin_id, result, kind='due'):
        if coin_id not in result.returned:
            result.returned.append(coin_id)
            result.return_kinds[coin_id] = kind

    def _queen_return(self, result):
        self._return(0, result, 'centre')
        self.queen_pending = None
        result.events.append('queen_returned')

    def _penalty(self, player, count, result):
        self.debt[player] += count
        while self.debt[player] and self.banked[player]:
            self._return(self.banked[player].pop(), result)
            self.debt[player] -= 1
            self.due_recovered[player] = True
            result.events.append('law_78_due_recovered')

    def technical_foul(self, offender):
        """Law 63: no stroke, no turn change; also valid for nonactive player."""
        if self.finished or offender not in (0, 1):
            raise ValueError('Invalid technical foul')
        result = Resolution(foul=True, keep_turn=True, events=['law_63_technical_foul'])
        self._penalty(offender, 1, result)
        return result

    def referee(self, event, offender=None):
        """Administrative laws are explicit events rather than hidden house rules."""
        if self.finished:
            raise RuntimeError('Board finished')
        player = self.player if offender is None else offender
        result = Resolution()
        if event in ('blocked_baseline', 'unforeseen', 'protest_upheld'):
            self.cancelled = self.finished = True
            self.finish_reason = {'blocked_baseline': 'law_142_replay', 'unforeseen': 'law_140_replay',
                                  'protest_upheld': 'law_151_replay'}[event]
            result.events.append(self.finish_reason)
        elif event in ('out_of_turn', 'left_seat', 'play_during_appeal', 'disturbed_board'):
            other = 1 - player
            own_remaining = 9 - len(self.banked[player])
            queen_on_board = self.queen_owner is None and self.queen_pending is None
            bonus = self._bonus(other) if queen_on_board else 0
            number = {'out_of_turn': 51, 'left_seat': 91, 'play_during_appeal': 121, 'disturbed_board': 126}[event]
            self._end(other, own_remaining + bonus, f'law_{number}_board_loss', result)
        elif event == 'concede_board':
            self._end(1 - player, 9 - len(self.banked[player]) + self._bonus(1 - player), 'conceded_board', result)
        else:
            raise ValueError('Unknown referee event')
        return result

    def resolve(self, pocketed, invalid=False, proper=True, touched=True, overboard=(), pass_turn=False):
        if self.finished:
            raise RuntimeError('Match already finished')
        player, other = self.player, 1 - self.player
        proper = proper and not invalid
        result = Resolution(foul=not proper)
        self.turn += 1
        if pass_turn:
            self.passes[player] += 1
            self.player = other
            if min(self.passes) >= 3:
                self.cancelled = self.finished = True
                self.finish_reason = 'law_137_replay'
            return result
        self.passes = [0, 0]
        kinds = [kind for _, kind in pocketed]
        striker = 'striker' in kinds
        queen = 'queen' in kinds
        own = [i for i, kind in pocketed if kind == self.colours[player]]
        theirs = [i for i, kind in pocketed if kind == self.colours[other]]
        before_own, before_other = len(self.banked[player]), len(self.banked[other])
        before_due = self.debt[player]
        pending = self.queen_pending == player
        queen_on_board = self.queen_owner is None and self.queen_pending is None

        ordered = sorted(overboard, key=lambda item: (item[1] != 'queen', item[1] != self.colours[player]))
        for coin_id, kind in ordered:
            if kind != 'striker':
                self._return(coin_id, result, 'centre')
                result.events.append('law_65_overboard')

        if not self.break_made:
            if touched:
                self.break_made = True
                result.events.append('law_44_break_made')
            else:
                self.break_attempts += 1
                result.keep_turn = proper and not striker and self.break_attempts < 3
                if not result.keep_turn:
                    self.player = other
                result.events.append('law_45_break_attempt')
                return self._limit(result)

        for i in own:
            self.banked[player].append(i)
        for i in theirs:
            self.banked[other].append(i)
        own_last = before_own + len(own) == 9 and bool(own)
        other_last = before_other + len(theirs) == 9 and bool(theirs)
        unconfirmed_queen = queen_on_board or pending or queen

        # Terminal exceptions must be decided BEFORE dues return the last coin.
        if own_last and other_last:
            if striker:
                base = 1 if self.queen_owner == player and not queen else (3 if self.game_scores[other] < 22 else 1)
                self._end(other, base + 1 + (not proper), 'law_109_110_112_last_both_striker', result)
            elif (pending or queen) and proper:
                self.queen_owner, self.queen_pending = player, None
                self._end(player, 3 if self.game_scores[player] < 22 else 1, 'law_102_104_last_both_covered', result)
            elif unconfirmed_queen or not proper:
                self._end(other, (3 if self.game_scores[other] < 22 else 1) + (not proper), 'law_105_last_both_uncovered', result)
            else:
                self._end(player, self._bonus(player) if self.queen_owner == player else 0, 'law_52_last_both', result)
        elif other_last:
            bonus = self._bonus(other) if unconfirmed_queen or self.queen_owner == other else 0
            self._end(other, 9 - len(self.banked[player]) + bonus + striker + (not proper), 'law_103_106_111_opponent_last', result)
        elif own_last and queen_on_board and not queen:
            self._end(other, (3 if self.game_scores[other] < 22 else 1) + striker + (not proper), 'law_107_108_own_last_before_queen', result)
        if self.finished:
            if queen and self.queen_owner is None:
                self._queen_return(result)
            return result

        if striker or not proper:
            result.foul = True
            for coin_id in own:
                self.banked[player].remove(coin_id)
                self._return(coin_id, result)
            self._penalty(player, int(striker) + int(not proper), result)
            result.keep_turn = proper and bool(own)
            if queen:
                eligible = before_own > 0 or self.due_recovered[player]
                self._queen_return(result)
                result.keep_turn = proper and (bool(own) or eligible)
                if before_own == 0 and not self.due_recovered[player] and not own:
                    result.keep_turn = False
                result.events.append('law_98_99_queen_striker')
            elif pending:
                if proper and own:
                    result.keep_turn = True  # Law 101a grants another coverage shot.
                    result.events.append('law_101_cover_retry')
                else:
                    self._queen_return(result)
            result.events.append('law_73_75_own_striker' if proper and own else 'law_72_76_77_foul')
        else:
            if before_due:
                self._penalty(player, 0, result)
            net_own = [i for i in own if i in self.banked[player]]
            result.keep_turn = bool(own)
            if pending:
                if net_own:
                    self.queen_owner, self.queen_pending = player, None
                    result.events.append('law_96_queen_covered')
                else:
                    self._queen_return(result)
            if queen:
                eligible = before_own > 0 or self.due_recovered[player]
                if before_due or (not eligible and not own):
                    self._queen_return(result)
                    result.keep_turn = False
                    result.events.append('law_95_ineligible_queen')
                elif net_own and (eligible or len(net_own) >= 2):
                    self.queen_owner = player
                    result.events.append('law_97_queen_covered')
                else:
                    self.queen_pending = player
                    result.keep_turn = True
                    result.events.append('law_97b_cover_required')
            if theirs:
                result.keep_turn = False  # Law 125: umpire notices opponent coin.
                if self.queen_pending == player:
                    self._queen_return(result)
                result.events.append('law_125_opponent_coin')
            if len(self.banked[player]) == 9 and self.queen_owner is not None:
                points = 9 - len(self.banked[other])
                if self.queen_owner == player:
                    points += self._bonus(player)
                self._end(player, points, 'law_52_board_won', result)

        # Recover earlier outstanding dues for EITHER owner when their coin arrives.
        if self.debt[other] and self.banked[other]:
            self._penalty(other, 0, result)
        if not result.keep_turn:
            self.player = other
        return self._limit(result)

    def _limit(self, result):
        if not self.finished and self.turn >= self.max_turns:
            if self.queen_pending is not None:
                self._queen_return(result)
            self.finished = True
            self.finish_reason = 'safety_limit_aborted'  # NOT an official draw/win.
            result.events.append(self.finish_reason)
        return result
