"""WinAI / LoseAI 5x5 MVP package.

General-sum (non-zero-sum) Go experiments where each agent has a fixed public
identity (WIN wants to win, LOSE wants to lose) and maximises its *own*
utility.  The MVP deliberately contains no learning: behaviour is produced by
planning (Random / Vector-MCTS) only.
"""

__version__ = "0.7.0"

# Semantic version stamped into every saved record; the independent source
# fingerprint identifies runtime bytes, separately from the Git commit.
CODE_VERSION = "winai_loseai-0.7.0-g1-pass8-estimation"
SCHEMA_VERSION = 2
