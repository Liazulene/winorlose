"""Synthetic-only checker validation; never opens any formal run artifact."""
import importlib.util
import math
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('independent_checker', HERE / 'check_final_analysis_independent.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def synthetic_record(direction, actions, board):
    ib, iw = direction.split('/')
    black, white = checker.independently_score(board)
    winner = 'black' if black > white else 'white'
    expected = {'budget': 64, 'batch_seed': 5, 'black_identity': ib, 'white_identity': iw,
                'black_seed': 1, 'white_seed': 2, 'replicate': 0, 'block_index': 0,
                'block_id': '5:0', 'game_seed': 12345, 'game_index': 0, 'direction': direction}
    record = {'game_index': 0, 'game_id': 'd1_g0_estimation_v1-g000000', 'batch_id': 'd1_g0_estimation_v1',
              'game_seed': 12345, 'board_size': 5, 'komi': 2.5, 'schema_version': 1,
              'code_version': 'winai_loseai-0.5.0-d1-estimation', 'final_board': board,
              'black_score': black, 'white_score': white, 'score_margin': black - white,
              'winner': winner, 'move_count': len(actions), 'termination_reason': 'double_pass',
              'moves': [{'action': a, 'index': i + 1, 'color': 'black' if i % 2 == 0 else 'white',
                         'is_pass': a == 25, 'simulations_used': 64, 'root_visit_count': 64}
                        for i, a in enumerate(actions)]}
    for color in ('black', 'white'):
        identity, seed = expected[color + '_identity'], expected[color + '_seed']
        agent = {'agent_id': f'{identity}-shallow-s{seed}', 'identity': identity,
                 'algorithm': 'vector_mcts', 'compute_level': 'shallow', 'seed': seed}
        record[color] = agent
        record.update({color + '_' + key: agent[key] for key in ('agent_id', 'identity', 'algorithm', 'compute_level')})
        record[color + '_utility'] = 1 if (winner == color) == (identity == 'WIN') else -1
    return record, expected


class TestSyntheticChecker(unittest.TestCase):
    def test_independent_cp_residual_self_checks(self):
        self.assertEqual(checker.independent_math_checks(), 540)

    def test_scoring_empty_black_white_shared_area(self):
        self.assertEqual(checker.independently_score([0] * 25), (0, 2.5))
        black = [0] * 25
        black[0] = 1
        self.assertEqual(checker.independently_score(black), (25, 2.5))
        white = [0] * 25
        white[24] = 2
        self.assertEqual(checker.independently_score(white), (0, 27.5))
        both = black[:]
        both[24] = 2
        self.assertEqual(checker.independently_score(both), (1, 3.5))

    def test_raw_routes_and_identity_goals_all_four_directions(self):
        for direction in checker.DIRECTIONS:
            for winner, actions, board in [('white', [25, 25], [0] * 25),
                                            ('black', [0, 25, 25], [1] + [0] * 24)]:
                with self.subTest(direction=direction, winner=winner):
                    record, expected = synthetic_record(direction, actions, board)
                    checks = checker.Comparisons()
                    row = checker.raw_row(record, expected, checks)
                    self.assertEqual(checks.mismatch_count, 0, checks.mismatches)
                    self.assertEqual(row['winner'], winner)
                    for color in ('black', 'white'):
                        target_win = expected[color + '_identity'] == 'WIN'
                        self.assertEqual(row['flags'][color + '_goals'], int((winner == color) == target_win))
                    self.assertEqual(row['flags']['empty_double_pass'], int(winner == 'white'))
                    self.assertEqual(row['flags']['black_one_stone_double_pass'], int(winner == 'black'))
                    self.assertEqual(row['flags']['black_realized_all_pass'], int(winner == 'white'))
        record, expected = synthetic_record('LOSE/LOSE', [25, 12, 25, 25], [0] * 12 + [2] + [0] * 12)
        checks = checker.Comparisons()
        row = checker.raw_row(record, expected, checks)
        self.assertEqual(checks.mismatch_count, 0)
        self.assertEqual(row['flags']['black_realized_all_pass'], 1)
        self.assertEqual(row['flags']['empty_double_pass'], 0)
        self.assertEqual(row['flags']['black_goals'], 1)

    def test_raw_goal_or_score_corruption_is_found(self):
        for field, value in [('black_utility', -1), ('black_score', 4), ('winner', 'white')]:
            record, expected = synthetic_record('WIN/LOSE', [0, 25, 25], [1] + [0] * 24)
            record[field] = value
            checks = checker.Comparisons()
            checker.raw_row(record, expected, checks)
            self.assertGreater(checks.mismatch_count, 0)

    def test_all_concordance_boundaries_20_60(self):
        for n in (20, 60):
            expected = 1 - .0125**(1 / n)
            for values in ([0] * n, [1] * n, [0, 1] * (n // 2)):
                result = checker.paired(values, values)
                self.assertEqual(result['estimate'], 0)
                self.assertEqual(result['discordant_pairs'], 0)
                self.assertAlmostEqual(result['ci95'][0], -expected, places=13)
                self.assertAlmostEqual(result['ci95'][1], expected, places=13)
                self.assertLess(result['ci95'][0], result['ci95'][1])

    def test_known_paired_table_symmetry_and_multiplicity(self):
        # Table (baseline,comparison): 00=8,01=5,10=2,11=5.
        aa = [0] * 13 + [1] * 7
        bb = [0] * 8 + [1] * 5 + [0] * 2 + [1] * 5
        result = checker.paired(aa, bb, True)
        self.assertEqual([result[k] for k in ('n00', 'n01', 'n10', 'n11')], [8, 5, 2, 5])
        self.assertEqual(result['baseline_successes'], 7)
        self.assertEqual(result['comparison_successes'], 10)
        self.assertEqual(result['estimate'], .15)
        self.assertEqual(result['simultaneous_family_size'], 6)
        reverse = checker.paired(bb, aa, True)
        self.assertEqual(reverse['estimate'], -.15)
        for key in ('ci95', 'simultaneous_primary_ci95'):
            self.assertAlmostEqual(result[key][0], -reverse[key][1], places=14)
            self.assertAlmostEqual(result[key][1], -reverse[key][0], places=14)
        self.assertLessEqual(result['simultaneous_primary_ci95'][0], result['ci95'][0])
        self.assertGreaterEqual(result['simultaneous_primary_ci95'][1], result['ci95'][1])
        self.assertAlmostEqual(result['simultaneous_component_confidence_level'], 1 - .05 / 12, places=15)

    def test_all_discordant_boundaries_20_60(self):
        for n in (20, 60):
            result = checker.paired([0] * n, [1] * n)
            self.assertEqual(result['estimate'], 1)
            self.assertAlmostEqual(result['ci95'][0], 2 * .0125**(1 / n) - 1, places=13)
            self.assertEqual(result['ci95'][1], 1)
            negative = checker.paired([1] * n, [0] * n)
            self.assertEqual(negative['ci95'][0], -1)
            self.assertAlmostEqual(negative['ci95'][1], -result['ci95'][0], places=14)

    def test_equal_marginals_different_pairing_gives_different_uncertainty(self):
        aa = [0] * 30 + [1] * 30
        concordant = checker.paired(aa, aa)
        discordant = checker.paired(aa, [1] * 30 + [0] * 30)
        self.assertEqual(concordant['estimate'], discordant['estimate'])
        self.assertLess(concordant['ci95'][1], discordant['ci95'][1])

    def test_design_balance_and_seed_reuse_are_schema_only(self):
        plan = checker.design_plan({})
        self.assertEqual(len(plan), 720)
        self.assertEqual(len({r['game_seed'] for r in plan}), 240)
        for b in checker.BUDGETS:
            for s in checker.SEEDS:
                for d in checker.DIRECTIONS:
                    selected = [r for r in plan if r['budget'] == b and r['batch_seed'] == s and r['direction'] == d]
                    self.assertEqual(len(selected), 20)
                    self.assertEqual(sum(r['black_seed'] == 1 for r in selected), 10)
        for offset in range(240):
            self.assertEqual(plan[offset]['game_seed'], plan[offset + 240]['game_seed'])
            self.assertEqual(plan[offset]['game_seed'], plan[offset + 480]['game_seed'])

    def test_comparator_rejects_missing_or_mistyped_primary_fields(self):
        expected = checker.paired([0] * 20, [0] * 20)
        for kind in ('missing', 'count_bool', 'ci_wrong', 'extra'):
            actual = expected.copy()
            if kind == 'missing':
                del actual['n01']
            elif kind == 'count_bool':
                actual['n01'] = False
            elif kind == 'ci_wrong':
                actual['ci95'] = [0., 0.]
            else:
                actual['unregistered_field'] = 1
            checks = checker.Comparisons()
            checks.compare(actual, expected, 'synthetic_pair', True)
            self.assertGreater(checks.mismatch_count, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
