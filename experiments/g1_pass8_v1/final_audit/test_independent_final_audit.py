"""Synthetic independent-audit tests. No production imports or game execution."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest

import independent_final_audit as audit


PROTOCOL = dict(batch_seeds=[8, 9, 10], schedule_seed=2026100401,
    identity_directions=[["WIN", "WIN"], ["LOSE", "LOSE"], ["WIN", "LOSE"], ["LOSE", "WIN"]],
    agent_seed_orientations=[[1, 2], [2, 1]])
PROVENANCE = dict(code_version="synthetic", schema_version=2,
                  source_fingerprint="synthetic", python_version="synthetic")
PLACEMENTS = [0, 1, 24, 5, 23, 20, 22, 21, 12, 13, 10, 14]


def make_record(index=0, actions=None):
    cells, plan = audit.design(PROTOCOL)
    cell, entry = cells[index], plan[index]
    rule = entry["pass_min_ply"]
    if actions is None:
        actions = PLACEMENTS[:8+2*(index % 3)]+[25, 25] if rule else (
            ([25, 25], [0, 25, 25], [25, 0, 25, 25], PLACEMENTS[:6]+[25, 25])[index % 4])
    rec = dict(game_id=f"{audit.BATCH}-g{index:06d}", batch_id=audit.BATCH,
        game_index=index, game_seed=entry["game_seed"], board_size=5, komi=2.5,
        pass_min_ply=rule, ruleset=audit.RULES[rule], **PROVENANCE)
    for color in ("black", "white"):
        rec[color] = copy.deepcopy(entry[color])
        for key in ("agent_id", "identity", "algorithm", "compute_level"):
            rec[color+"_"+key] = entry[color][key]
    board, moves = [0]*25, []
    for i, action in enumerate(actions):
        color, code = ("black", 1) if i % 2 == 0 else ("white", 2)
        # A deliberately minimal reported search tree, not simulated MCTS.
        keys = [str(action)]
        if i >= rule and "25" not in keys:
            keys.append("25")
        visits = {key: 256 if key == str(action) else 0 for key in keys}
        qb = {key: 1 if visits[key] else None for key in keys}
        qw = {key: (1 if cell["black_identity"] != cell["white_identity"] else -1)
              if visits[key] else None for key in keys}
        moves.append(dict(index=i+1, color=color, action=action, is_pass=action == 25,
            legal_action_count=len(keys), superko_excluded=0,
            root_visit_count=256, simulations_used=256, action_visit_counts=visits,
            action_q_black=qb, action_q_white=qw, search_time_ms=10.0+i))
        if action != 25:
            board, _ = audit.apply_placement(board, action, code)
    scored = audit.area(board)
    ub, uw = audit.utilities(scored["winner"], cell["black_identity"], cell["white_identity"])
    rec.update(moves=moves, final_board=board, move_count=len(actions),
        black_utility=ub, white_utility=uw, termination_reason="double_pass",
        superko_rejections=0, game_wall_ms=1000+index, **scored)
    return rec, cell, entry


def make_rows():
    rows = []
    for index in range(48):
        rec, cell, entry = make_record(index)
        row, errors = audit.reconstruct(rec, cell, entry, 1234+index, PROVENANCE)
        if errors:
            raise AssertionError(errors)
        rows.append(row)
    return rows


class GeometryTests(unittest.TestCase):
    def test_empty_area(self):
        self.assertEqual(audit.area([0]*25), dict(black_score=0., white_score=2.5,
            score_margin=-2.5, winner="white"))

    def test_single_black_claims_connected_empty(self):
        board = [0]*25
        board[12] = 1
        self.assertEqual(audit.area(board)["black_score"], 25.)
        self.assertEqual(audit.area(board)["white_score"], 2.5)

    def test_single_white_claims_connected_empty(self):
        board = [0]*25
        board[24] = 2
        self.assertEqual(audit.area(board)["white_score"], 27.5)

    def test_mixed_empty_is_neutral(self):
        board = [0]*25
        board[0], board[24] = 1, 2
        self.assertEqual(audit.area(board)["black_score"], 1.)
        self.assertEqual(audit.area(board)["white_score"], 3.5)

    def test_separate_owned_regions(self):
        board = [1, 1, 1, 2, 2, 1, 0, 1, 2, 0, 1, 1, 1, 2, 2,
                 1, 1, 1, 2, 2, 1, 1, 1, 2, 2]
        self.assertEqual(audit.area(board)["black_score"], 15.)
        self.assertEqual(audit.area(board)["white_score"], 12.5)

    def test_capture_group_not_counted_twice(self):
        board = [0]*25
        board[6] = board[7] = 2
        for i in (1, 5, 11, 2, 8):
            board[i] = 1
        after, captured = audit.apply_placement(board, 12, 1)
        self.assertEqual(captured, 2)
        self.assertEqual((after[6], after[7]), (0, 0))

    def test_suicide_rejected(self):
        board = [0]*25
        board[1] = board[5] = 1
        with self.assertRaisesRegex(ValueError, "suicide"):
            audit.apply_placement(board, 0, 2)

    def test_identity_truth_table(self):
        self.assertEqual(audit.utilities("black", "WIN", "WIN"), [1, -1])
        self.assertEqual(audit.utilities("black", "LOSE", "LOSE"), [-1, 1])
        self.assertEqual(audit.utilities("black", "WIN", "LOSE"), [1, 1])
        self.assertEqual(audit.utilities("white", "WIN", "LOSE"), [-1, -1])
        self.assertEqual(audit.utilities("white", "LOSE", "WIN"), [1, 1])
        self.assertEqual(audit.utilities("draw", "WIN", "LOSE"), [0, 0])


class ArithmeticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = make_rows()
        cls.expected = audit.assemble(cls.rows)

    def test_48_24_balance(self):
        self.assertEqual(len(self.rows), 48)
        self.assertEqual(len(self.expected["paired_differences"]), 24)
        for name in audit.RULES.values():
            for direction in audit.DIRECTIONS:
                self.assertEqual(self.expected["groups"][name]["directions"][direction]["n"], 6)
                for seed in ("8", "9", "10"):
                    self.assertEqual(self.expected["groups"][name]["seeds"][seed][direction]["n"], 2)

    def test_quantile_known_values(self):
        stats = audit.distribution([2, 3, 10, 60])
        self.assertEqual(stats["median"], 6.5)
        self.assertEqual(stats["q1"], 2.75)
        self.assertEqual(stats["q3"], 22.5)
        self.assertAlmostEqual(stats["p90"], 45.)
        self.assertAlmostEqual(stats["p95"], 52.5)
        self.assertEqual(stats["mean"], 18.75)
        self.assertIsNone(audit.distribution([])["mean"])

    def test_extra_delta_exact_minus_eight(self):
        for pair in self.expected["paired_differences"]:
            self.assertEqual(pair["extra_length_delta"], pair["length_delta"]-8)

    def test_equal_direction_weighting(self):
        # Unequal row counts deliberately distinguish equal-direction weighting.
        rows = [copy.deepcopy(self.rows[0]) for _ in range(7)]
        data = [("WIN", "WIN", 10)]*4+[("LOSE", "LOSE", 20),
                ("WIN", "LOSE", 30), ("LOSE", "WIN", 50)]
        for r, (ib, iw, length) in zip(rows, data):
            r.update(black_identity=ib, white_identity=iw, move_count=length,
                     pass_min_ply=0, block_id=str(length))
        stats = audit.assemble(rows)["supplemental_equal_direction_means"]["G0"]["pooled"]
        self.assertEqual(stats["same_mean"], 15)
        self.assertEqual(stats["mixed_mean"], 40)
        self.assertEqual(stats["mixed_minus_same"], 25)
        self.assertEqual(stats["mixed_minus_WW"], 30)
        self.assertEqual(stats["mixed_minus_LL"], 20)

    def test_event_denominator_excludes_unavailable_next_action(self):
        row = copy.deepcopy(self.rows[0])
        row["pass_proposals"] = [dict(proposer="black", instant_utilities=[1, 1],
            next_action_available=True, accepted=True), dict(proposer="black",
            instant_utilities=[1, 1], next_action_available=True, accepted=False),
            dict(proposer="black", instant_utilities=[1, 1], next_action_available=False, accepted=None)]
        stats = audit.summarize([row])["pass_proposal_acceptance"]
        self.assertEqual(stats["black_proposer_favorable_True"], dict(opportunities=2, accepted=1))

    def test_pass_and_capture_and_prefix_hand_calculation(self):
        index = next(i for i, e in enumerate(audit.design(PROTOCOL)[1]) if e["pass_min_ply"] == 0)
        rec, cell, entry = make_record(index, [25, 0, 25, 25])
        row, errors = audit.reconstruct(rec, cell, entry, 1, PROVENANCE)
        self.assertEqual(errors, [])
        self.assertEqual(row["first_pass_action"], 1)
        self.assertEqual(row["color_counts"]["black"]["passes"], 2)
        self.assertEqual([e["accepted"] for e in row["pass_proposals"]], [False, True])
        self.assertEqual([e["score_margin"] for e in row["pass_proposals"]], [-2.5, -27.5])
        self.assertIsNone(row["prefixes"]["8"]["raw"])
        self.assertEqual(row["prefixes"]["8"]["END_padded"], [25, 0, 25, 25, -1, -1, -1, -1])
        rec, cell, entry = make_record(0, PLACEMENTS[:8]+[25, 25])
        row, errors = audit.reconstruct(rec, cell, entry, 1, PROVENANCE)
        self.assertEqual(errors, [])
        self.assertEqual(row["color_counts"]["black"]["captured_by_opponent"], 1)

    def test_uncorrupted_analysis_matches(self):
        self.assertEqual(audit.differences(self.expected, copy.deepcopy(self.expected)), [])

    def test_deliberately_corrupted_analysis_detected(self):
        # One change in every principal output family; each must be localized.
        mutations = [
            ("record count", ("n_records",)),
            ("direction wins", ("groups", "G0", "directions", "WIN/WIN", "black_board_wins")),
            ("per-seed utility", ("groups", "G1-pass8", "seeds", "8", "WIN/LOSE", "joint_goals")),
            ("length quantile", ("groups", "G0", "all", "length", "p95")),
            ("first pass", ("groups", "G1-pass8", "all", "first_pass_action", "mean")),
            ("pass delay", ("groups", "G1-pass8", "all", "first_legal_pass_delay", "median")),
            ("captures", ("rows", 0, "color_counts", "black", "captured_by_opponent")),
            ("prefix", ("rows", 0, "prefixes", "8", "END_padded", 0)),
            ("prefix concentration", ("groups", "G0", "all", "prefixes", "12", "END_padded", "top1_count")),
            ("event denominator", ("groups", "G1-pass8", "all", "pass_proposal_acceptance", "black_proposer_favorable_True", "opportunities")),
            ("event numerator", ("groups", "G0", "all", "pass_proposal_acceptance", "white_proposer_favorable_False", "accepted")),
            ("raw paired delta", ("paired_differences", 0, "length_delta")),
            ("extra paired delta", ("paired_differences", 0, "extra_length_delta")),
            ("boardwinner paired delta", ("paired_differences", 0, "black_board_win_delta")),
            ("goal paired summary", ("paired_summaries", "8", "WIN/LOSE", "joint_goal_delta", "mean")),
            ("equal direction mean", ("supplemental_equal_direction_means", "G0", "pooled", "mixed_minus_same")),
        ]
        for name, path in mutations:
            with self.subTest(name=name):
                altered = copy.deepcopy(self.expected)
                value = altered
                for step in path[:-1]:
                    value = value[step]
                value[path[-1]] += 1
                issues = audit.differences(self.expected, altered, "analysis")
                self.assertEqual(len(issues), 1)
                self.assertIn(str(path[-1]), issues[0])
        altered = copy.deepcopy(self.expected)
        altered["paired_differences"].pop()
        self.assertTrue(audit.differences(self.expected, altered))
        altered = copy.deepcopy(self.expected)
        del altered["groups"]["G0"]["seeds"]["9"]
        self.assertTrue(audit.differences(self.expected, altered))
        altered = copy.deepcopy(self.expected)
        altered["rows"][0]["pass_proposals"][0]["instant_utilities"][0] *= -1
        self.assertTrue(audit.differences(self.expected, altered))


class RecordCorruptionTests(unittest.TestCase):
    def test_bad_source_and_rule_and_budget_rejected(self):
        for key, wrong in (("source_fingerprint", "bad"), ("ruleset", "G0"),
                           ("pass_min_ply", 0), ("black_utility", 9), ("black_score", 100)):
            with self.subTest(key=key):
                rec, cell, entry = make_record(0)
                rec[key] = wrong
                self.assertTrue(audit.reconstruct(rec, cell, entry, 1, PROVENANCE)[1])
        for key in ("root_visit_count", "simulations_used"):
            rec, cell, entry = make_record(0)
            rec["moves"][0][key] = 255
            self.assertTrue(audit.reconstruct(rec, cell, entry, 1, PROVENANCE)[1])

    def test_early_root_pass_rejected(self):
        rec, cell, entry = make_record(0)
        for key in ("action_visit_counts", "action_q_black", "action_q_white"):
            rec["moves"][0][key]["25"] = 0 if key == "action_visit_counts" else None
        rec["moves"][0]["legal_action_count"] += 1
        self.assertIn("pass root membership", " ".join(audit.reconstruct(rec, cell, entry, 1, PROVENANCE)[1]))

    def test_missing_late_root_pass_rejected(self):
        rec, cell, entry = make_record(0, PLACEMENTS[:10]+[25, 25])
        move = rec["moves"][8]
        for key in ("action_visit_counts", "action_q_black", "action_q_white"):
            del move[key]["25"]
        move["legal_action_count"] -= 1
        self.assertIn("pass root membership", " ".join(audit.reconstruct(rec, cell, entry, 1, PROVENANCE)[1]))

    def test_early_actual_pass_rejected(self):
        rec, cell, entry = make_record(0, [25, 25])
        errors = audit.reconstruct(rec, cell, entry, 1, PROVENANCE)[1]
        self.assertIn("early actual pass", " ".join(errors))

    def test_final_board_corruption_rejected(self):
        rec, cell, entry = make_record(0)
        rec["final_board"][0] = 1
        self.assertIn("final_board", " ".join(audit.reconstruct(rec, cell, entry, 1, PROVENANCE)[1]))

    def test_after_doublepass_rejected(self):
        rec, cell, entry = make_record(0, PLACEMENTS[:8]+[25, 25, 25])
        self.assertIn("double pass before end", " ".join(audit.reconstruct(rec, cell, entry, 1, PROVENANCE)[1]))

    def test_no_production_or_third_party_imports(self):
        tree = ast.parse(Path(audit.__file__).read_text())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])
        self.assertTrue(modules <= {"argparse", "collections", "hashlib", "json", "math", "pathlib", "random", "sys"})

    def test_boolean_numeric_and_nan_corruption_rejected(self):
        self.assertTrue(audit.differences({"n": 1}, {"n": True}))
        self.assertTrue(audit.differences({"n": 1.}, {"n": float("nan")}))


class FileAuditTests(unittest.TestCase):
    """Entire auditor on 48 tiny hand-built records, never actual pilot games."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="g1_independent_audit_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exp = self.root/"experiments/g1_pass8_v1"
        self.out = self.root/"outputs/g1_pass8_pilot_v1"
        self.exp.mkdir(parents=True)
        (self.out/"games").mkdir(parents=True)
        self.old_protocol_sha, self.old_plan_sha = audit.PROTOCOL_SHA, audit.PLAN_SHA
        self.addCleanup(self.restore_constants)
        for file in ("run.py", "src/winai_loseai/__init__.py", "scripts/run_g1_pass8.py",
                     "scripts/measure_g1_pass8_chunk.py", "tests/test_synthetic.py"):
            target = self.root/file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Synthetic audit fixture only.\n", encoding="utf-8")
        self.write(self.exp/"preregistration.json", PROTOCOL)
        self.write(self.out/"preregistration.json", PROTOCOL)
        cells, plan = audit.design(PROTOCOL)
        self.write(self.exp/"frozen_plan.json", plan)
        self.write(self.out/"plan.json", plan)
        self.write(self.out/"game_seeds.json", [dict(index=e["index"], game_seed=e["game_seed"]) for e in plan])
        audit.PROTOCOL_SHA = audit.digest(self.exp/"preregistration.json")
        audit.PLAN_SHA = audit.digest(self.exp/"frozen_plan.json")
        inventory = {file: audit.digest(self.root/file) for file in ("run.py", "src/winai_loseai/__init__.py")}
        fingerprint = audit.hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        provenance = dict(PROVENANCE, source_fingerprint=fingerprint)
        source_lock = dict(provenance, files=inventory, algorithm="sha256-utf8-lf-path-map-v1")
        self.write(self.exp/"pre_execution_source_lock.json", source_lock)
        self.write(self.out/"source_lock.json", source_lock)
        experiment_lock = dict(provenance, experiment_id=audit.EXPERIMENT,
            preregistration_sha256=audit.PROTOCOL_SHA, entry_point_sha256=audit.digest(self.root/"scripts/run_g1_pass8.py"),
            measurement_script_sha256=audit.digest(self.root/"scripts/measure_g1_pass8_chunk.py"),
            scipy_version="synthetic", numpy_version="synthetic")
        self.write(self.out/"experiment_lock.json", experiment_lock)
        self.write(self.exp/"pre_execution_lock.json", dict(experiment_lock,
            test_files_sha256={"tests/test_synthetic.py": audit.digest(self.root/"tests/test_synthetic.py")}))
        agents = {}
        for entry in plan:
            for color in ("black", "white"):
                agents[entry[color]["agent_id"]] = entry[color]
        self.write(self.out/"manifest.json", dict(batch_id=audit.BATCH, kind=audit.EXPERIMENT,
            status="completed", requested_games=48, planned_game_count=48, completed_game_count=48,
            completed_indexes=list(range(48)), board_size=5, komi=2.5, batch_seed=[8, 9, 10],
            concurrency=1, pass_min_plies=[0, 8], budget=256, schedule_seed=2026100401,
            agents=list(agents.values()), **provenance))
        rows, metadata = [], []
        for index in range(48):
            rec, cell, entry = make_record(index)
            rec.update(provenance)
            file = self.out/"games"/(rec["game_id"]+".json")
            self.write(file, rec)
            row, errors = audit.reconstruct(rec, cell, entry, file.stat().st_size, provenance)
            self.assertEqual(errors, [])
            rows.append(row)
            meta = {key: value for key, value in rec.items() if key not in ("black", "white", "moves")}
            meta.update(opening_actions=row["actions"][:12], game_file="games/"+file.name)
            metadata.append(meta)
        (self.out/"games.jsonl").write_text("\n".join(json.dumps(m) for m in metadata)+"\n")
        self.write(self.out/"analysis.json", audit.assemble(rows))

    def restore_constants(self):
        audit.PROTOCOL_SHA, audit.PLAN_SHA = self.old_protocol_sha, self.old_plan_sha

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")

    def snapshot(self):
        return {str(file.relative_to(self.root)): audit.digest(file) for file in self.root.rglob("*") if file.is_file()}

    def test_complete_file_audit_and_read_only_inputs(self):
        before = self.snapshot()
        report, analysis = audit.audit(self.root, self.out)
        self.assertEqual(report["problems"], [])
        self.assertTrue(report["passed"])
        self.assertEqual(report["n_records"], 48)
        self.assertEqual(report["n_pairs"], 24)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(analysis["n_records"], 48)

    def test_persisted_corrupt_analysis_fails_end_to_end(self):
        path = self.out/"analysis.json"
        data = audit.read(path)
        data["paired_differences"][0]["black_board_win_delta"] += 1
        data["groups"]["G0"]["all"]["pass_proposal_acceptance"]["black_proposer_favorable_True"]["opportunities"] += 1
        self.write(path, data)
        report, _ = audit.audit(self.root, self.out)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["problems"]), 2)
        self.assertTrue(any("black_board_win_delta" in p for p in report["problems"]))
        self.assertTrue(any("opportunities" in p for p in report["problems"]))

    def test_source_and_metadata_corruption_fail(self):
        (self.root/"run.py").write_text("# Deliberately changed.\n")
        metadata = [json.loads(line) for line in (self.out/"games.jsonl").read_text().splitlines()]
        metadata[0]["move_count"] += 1
        (self.out/"games.jsonl").write_text("\n".join(json.dumps(m) for m in metadata)+"\n")
        report, _ = audit.audit(self.root, self.out)
        self.assertFalse(report["passed"])
        self.assertTrue(any("source" in problem for problem in report["problems"]))
        self.assertTrue(any("metadata" in problem for problem in report["problems"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
