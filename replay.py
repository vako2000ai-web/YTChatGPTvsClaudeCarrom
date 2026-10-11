"""Recorded frames, not physics resimulation: replay never imports or calls agents."""
import gzip
import hashlib
import json
import math
from pathlib import Path

FORMAT = 'carrom-frames-v1'


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Recorder:
    def __init__(self, path, state, version, mode, board_theme=None):
        self.path = Path(path)
        self.file = gzip.open(self.path, 'xt', encoding='utf-8', compresslevel=3)
        self.file.write(canonical({'event': 'header', 'format': FORMAT, 'fps': 60,
                                   'version': version, 'mode': mode, 'initial_state': state, 'board_theme': board_theme}) + '\n')
        self.frames = 0
        self.closed = False

    def frame(self, match, timestamp, comment='', status='', move=None, aiming=False):
        if self.closed:
            return
        data = {'event': 'frame', 'time': timestamp, 'state': match.state(),
                'discs': [{'id': i, 'type': d['type'], 'radius': d['radius'],
                           'x': d['body'].position.x, 'y': d['body'].position.y,
                           'vx': d['body'].velocity.x, 'vy': d['body'].velocity.y}
                          for i, d in sorted(match.board.discs.items())],
                'comment': comment, 'status': status, 'move': move, 'aiming': aiming}
        data['checksum'] = hashlib.sha256(canonical(data).encode('utf-8')).hexdigest()
        self.file.write(canonical(data) + '\n')
        self.frames += 1

    def close(self, summary=None):
        if not self.closed:
            self.file.write(canonical({'event': 'footer', 'frames': self.frames, 'summary': summary}) + '\n')
            self.file.close()
            self.closed = True


class Replay:
    def __init__(self, path):
        self.path = Path(path)
        self.frames, self.summary = [], None
        self.complete = False
        total = 0
        try:
            with gzip.open(self.path, 'rt', encoding='utf-8') as file:
                for index, line in enumerate(file):
                    total += len(line)
                    if len(line) > 100_000 or total > 512_000_000 or index > 500_000:
                        raise ValueError('Replay exceeds loading limits')
                    item = json.loads(line)
                    if self.complete:
                        raise ValueError('Data after replay footer')
                    if not isinstance(item, dict):
                        raise ValueError('Invalid replay event')
                    if index == 0:
                        if item.get('event') != 'header' or item.get('format') != FORMAT or item.get('fps') != 60:
                            raise ValueError('Unsupported replay format')
                        self.header = item
                    elif item.get('event') == 'frame':
                        checksum = item.pop('checksum', None)
                        if checksum != hashlib.sha256(canonical(item).encode('utf-8')).hexdigest():
                            raise ValueError('Replay checksum mismatch')
                        self._validate(item)
                        self.frames.append(item)
                    elif item.get('event') == 'footer':
                        if item.get('frames') != len(self.frames):
                            raise ValueError('Replay frame count mismatch')
                        self.summary = item.get('summary')
                        self.complete = True
                    else:
                        raise ValueError('Unknown replay event')
        except (OSError, EOFError, json.JSONDecodeError) as exc:
            raise ValueError('Cannot read replay file') from exc
        if not self.frames or not self.complete:
            raise ValueError('Replay incomplete')
        self.duration = self.frames[-1]['time']
        self.timestamps = [frame['time'] for frame in self.frames]

    def _validate(self, item):
        timestamp = item.get('time')
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError('Invalid replay time')
        if self.frames and timestamp < self.frames[-1]['time']:
            raise ValueError('Nonmonotonic replay time')
        if type(item.get('aiming', False)) is not bool:
            raise ValueError('Invalid replay aiming flag')
        discs = item.get('discs')
        if not isinstance(discs, list) or len(discs) > 20:
            raise ValueError('Invalid replay discs')
        ids = []
        for disc in discs:
            if not isinstance(disc, dict):
                raise ValueError('Invalid replay disc')
            ids.append(disc.get('id'))
            if disc.get('type') not in ('white', 'black', 'queen', 'striker'):
                raise ValueError('Invalid replay disc kind')
            for field in ('x', 'y', 'vx', 'vy', 'radius'):
                value = disc.get(field)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 10000:
                    raise ValueError('Invalid replay coordinates')
            if not 0 < disc['radius'] < 50:
                raise ValueError('Invalid replay radius')
        if any(type(i) is not int or not -1 <= i <= 18 for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid replay ID')
        state = item.get('state')
        if not isinstance(state, dict) or not isinstance(state.get('rules'), dict):
            raise ValueError('Invalid replay state')
        rules = state['rules']
        if rules.get('player_index') not in (0, 1) or not isinstance(rules.get('scores'), list) or len(rules['scores']) != 2:
            raise ValueError('Invalid replay rules')
        try:
            from board import Geometry
            geometry = Geometry.from_snapshot(item['state']['board'])
            if geometry.name not in ('icf-735mm', 'house-v0.2'):
                raise ValueError('Invalid replay geometry')
            numbers = [geometry.coin_radius, geometry.striker_radius, geometry.coin_mass,
                       geometry.striker_mass, geometry.pocket_radius, geometry.outer_radius, geometry.centre_radius]
            numbers += list(geometry.baseline_y) + list(geometry.baseline_ends)
            numbers += [n for interval in geometry.legal_intervals for n in interval]
            numbers += [n for wall in geometry.walls for point in wall for n in point]
            if any(type(n) not in (float, int) or not math.isfinite(n) or not 0 <= n <= 760 for n in numbers):
                raise ValueError('Invalid replay geometry')
            if len(geometry.baseline_y) != 2 or len(geometry.baseline_ends) != 2 or len(geometry.walls) != 4:
                raise ValueError('Invalid replay geometry')
            for name in ('queen_owner', 'queen_pending', 'winner'):
                if rules.get(name) not in (None, 0, 1):
                    raise ValueError('Invalid replay owner')
            if not isinstance(item.get('comment'), str) or not isinstance(item.get('status'), str):
                raise ValueError('Invalid replay text')
            for name in ('turn', 'max_turns'):
                if type(rules[name]) is not int or not 0 <= rules[name] <= 1_000_000:
                    raise ValueError('Invalid replay turn')
            for name in ('scores', 'penalty_debt'):
                if len(rules[name]) != 2 or any(type(n) is not int or not 0 <= n <= 1_000_000 for n in rules[name]):
                    raise ValueError('Invalid replay score')
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError('Invalid replay state') from exc

    def seek(self, seconds):
        from bisect import bisect_right
        if seconds <= 0:
            return 0
        return max(0, bisect_right(self.timestamps, min(max(seconds, 0), self.duration)) - 1)


def inspect_replay(path):
    replay = Replay(path)
    return {'format': FORMAT, 'frames': len(replay.frames), 'duration': replay.duration,
            'summary': replay.summary, 'complete': replay.complete}
