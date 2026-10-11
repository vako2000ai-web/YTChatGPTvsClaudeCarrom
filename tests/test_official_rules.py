"""Reference scenarios with explicit expected outcomes and law numbers."""
import pytest
from official_rules import OfficialRules
from tournament import Tournament
from engine import Match, Board
from board import official_geometry, official_coins

WHITE, BLACK = list(range(1, 19, 2)), list(range(2, 19, 2))


def prepared(own=0, other=0, owner=None, pending=None, scores=(0, 0)):
    rules = OfficialRules(game_scores=scores)
    rules.break_made = True
    rules.banked = [WHITE[:own], BLACK[:other]]
    rules.queen_owner, rules.queen_pending = owner, pending
    return rules


def test_breaker_owns_white_even_when_claude_breaks():
    rules = OfficialRules(first_player=1)
    assert rules.colours == ['black', 'white'] and rules.player == 1


def test_three_break_chances_then_switch_without_due():
    rules = OfficialRules()
    for turn in range(3):
        rules.resolve([], touched=False)
        assert rules.player == (0 if turn < 2 else 1)
    assert rules.debt == [0, 0] and not rules.break_made


def test_striker_without_break_contact_loses_turn_without_due():
    rules = OfficialRules()
    rules.resolve([(-1, 'striker')], touched=False)
    assert rules.player == 1 and rules.debt == [0, 0]


def test_first_contact_completes_break():
    rules = OfficialRules()
    rules.resolve([], touched=True)
    assert rules.break_made and rules.player == 1


def test_first_coin_and_queen_need_next_stroke():
    rules = prepared()
    rules.resolve([(0, 'queen'), (1, 'white')])
    assert rules.queen_pending == 0 and rules.queen_owner is None and rules.player == 0
    rules.resolve([(3, 'white')])
    assert rules.queen_pending is None and rules.queen_owner == 0


def test_first_two_coins_plus_queen_cover_immediately():
    rules = prepared()
    rules.resolve([(0, 'queen'), (1, 'white'), (3, 'white')])
    assert rules.queen_owner == 0


def test_queen_alone_without_prior_coin_is_returned():
    rules = prepared()
    result = rules.resolve([(0, 'queen')])
    assert result.returned == [0] and rules.player == 1 and rules.queen_pending is None


def test_prior_coin_plus_queen_same_shot_covers():
    rules = prepared(own=1)
    rules.resolve([(0, 'queen'), (3, 'white')])
    assert rules.queen_owner == 0


def test_due_blocks_queen_even_when_due_paid_in_that_stroke():
    rules = prepared(own=1)
    rules.debt[0] = 1
    result = rules.resolve([(0, 'queen'), (3, 'white')])
    assert 0 in result.returned and rules.queen_owner is None and rules.player == 1


def test_recovered_due_allows_queen_with_nine_coins_on_board():
    rules = prepared()
    rules.due_recovered[0] = True
    rules.resolve([(0, 'queen')])
    assert rules.queen_pending == 0 and rules.player == 0


@pytest.mark.parametrize('proper,extra,keeps', [(True, 1, True), (False, 2, False)])
def test_own_and_striker_returns_own_plus_due(proper, extra, keeps):
    rules = prepared(own=3)
    result = rules.resolve([(7, 'white'), (-1, 'striker')], proper=proper)
    assert 7 in result.returned and len(result.returned) == 1 + extra
    assert result.keep_turn is keeps and rules.player == (0 if keeps else 1)


@pytest.mark.parametrize('proper,expected_debt', [(True, 1), (False, 2)])
def test_striker_alone_due_or_due_and_penalty(proper, expected_debt):
    rules = prepared()
    rules.resolve([(-1, 'striker')], proper=proper)
    assert rules.debt == [expected_debt, 0] and rules.player == 1


def test_own_opponent_and_striker_retain_turn_by_specific_law_75():
    rules = prepared(own=1)
    result = rules.resolve([(3, 'white'), (2, 'black'), (-1, 'striker')])
    assert rules.player == 0 and result.keep_turn and rules.scores == [0, 1]


def test_opponent_coin_stops_turn_even_with_own_coin():
    rules = prepared()
    rules.resolve([(1, 'white'), (2, 'black')])
    assert rules.player == 1 and rules.scores == [1, 1]


