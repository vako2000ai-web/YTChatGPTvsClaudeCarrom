"""Shared move contract; local demo and two explicit API players."""
from dataclasses import dataclass
import json
import math
import re
import time
from board import BASE_X, BASE_Y, POCKETS, PLAYERS, COLORS
from settings import Settings

MOVE_SCHEMA = {'type': 'object', 'properties': {
    'x': {'type': 'number'}, 'angle': {'type': 'number'},
    'power': {'type': 'number'}, 'comment': {'type': 'string'}},
    'required': ['x', 'angle', 'power', 'comment'], 'additionalProperties': False}

INSTRUCTIONS = (
    'Play Carrom using the provided shared state. Return x, angle, power, comment as JSON. '
    'x is striker baseline x in 265..495, angle is 0..360 degrees (0 right, 90 down), '
    'power is 0.15..1.0. ChatGPT owns white and uses y=665; Claude owns black and uses y=95. '
    'Do not overlap the striker with a coin. The board includes all geometry. '
    'Rules showdown-house-v0.2: own coins retain the turn, opponent coins benefit opponent. '
    'Queen plus an own coin covers immediately, otherwise cover on the very next shot; '
    'failure returns the queen. Striker foul returns all newly pocketed own coins and '
    'one older own coin (or creates penalty debt); queen returns if unconfirmed. '
    'Debt is paid by returning future own coins. Last own coin returns if queen is not covered. '
    'First player clearing nine own coins after queen coverage wins; turn limit is a draw. '
    'An invalid/API-failed decision loses the turn without a striker penalty. '
    'comment is a short public Russian line (max 150 characters), not private reasoning. '
    'This is a house rules prototype, not official tournament Carrom.'
)


def clean_move(data, player=None):
    if not isinstance(data, dict) or set(data) != set(MOVE_SCHEMA['required']):
        raise ValueError('Move must have exactly x, angle, power, comment')
    for name in ('x', 'angle', 'power'):
        value = data[name]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError('Move numbers must be finite JSON numbers')
    if not BASE_X[0] <= data['x'] <= BASE_X[1] or not 0 <= data['angle'] <= 360 or not 0.15 <= data['power'] <= 1:
        raise ValueError('Move parameters out of range')
    if not isinstance(data['comment'], str) or len(data['comment']) > 150:
        raise ValueError('Comment must be a string of at most 150 characters')
    return dict(data, angle=data['angle'] % 360)


def parse_move(text, player=None):
    if not isinstance(text, str):
        raise ValueError('No model text')
    text = text.strip()
    fenced = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text, re.S)
    if fenced:
        text = fenced.group(1)
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('Duplicate move field')
            obj[key] = value
        return obj
    try:
        data = json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError('Model returned invalid JSON') from exc
    return clean_move(data, player)


def local_move(state):
    player = PLAYERS.index(state['player'])
    base_y = BASE_Y[player]
    coins = state['coins']
    targets = [c for c in coins if c['type'] == COLORS[player]]
    rules = state.get('rules', {})
    if rules.get('queen_pending') is None and rules.get('queen_owner') is None:
        targets += [c for c in coins if c['type'] == 'queen']
    targets = targets or coins
    candidates = []
    for target in targets:
        for px, py in POCKETS:
            dx, dy = px - target['x'], py - target['y']
            length = math.hypot(dx, dy)
            if length < 1 or abs(dy) < 1:
                continue
            gx, gy = target['x'] - 28 * dx / length, target['y'] - 28 * dy / length
            x = gx + (base_y - gy) * dx / dy
            if BASE_X[0] <= x <= BASE_X[1] and (gy - base_y) * dy > 0:
                if all(math.hypot(c['x'] - x, c['y'] - base_y) >= 28.5 for c in coins):
                    candidates.append((length, x, math.degrees(math.atan2(gy - base_y, gx - x)) % 360))
    if candidates:
        _, x, angle = min(candidates)
        return {'x': x, 'angle': angle, 'power': 0.65, 'comment': 'Демо: прицеливаюсь в лузу.'}
    free = [x for x in range(265, 496, 5) if all(
        math.hypot(c['x'] - x, c['y'] - base_y) >= 28.5 for c in coins)]
    if not free:
        raise ValueError('No legal demo placement')
    x = min(free, key=lambda value: abs(value - 380))
    target = min(targets, key=lambda c: math.hypot(c['x'] - x, c['y'] - base_y)) if targets else {'x': x, 'y': 380}
    return {'x': x, 'angle': math.degrees(math.atan2(target['y'] - base_y, target['x'] - x)) % 360,
            'power': 0.75, 'comment': 'Демо: удар по ближайшей фишке.'}


@dataclass
class Decision:
    move: dict
    source: str
    model: str
    latency_ms: int
    usage: dict


def decide(state, settings, client=None):
    start = time.monotonic()
    if settings.mode == 'demo':
        return Decision(clean_move(local_move(state)), 'demo', 'local-geometric-v0.2', 0, {})
    player = state['player']
    content = json.dumps(state, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if player == 'ChatGPT':
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_key, timeout=settings.timeout, max_retries=0)
        response = client.responses.create(
            model=settings.openai_model, instructions=INSTRUCTIONS, input=content,
            max_output_tokens=settings.max_output_tokens, store=False,
            text={'format': {'type': 'json_schema', 'name': 'carrom_move',
                             'strict': True, 'schema': MOVE_SCHEMA}})
        if response.status != 'completed':
            raise ValueError('OpenAI response incomplete')
        text = response.output_text
        usage = {'input_tokens': response.usage.input_tokens,
                 'output_tokens': response.usage.output_tokens} if response.usage else {}
        source, model = 'OpenAI API', settings.openai_model
    elif player == 'Claude':
        if client is None:
            from anthropic import Anthropic
            client = Anthropic(api_key=settings.anthropic_key, timeout=settings.timeout, max_retries=0)
        response = client.messages.create(
            model=settings.anthropic_model, system=INSTRUCTIONS,
            max_tokens=settings.max_output_tokens,
            messages=[{'role': 'user', 'content': content}],
            output_config={'format': {'type': 'json_schema', 'schema': MOVE_SCHEMA}})
        if response.stop_reason != 'end_turn':
            raise ValueError('Claude response incomplete or refused')
        text = ''.join(block.text for block in response.content if getattr(block, 'type', None) == 'text')
        usage = {name: getattr(response.usage, name, 0) for name in (
            'input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')}
        source, model = 'Anthropic API', settings.anthropic_model
    else:
        raise ValueError('Unknown player')
    return Decision(parse_move(text, player), source, model, int((time.monotonic() - start) * 1000), usage)


def choose_move(state):
    """Compatibility entry point retained from v0.1."""
    decision = decide(state, Settings.load())
    return decision.move, decision.source
