import unittest
from agents import parse_move, local_move


class TestAgents(unittest.TestCase):
    def test_clamp(self):
        move = parse_move('{"x":999,"angle":-90,"power":7,"comment":"test"}', 'ChatGPT')
        self.assertEqual(move['x'], 495)
        self.assertEqual(move['angle'], 270)
        self.assertEqual(move['power'], 1)

    def test_local(self):
        state = {'player': 'Claude', 'coins': [{'x':380,'y':380,'type':'black'}]}
        move = local_move(state)
        self.assertTrue(0 <= move['angle'] <= 360)
        self.assertGreater(move['power'], 0)

if __name__ == '__main__':
    unittest.main()