def test_opponent_and_striker_counts_opponent_coin_and_loses_turn():
    rules = prepared(own=1)
    result = rules.resolve([(2, 'black'), (-1, 'striker')])
    assert rules.scores == [0, 1] and rules.player == 1 and result.returned == [1]


@pytest.mark.parametrize('proper', [True, False])
def test_opponent_coin_stays_pocketed_on_improper_stroke(proper):
    rules = prepared(own=1)
    result = rules.resolve([(2, 'black')], proper=proper)
    assert 2 not in result.returned and rules.scores[1] == 1 and rules.player == 1


def test_technical_foul_keeps_turn_and_can_penalize_nonactive_player():
    rules = prepared(own=1, other=1)
    result = rules.technical_foul(1)
    assert result.returned == [2] and rules.player == 0 and rules.turn == 0


def test_old_due_recovered_after_own_coin_and_turn_retained():
    rules = prepared()
    rules.debt[0] = 1
    result = rules.resolve([(1, 'white')])
    assert result.returned == [1] and rules.player == 0 and rules.due_recovered[0]


def test_opponents_due_recovered_when_shooter_pockets_their_coin():
    rules = prepared()
    rules.debt[1] = 1
    result = rules.resolve([(2, 'black')])
    assert result.returned == [2] and rules.debt[1] == 0


def test_coverage_striker_with_own_gives_another_coverage_shot():
    rules = prepared(own=1, pending=0)
    result = rules.resolve([(3, 'white'), (-1, 'striker')])
    assert rules.queen_pending == 0 and rules.player == 0 and 0 not in result.returned
    rules.resolve([(5, 'white')])
    assert rules.queen_owner == 0


@pytest.mark.parametrize('proper,keep', [(True, True), (False, False)])
def test_queen_and_striker_with_prior_coin(proper, keep):
    rules = prepared(own=3)
    result = rules.resolve([(0, 'queen'), (-1, 'striker')], proper=proper)
    assert 0 in result.returned and rules.queen_owner is None and result.keep_turn is keep


def test_queen_striker_before_any_own_coin_loses_turn():
    rules = prepared()
    rules.resolve([(0, 'queen'), (-1, 'striker')])
    assert rules.player == 1 and rules.debt[0] == 1


@pytest.mark.parametrize('proper,expected', [(True, 3), (False, 4)])
def test_last_own_before_queen_loses_board(proper, expected):
    rules = prepared(own=8)
    rules.resolve([(17, 'white')], proper=proper)
    assert rules.finished and rules.winner == 1 and rules.points == [0, expected]


@pytest.mark.parametrize('proper,expected', [(True, 4), (False, 5)])
def test_last_own_and_striker_before_queen(proper, expected):
    rules = prepared(own=8)
    rules.resolve([(17, 'white'), (-1, 'striker')], proper=proper)
    assert rules.winner == 1 and rules.points[1] == expected


@pytest.mark.parametrize('own,other,scores,expected', [(8, 5, (0, 0), 7), (8, 5, (22, 0), 4), (8, 0, (21, 0), 12)])
def test_normal_board_scoring_and_queen_cutoff(own, other, scores, expected):
    rules = prepared(own, other, owner=0, scores=scores)
    rules.resolve([(17, 'white')])
    assert rules.winner == 0 and rules.points[0] == expected


def test_loser_covering_queen_gets_no_queen_bonus():
    rules = prepared(own=8, other=3, owner=1)
    rules.resolve([(17, 'white')])
    assert rules.points == [6, 0]


@pytest.mark.parametrize('queen_state,striker,proper,scores,expected_winner,award', [
    ('board', False, True, (0, 0), 1, 3),
    ('board', False, False, (0, 0), 1, 4),
    ('pending', False, True, (0, 0), 0, 3),
    ('new', False, True, (22, 0), 0, 1),
    ('new', False, False, (0, 0), 1, 4),
    ('new', True, True, (0, 0), 1, 4),
    ('new', True, False, (0, 0), 1, 5),
    ('own', True, True, (0, 0), 1, 2),
    ('own', True, False, (0, 0), 1, 3),
    ('opponent', True, True, (0, 0), 1, 4),
    ('opponent', True, True, (0, 22), 1, 2),
])
def test_last_both_exceptions(queen_state, striker, proper, scores, expected_winner, award):
    rules = prepared(8, 8, owner={'own': 0, 'opponent': 1}.get(queen_state),
                     pending=0 if queen_state == 'pending' else None, scores=scores)
    shot = [(17, 'white'), (18, 'black')]
    if queen_state == 'new':
        shot.append((0, 'queen'))
    if striker:
        shot.append((-1, 'striker'))
    rules.resolve(shot, proper=proper)
    assert rules.winner == expected_winner and rules.points[expected_winner] == award


