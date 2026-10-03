"""WinAI / LoseAI 5x5 MVP package.

General-sum (non-zero-sum) Go experiments where each agent has a fixed public
identity (WIN wants to win, LOSE wants to lose) and maximises its *own*
utility.  The MVP deliberately contains no learning: behaviour is produced by
planning (Random / Vector-MCTS) only.
"""

__version__ = "0.5.0"

# Version tag stamped into every saved record.  This directory is not a git
# repository, so we use an explicit version string instead of a commit hash.
CODE_VERSION = "winai_loseai-0.5.0-d1-estimation"
SCHEMA_VERSION = 1
