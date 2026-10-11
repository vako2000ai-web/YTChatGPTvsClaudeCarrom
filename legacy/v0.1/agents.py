"""AI turns: strict JSON, optional model API calls, deterministic local fallback."""
import json
import math
import os
import re
from typing import Any


def local_move(state: dict[str, Any]) -> dict[str, Any]:
    """Aim from the baseline at the nearest own coin. A simple demonstrator, not strong AI."""
    side = state['player']
    base_y = 665 if side == 'ChatGPT' else 95
    base_x = 380
    target_type = 'white' if side == 'ChatGPT' else 'black'
    targets = [c for c in state['coins'] if c['type'] == target_type]
    if not targets:
        targets = [c for c in state['coins'] if c['type'] == 'queen']
    if not targets:
        targets = state['coins']
    if not targets:
        return {'x': base_x, 'angle': -90 if side == 'ChatGPT' else 90, 'power': 0.5, 'comment': 'На доске нет целей.'}
    target = min(targets, key=lambda c: abs(c['y'] - base_y))
    angle = math.degrees(math.atan2(target['y'] - base_y, target['x'] - base_x))
    return {'x': base_x, 'angle': angle, 'power': 0.75, 'comment': 'Пытаюсь попасть по ближайшей фишке.'}


def clean_move(data: dict[str, Any], player: str) -> dict[str, Any]:
    x = float(data.get('x', 380))
    angle = float(data.get('angle', -90 if player == 'ChatGPT' else 90))
    power = float(data.get('power', 0.7))
    if not all(math.isfinite(n) for n in (x, angle, power)):
        raise ValueError('Non-finite move')
    return {
        'x': max(265, min(495, x)),
        'angle': angle % 360,
        'power': max(0.15, min(1, power)),
        'comment': str(data.get('comment', 'Делаю ход.'))[:150],
    }


def parse_move(text: str, player: str) -> dict[str, Any]:
    # Require a plain JSON object; tolerate fenced response as fallback.
    try:
        return clean_move(json.loads(text), player)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r'\{[^{}]+\}', text, flags=re.S)
        if not match:
            raise ValueError('Model returned no JSON object')
        return clean_move(json.loads(match.group(0)), player)


def choose_move(state: dict[str, Any]) -> tuple[dict[str, Any], str]:
    player = state['player']
    if os.getenv('MODE', 'demo').lower() != 'api':
        return clean_move(local_move(state), player), 'demo'
    instructions = (
        'You are an AI playing carrom on a 760x760 board. '
        'Return ONLY one JSON object with x (striker baseline x position 265..495), '
        'angle (degrees, atan2 direction: 0 right, 90 down, 180 left, 270 up), '
        'power (0.15..1.0), comment (one short entertaining Russian sentence). '
        'The striker starts at (x,665) for ChatGPT, (x,95) for Claude. '
        'ChatGPT pockets white pieces; Claude pockets black pieces. '
        'Pockets are near (45,45),(715,45),(45,715),(715,715). '
        'Physics includes collisions; do not request impossible parameters. '
        'This comment is fictional on-air banter, not your private reasoning.'
    )
    content = instructions + '\nSTATE JSON:\n' + json.dumps(state, ensure_ascii=False)
    if player == 'ChatGPT':
        from openai import OpenAI
        if not os.getenv('OPENAI_API_KEY'):
            raise RuntimeError('OPENAI_API_KEY is missing')
        response = OpenAI(timeout=25).responses.create(
            model=os.getenv('OPENAI_MODEL', 'gpt-5.4'), input=content,
            max_output_tokens=240,
        )
        return parse_move(response.output_text, player), 'OpenAI API'
    from anthropic import Anthropic
    if not os.getenv('ANTHROPIC_API_KEY'):
        raise RuntimeError('ANTHROPIC_API_KEY is missing')
    response = Anthropic(timeout=25).messages.create(
        model=os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-5-20250929'),
        max_tokens=300, messages=[{'role': 'user', 'content': content}],
    )
    text = ''.join(block.text for block in response.content if getattr(block, 'type', None) == 'text')
    return parse_move(text, player), 'Anthropic API'
