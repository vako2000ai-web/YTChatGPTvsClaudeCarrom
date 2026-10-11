import pytest
from rules import Rules


def test_own_coin_retains_turn():
    rules = Rules()
    result = rules.resolve([(1, 'white')])
    assert result.keep_turn and rules.player == 0 and rules.scores == [1, 0]


def test_miss_and_opponent_coin_switch_turn():
    rules = Rules()
    rules.resolve([(2, 'black')])
    assert rules.player == 1 and rules.scores == [0, 1]


def test_striker_foul_returns_new_own_and_old_coin():
    rules = Rules()
    rules.resolve([(1, 'white')])
    result = rules.resolve([(3, 'white'), (-1, 'striker')])
    assert result.returned == [3, 1]
    assert rules.scores == [0, 0] and rules.player == 1 and rules.debt == [0, 0]


def test_striker_foul_debt_paid_later():
    rules = Rules()
    rules.resolve([(-1, 'striker')])
    assert rules.debt == [1, 0]
    rules.resolve([])
    result = rules.resolve([(1, 'white')])
    assert result.returned == [1] and rules.scores == [0, 0] and rules.debt == [0, 0]


def test_opponent_coin_stays_pocketed_on_striker_foul():
    rules = Rules()
    result = rules.resolve([(2, 'black'), (-1, 'striker')])
    assert 2 not in result.returned and rules.scores == [0, 1]


def test_queen_same_shot_coverage():
    rules = Rules()
    result = rules.resolve([(0, 'queen'), (1, 'white')])
    assert rules.queen_owner == 0 and rules.queen_pending is None
    assert 'queen_covered' in result.events and rules.scores == [1, 0]


def test_queen_next_shot_coverage():
    rules = Rules()
    rules.resolve([(0, 'queen')])
    assert rules.queen_pending == 0 and rules.player == 0
    rules.resolve([(1, 'white')])
    assert rules.queen_owner == 0 and rules.queen_pending is None


@pytest.mark.parametrize('shot,invalid', [([], False), ([(-1, 'striker')], False), ([], True), ([(2, 'black')], False)])
def test_queen_returned_after_failed_coverage(shot, invalid):
    rules = Rules()
    rules.resolve([(0, 'queen')])
    result = rules.resolve(shot, invalid=invalid)
    assert result.returned.count(0) == 1 and rules.queen_pending is None and rules.queen_owner is None


def test_queen_and_striker_foul_return_queen():
    rules = Rules()
    result = rules.resolve([(0, 'queen'), (-1, 'striker')])
    assert result.returned == [0] and rules.queen_owner is None


def test_queen_cannot_be_covered_by_penalty_payment():
    rules = Rules()
    rules.debt[0] = 1
    rules.resolve([(0, 'queen')])
    result = rules.resolve([(1, 'white')])
    assert set(result.returned) == {0, 1} and rules.queen_owner is None


def test_last_coin_returned_before_queen():
    rules = Rules()
    rules.banked[0] = [1, 3, 5, 7, 9, 11, 13, 15]
    result = rules.resolve([(17, 'white')])
    assert not rules.finished and rules.scores[0] == 8 and result.returned == [17]


def test_board_winner_after_queen():
    rules = Rules()
    rules.banked[0] = [1, 3, 5, 7, 9, 11, 13, 15]
    rules.queen_owner = 1
    rules.resolve([(17, 'white')])
    assert rules.finished and rules.winner == 0
    with pytest.raises(RuntimeError):
        rules.resolve([])


def test_limit_draw_returns_uncovered_queen():
    rules = Rules(max_turns=1)
    result = rules.resolve([(0, 'queen')])
    assert rules.finished and rules.winner is None and rules.finish_reason == 'turn_limit_draw'
    assert result.returned == [0]


def test_invalid_turn_has_no_striker_penalty():
    rules = Rules()
    rules.banked[0] = [1]
    rules.resolve([], invalid=True)
    assert rules.turn == 1 and rules.player == 1 and rules.scores == [1, 0] and rules.debt == [0, 0]