def test_opponent_last_with_uncovered_queen_scores_remaining_and_queen():
    rules = prepared(own=1, other=8, pending=0)
    rules.resolve([(18, 'black')])
    assert rules.winner == 1 and rules.points[1] == 11


def test_limit_is_technical_abort_not_sporting_draw():
    rules = OfficialRules(max_turns=1)
    rules.resolve([])
    assert rules.winner is None and rules.points == [0, 0] and rules.finish_reason == 'safety_limit_aborted'


@pytest.mark.parametrize('event', ['blocked_baseline', 'unforeseen', 'protest_upheld'])
def test_referee_replay_events(event):
    rules = prepared()
    rules.referee(event)
    assert rules.cancelled and rules.finished and rules.winner is None


@pytest.mark.parametrize('event', ['out_of_turn', 'left_seat', 'play_during_appeal', 'disturbed_board'])
def test_referee_board_loss(event):
    rules = prepared(own=2)
    rules.referee(event, offender=0)
    assert rules.winner == 1 and rules.points[1] == 10


def test_three_passes_each_cancel_board():
    rules = prepared()
    for _ in range(6):
        rules.resolve([], pass_turn=True)
    assert rules.cancelled and rules.finish_reason == 'law_137_replay'


def test_official_equipment_and_rack():
    geometry = official_geometry()
    coins = official_coins(geometry.coin_radius)
    scale = 630 / 735
    assert geometry.coin_radius * 2 / scale == pytest.approx(31)
    assert geometry.striker_radius * 2 / scale == pytest.approx(41.3)
    assert geometry.pocket_radius * 2 / scale == pytest.approx(44.5)
    assert sum(kind == 'white' for _, kind, _ in coins) == 9
    for index, (_, _, pos) in enumerate(coins):
        for _, _, other in coins[index + 1:]:
            import math
            assert math.dist(pos, other) >= geometry.coin_radius * 2 - 1e-8


def test_dues_return_in_outer_circle_without_covering_centre():
    board = Board(official=True)
    # Open space in the outer ring; a packed rack may legitimately defer dues.
    for i in range(7, 19):
        board.remove(i)
    assert board.return_coin(7, 'due')
    distance = (board.discs[7]['body'].position - (380, 380)).length
    assert distance + board.geometry.coin_radius <= board.geometry.outer_radius
    assert distance - board.geometry.coin_radius > board.geometry.centre_radius


def test_due_is_deferred_when_outer_circle_has_no_space():
    board = Board(official=True)
    board.remove(1)
    assert not board.return_coin(1, 'due')
    assert 1 not in board.discs
    assert board.pending_returns == [(1, 'due', 0)]


def test_official_agent_colours_and_seats_are_in_shared_state():
    match = Match(first_player=1, ruleset='icf', seats=(1, 0))
    state = match.state()
    assert state['rules']['colour_by_player'] == ['black', 'white']
    assert state['board']['baseline_by_player'][1] == match.board.geometry.baseline_y[0]


def test_game_and_match_scoring():
    tournament = Tournament()
    for _ in range(3):
        tournament.record_board(0, 9)
    assert tournament.games == [1, 0] and tournament.game_number == 2 and tournament.breaker == 1
    for _ in range(3):
        tournament.record_board(0, 9)
    assert tournament.finished and tournament.winner == 0 and tournament.games == [2, 0]


def test_eight_boards_with_tie_need_extra_board():
    tournament = Tournament()
    for i in range(8):
        tournament.record_board(i % 2, 1)
    assert tournament.boards == 8 and tournament.games == [0, 0]
    tournament.record_board(1, 1)
    assert tournament.games == [0, 1]


def test_third_game_switches_sides_at_four_boards_or_thirteen_points():
    tournament = Tournament(game_number=3)
    tournament.record_board(0, 7)
    tournament.record_board(0, 6)
    assert tournament.midgame_swapped and tournament.seats == (1, 0)


def test_senior_profile_has_ten_second_stroke_clock():
    assert OfficialRules(profile='aicf-senior').stroke_seconds == 10
