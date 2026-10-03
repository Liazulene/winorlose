"""Agent construction from AgentSpec (isolates the rest of the code from
the concrete agent classes)."""

from __future__ import annotations

from .scripted import SCRIPTED_AGENTS
from .random_agent import RandomAgent
from .vector_mcts import VectorMCTSAgent
from ..spec import AgentSpec, ALGO_RANDOM, ALGO_VECTOR_MCTS


def make_agent(spec: AgentSpec, rng, komi: float = 2.5):
    """Build the agent instance for ``spec`` using the provided RNG stream."""
    if spec.algorithm == ALGO_RANDOM:
        return RandomAgent(spec, rng)
    if spec.algorithm == ALGO_VECTOR_MCTS:
        return VectorMCTSAgent(spec, rng, komi=komi)
    if spec.algorithm in SCRIPTED_AGENTS:
        return SCRIPTED_AGENTS[spec.algorithm](spec, rng, komi=komi)
    raise ValueError(f"unknown algorithm: {spec.algorithm!r}")
