#!/usr/bin/env python3
"""Lightweight Echo State Network (reservoir computing) for daily Tmax buckets.

Stdlib-only. The reservoir weights stay fixed; only the ridge-regularized
readout is trained. This is intentionally an experimental forecast layer:
it must be evaluated walk-forward against persistence/NWP before use.
"""

import math
import random
from dataclasses import dataclass


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _mat_vec(m, v):
    return [_dot(row, v) for row in m]


def _softmax(xs):
    m = max(xs)
    ex = [math.exp(max(-60.0, min(60.0, x - m))) for x in xs]
    s = sum(ex) or 1.0
    return [x / s for x in ex]


def _solve_ridge(x, y, ridge):
    """Solve (X'X + ridge I)W = X'Y with Gauss-Jordan elimination."""
    n = len(x[0])
    k = len(y[0])
    a = [[0.0] * (n + k) for _ in range(n)]
    for i in range(n):
        for j in range(n):
            a[i][j] = sum(row[i] * row[j] for row in x)
        a[i][i] += ridge
        for c in range(k):
            a[i][n + c] = sum(x[r][i] * y[r][c] for r in range(len(x)))

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("singular ridge system")
        a[col], a[pivot] = a[pivot], a[col]
        p = a[col][col]
        for j in range(col, n + k):
            a[col][j] /= p
        for r in range(n):
            if r == col:
                continue
            q = a[r][col]
            if abs(q) < 1e-15:
                continue
            for j in range(col, n + k):
                a[r][j] -= q * a[col][j]

    return [row[n:] for row in a]


@dataclass
class ReservoirConfig:
    size: int = 96
    spectral_radius: float = 0.85
    leak: float = 0.35
    input_scale: float = 0.8
    ridge: float = 1e-2
    seed: int = 42


class EchoStateTmax:
    """ESN classifier over integer Tmax buckets."""

    def __init__(self, input_size, buckets, config=None):
        self.config = config or ReservoirConfig()
        self.input_size = input_size
        self.buckets = list(buckets)
        rng = random.Random(self.config.seed)
        n = self.config.size

        self.win = [[rng.uniform(-1, 1) * self.config.input_scale
                     for _ in range(input_size + 1)] for _ in range(n)]
        w = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if rng.random() < 0.08:
                    w[i][j] = rng.uniform(-1, 1)

        # Scale sparse recurrent matrix to the requested spectral radius using
        # power iteration; no numpy dependency required.
        v = [1.0 / math.sqrt(n)] * n
        for _ in range(30):
            nv = _mat_vec(w, v)
            norm = math.sqrt(sum(z * z for z in nv)) or 1.0
            v = [z / norm for z in nv]
        eig = math.sqrt(sum(z * z for z in _mat_vec(w, v)))
        scale = self.config.spectral_radius / eig if eig > 1e-12 else 1.0
        self.w = [[z * scale for z in row] for row in w]
        self.state = [0.0] * n
        self.readout = None

    def reset(self):
        self.state = [0.0] * self.config.size

    def step(self, x):
        if len(x) != self.input_size:
            raise ValueError(f"expected {self.input_size} inputs, got {len(x)}")
        u = [1.0] + list(x)
        recurrent = _mat_vec(self.w, self.state)
        inp = _mat_vec(self.win, u)
        candidate = [math.tanh(a + b) for a, b in zip(recurrent, inp)]
        l = self.config.leak
        self.state = [(1 - l) * old + l * new for old, new in zip(self.state, candidate)]
        return self.state[:]

    def _features(self, state):
        return [1.0] + state

    def fit(self, sequences, targets):
        if not sequences or len(sequences) != len(targets):
            raise ValueError("training sequences and targets must be non-empty and equal length")
        x, y = [], []
        index = {b: i for i, b in enumerate(self.buckets)}
        for seq, target in zip(sequences, targets):
            self.reset()
            for row in seq:
                self.step(row)
            x.append(self._features(self.state))
            label = min(self.buckets, key=lambda b: abs(b - target))
            yy = [0.0] * len(self.buckets)
            yy[index[label]] = 1.0
            y.append(yy)
        self.readout = _solve_ridge(x, y, self.config.ridge)
        return len(x)

    def predict_proba(self, sequence):
        if self.readout is None:
            raise RuntimeError("model is not fitted")
        self.reset()
        for row in sequence:
            self.step(row)
        logits = _mat_vec(self.readout, self._features(self.state))
        probs = _softmax(logits)
        return {str(b): round(p, 6) for b, p in zip(self.buckets, probs)}

    def predict_bucket(self, sequence):
        probs = self.predict_proba(sequence)
        return max(probs, key=probs.get), probs
