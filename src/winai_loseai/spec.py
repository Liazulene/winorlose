"""Agent specifications, compute tiers and default individuals."""

from __future__ import annotations

from dataclasses import dataclass, asdict

from .identity import Identity, coerce_identity

# Algorithm tags
ALGO_RANDOM = "random"
ALGO_VECTOR_MCTS = "vector_mcts"

# Compute tiers -> simulations per move.
# deep is provided for later use; it is NOT part of the MVP acceptance gate.
COMPUTE_SIMS = {
    "shallow": 64,
    "medium": 256,
    "deep": 1024,
}

# RandomAgent has no real compute budget; store a stable tag.
COMPUTE_NONE = "none"

DEFAULT_BOARD_SIZE = 5
DEFAULT_KOMI = 2.5

# Per-move search-record keys (spec section 7).
MCTS_MOVE_KEYS = (
    "root_visit_count",
    "action_visit_counts",
    "action_q_black",
    "action_q_white",
    "simulations_used",
    "search_time_ms",
)


@dataclass(frozen=True)
class AgentSpec:
    """A unique agent definition.

    Fields
    ------
    agent_id : str
        Unique id of this individual.
    identity : Identity
        WIN or LOSE (public before the game).
    algorithm : str
        ALGO_RANDOM or ALGO_VECTOR_MCTS.
    compute_level : str
        "shallow" / "medium" / "deep" (MCTS) or COMPUTE_NONE (random).
    seed : int
        Individual seed.  For MCTS it only influences rollout and tie-break
        noise; for Random it does not change the move distribution.
    """

    agent_id: str
    identity: Identity
    algorithm: str
    compute_level: str
    seed: int

    def __post_init__(self):
        object.__setattr__(self, "identity", coerce_identity(self.identity))

    def simulations(self):
        if self.algorithm != ALGO_VECTOR_MCTS:
            return None
        return COMPUTE_SIMS[self.compute_level]

    def to_dict(self):
        d = asdict(self)
        d["identity"] = self.identity.value
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            agent_id=d["agent_id"],
            identity=coerce_identity(d["identity"]),
            algorithm=d["algorithm"],
            compute_level=d["compute_level"],
            seed=int(d["seed"]),
        )


def mcts_individuals(identity, compute_level: str, n_seeds: int = 4, base_seed: int = 1):
    """4 seed-variants of a MCTS individual for one identity + compute tier."""
    out = []
    for k in range(base_seed, base_seed + n_seeds):
        out.append(
            AgentSpec(
                agent_id=f"{identity.value}-{compute_level}-s{k}",
                identity=identity,
                algorithm=ALGO_VECTOR_MCTS,
                compute_level=compute_level,
                seed=k,
            )
        )
    return out


def random_spec(identity, seed: int = 0, agent_id: str | None = None) -> AgentSpec:
    """A RandomAgent carrying an identity (identity does not affect its moves)."""
    return AgentSpec(
        agent_id=agent_id or f"RAND-{coerce_identity(identity).value}",
        identity=identity,
        algorithm=ALGO_RANDOM,
        compute_level=COMPUTE_NONE,
        seed=seed,
    )


# Default random baselines reused by the smoke / batch commands.
RANDOM_WIN = random_spec(Identity.WIN, seed=0)
RANDOM_LOSE = random_spec(Identity.LOSE, seed=1)
RANDOM_AGENTS = (RANDOM_WIN, RANDOM_LOSE)
