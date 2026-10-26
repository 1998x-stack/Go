"""PUCT search: edges use PARENT-to-play value convention, including terminal pass."""
import math
import random
from dataclasses import dataclass, field

from go_game.core import RulesEngine


@dataclass(frozen=True)
class SearchConfig:
    simulations: int = 16
    c_puct: float = 1.5
    dirichlet_alpha: float = 0.3
    dirichlet_fraction: float = 0.25

    def __post_init__(self):
        if type(self.simulations) is not int or not 1 <= self.simulations <= 100000:
            raise ValueError("simulations must be 1..100000")
        if not math.isfinite(self.c_puct) or self.c_puct <= 0:
            raise ValueError("c_puct must be positive")
        if not math.isfinite(self.dirichlet_alpha) or self.dirichlet_alpha <= 0:
            raise ValueError("dirichlet_alpha must be positive")
        if not 0 <= self.dirichlet_fraction <= 1:
            raise ValueError("dirichlet_fraction must be within [0,1]")


@dataclass
class Edge:
    prior: float
    visits: int = 0
    value_sum: float = 0.0
    child: object = None

    @property
    def q(self):
        return self.value_sum / self.visits if self.visits else 0.0


@dataclass
class Node:
    player: str
    fingerprint: str
    edges: dict = field(default_factory=dict)
    visits: int = 0


@dataclass(frozen=True)
class SearchResult:
    visits: tuple
    policy: tuple
    action: int
    root_value: float
    model_id: str


class UniformPredictor:
    model_id = "uniform-baseline-v1"

    def predict(self, state):
        return [0.0] * (state.rules.board_size ** 2 + 1), 0.0


def _priors(logits, mask):
    if len(logits) != len(mask) or not any(mask):
        raise ValueError("Logits length or nonterminal legal actions invalid")
    legal = []
    for i, allowed in enumerate(mask):
        if allowed:
            v = float(logits[i])
            if not math.isfinite(v):
                raise ValueError("Nonfinite policy logits")
            legal.append((i, v))
    top = max(x[1] for x in legal)
    weights = [(i, math.exp(v - top)) for i, v in legal]
    total = sum(v for _, v in weights)
    return {i: v / total for i, v in weights}


def _terminal_value(state, engine):
    winner = engine.score(state).winner
    if winner == "draw":
        return 0.0
    return 1.0 if winner == state.current_player else -1.0


def _expand(node, state, engine, predictor):
    if state.terminated:
        return _terminal_value(state, engine)
    mask = engine.legal_actions(state)
    logits, value = predictor.predict(state)
    value = float(value)
    if not math.isfinite(value) or not -1.000001 <= value <= 1.000001:
        raise ValueError("Nonfinite or out-of-range value prediction")
    node.edges = {a: Edge(p) for a, p in _priors(logits, mask).items()}
    return max(-1.0, min(1.0, value))


def _mix_dirichlet(node, config, rng):
    if config.dirichlet_fraction == 0:
        return
    actions = list(sorted(node.edges))
    noise = [rng.gammavariate(config.dirichlet_alpha, 1.0) for _ in actions]
    total = sum(noise)
    for a, sample in zip(actions, noise):
        edge = node.edges[a]
        edge.prior = ((1 - config.dirichlet_fraction) * edge.prior
                      + config.dirichlet_fraction * sample / total)


def _select(node, config):
    parent_n = max(1, node.visits)
    return max(sorted(node.edges), key=lambda a: (
        node.edges[a].q
        + config.c_puct * node.edges[a].prior * math.sqrt(parent_n)
        / (1 + node.edges[a].visits),
        -a,
    ))


def _backup(path, value, value_player):
    """Convert the leaf value only when the actual actor perspective changes.

    Legacy double-Pass terminal does not flip current_player; unconditional
    negation on every edge incorrectly labels that terminal node.
    """
    for parent, edge in reversed(path):
        if value_player != parent.player:
            value = -value
        edge.visits += 1
        edge.value_sum += value
        parent.visits += 1
        value_player = parent.player


def _distribution(visits, temperature):
    if temperature < 0 or not math.isfinite(temperature):
        raise ValueError("temperature must be a nonnegative finite number")
    if not any(visits):
        raise ValueError("MCTS did not visit any legal action")
    if temperature == 0:
        result = [0.0] * len(visits)
        result[max(range(len(visits)), key=lambda i: (visits[i], -i))] = 1.0
        return result
    # normalize exponentiation for small temperature to avoid overflow.
    top = max(visits)
    weights = [(n / top) ** (1.0 / temperature) if n else 0.0 for n in visits]
    scale = sum(weights)
    return [v / scale for v in weights]


def _sample(probs, rng):
    r = rng.random()
    cumulative = 0.0
    for index, p in enumerate(probs):
        cumulative += p
        if r < cumulative:
            return index
    return max(range(len(probs)), key=lambda i: probs[i])


def search(state, predictor, config=None, seed=0, temperature=1.0,
           explore=False, engine=None, rng=None):
    """Return canonical visit target (temperature=1) and sampled action.

    One new search tree is built per call; no board-only transposition caching.
    Predictor is pinned throughout search by its immutable model_id.
    """
    engine = engine or RulesEngine()
    config = config or SearchConfig()
    if state.terminated:
        raise ValueError("Cannot search terminal Go state")
    model_id = predictor.model_id
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("Predictor must identify a pinned model")
    rng = rng if rng is not None else random.Random(seed)
    root = Node(state.current_player, state.fingerprint)
    _expand(root, state, engine, predictor)
    if explore:
        _mix_dirichlet(root, config, rng)
    for _ in range(config.simulations):
        branch = state.clone()
        node = root
        path = []
        while True:
            if node.fingerprint != branch.fingerprint:
                raise RuntimeError("MCTS tree state fingerprint mismatch")
            if branch.terminated:
                leaf_value = _terminal_value(branch, engine)
                break
            action = _select(node, config)
            edge = node.edges[action]
            parent = node
            outcome = engine.try_apply(branch, action)
            if not outcome.ok:
                raise RuntimeError("Rules kernel rejected MCTS legal action")
            path.append((parent, edge))
            if edge.child is None:
                edge.child = Node(branch.current_player, branch.fingerprint)
                node = edge.child
                leaf_value = _expand(node, branch, engine, predictor)
                break
            node = edge.child
        _backup(path, leaf_value, branch.current_player)
    if predictor.model_id != model_id:
        raise RuntimeError("Predictor model changed in-flight")
    n = state.rules.board_size ** 2 + 1
    counts = [root.edges[i].visits if i in root.edges else 0 for i in range(n)]
    total = sum(counts)
    policy = tuple(c / total for c in counts)  # training target, not sampling temp
    sampling = _distribution(counts, temperature)
    root_v = sum(edge.value_sum for edge in root.edges.values()) / total
    return SearchResult(tuple(counts), policy, _sample(sampling, rng), root_v, model_id)
