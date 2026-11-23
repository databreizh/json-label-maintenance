"""Reference implementations for JSON value trees (Python 3.10+)."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field
from fractions import Fraction

from additional_schemes import dde_ancestor, dde_between, qed_ticks


def encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")


def load_json(file):
    def unique_members(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Duplicate object member")
        return result

    def reject_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.load(file, object_pairs_hook=unique_members, parse_constant=reject_constant)


@dataclass
class Node:
    uid: int
    kind: str
    value: object = None
    children: list[tuple[str | int, Node]] = field(default_factory=list)


class JsonTree:
    def __init__(self, value):
        self._ids = itertools.count(1)
        self.root = self._build(value)

    def _build(self, value):
        uid = next(self._ids)
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("Object keys must be strings")
            return Node(uid, "object", children=[
                (key, self._build(value[key])) for key in sorted(value)
            ])
        if isinstance(value, list):
            return Node(uid, "array", children=[
                (index, self._build(item)) for index, item in enumerate(value)
            ])
        if type(value) not in (type(None), str, bool, int, float):
            raise ValueError("Unsupported JSON value")
        encode(value)
        return Node(uid, "scalar", value)

    def at(self, path):
        node = self.root
        for token in path:
            if type(token) is int and node.kind == "array" and 0 <= token < len(node.children):
                node = node.children[token][1]
            elif isinstance(token, str) and node.kind == "object":
                node = dict(node.children)[token]
            else:
                raise KeyError(path)
        return node

    def insert(self, parent_path, key, value):
        parent = self.at(parent_path)
        if parent.kind == "array" and type(key) is int and 0 <= key <= len(parent.children):
            parent.children.insert(key, (key, self._build(value)))
            self._reindex(parent)
        elif parent.kind == "object" and isinstance(key, str) and key not in dict(parent.children):
            parent.children.append((key, self._build(value)))
            parent.children.sort(key=lambda edge: edge[0])
        else:
            raise ValueError("Invalid insertion key or index")

    def delete(self, path):
        if not path:
            raise ValueError("Cannot delete the root")
        node = self.at(path)
        parent = self.at(path[:-1])
        parent.children[:] = [(key, child) for key, child in parent.children if child is not node]
        if parent.kind == "array":
            self._reindex(parent)

    def modify_scalar(self, path, value):
        node = self.at(path)
        if node.kind != "scalar" or type(value) not in (type(None), str, bool, int, float):
            raise ValueError("Expected an existing scalar and a new scalar")
        encode(value)
        node.value = value

    def move(self, parent_path, source, target):
        """Move inside an array. Target is the final zero-based position.

        Returns the moved subtree IDs to invalidate in the dynamic schemes.
        """
        parent = self.at(parent_path)
        if parent.kind != "array" or any(
            type(index) is not int or not 0 <= index < len(parent.children)
            for index in (source, target)
        ):
            raise ValueError("Invalid array move")
        if source == target:
            return set()
        edge = parent.children.pop(source)
        parent.children.insert(target, edge)
        self._reindex(parent)
        return {node.uid for node in preorder(edge[1])}

    @staticmethod
    def _reindex(parent):
        parent.children[:] = [(index, child) for index, (_, child) in enumerate(parent.children)]


def preorder(node):
    yield node
    for _, child in node.children:
        yield from preorder(child)


def region_events(node):
    yield node.uid, 0
    for _, child in node.children:
        yield from region_events(child)
    yield node.uid, 1


def prefix(left, right):
    return len(left) < len(right) and right[:len(left)] == left


def between_ordpaths(left, right):
    """Allocate an odd-terminated sibling code with even caret components."""
    if left is None:
        return (1,) if right is None else (*right[:-1], right[-1] - 2)
    if right is None:
        return (*left[:-1], left[-1] + 2)

    shared = 0
    while left[shared] == right[shared]:
        shared += 1
    low, high = left[shared], right[shared]
    common = left[:shared]
    if low + 1 < high:
        middle = low + 1
        return (*common, middle) if middle % 2 else (*common, middle, 1)
    if low % 2 == 0:
        return (*left[:-1], left[-1] + 2)
    return (*right[:-1], right[-1] - 2)


def primes():
    known = []
    for candidate in itertools.count(2):
        if all(candidate % prime for prime in itertools.takewhile(
            lambda prime: prime * prime <= candidate, known
        )):
            known.append(candidate)
            yield candidate


class Scheme:
    def __init__(self, name):
        self.name = name

    def labels(self, tree, previous=None, invalidate=()):
        """Return {stable node ID: label}; previous must be the preceding snapshot."""
        old = {} if previous is None else previous
        invalid = set(invalidate)
        name = self.name
        if name in {"region", "dynamic-region", "qed"}:
            events = list(region_events(tree.root))
            if name == "region":
                ticks = list(range(1, len(events) + 1))
            elif name == "qed":
                ticks = qed_ticks(events, old, invalid)
            else:
                ticks = self._dynamic_ticks(events, old, invalid)
            return self._pair_ticks(events, ticks)

        labels = {}
        prime_stream = primes()

        def visit(node, label):
            labels[node.uid] = label
            if name in {"ordpath", "dde"}:
                sibling_codes = [(old[child.uid][len(label):] if name == "ordpath" else old[child.uid])
                                 if child.uid in old and child.uid not in invalid else None
                                 for _, child in node.children]
                right_codes = [None] * len(sibling_codes)
                right = None
                for index in range(len(sibling_codes) - 1, -1, -1):
                    right_codes[index] = right
                    if sibling_codes[index] is not None:
                        right = sibling_codes[index]
                left = None
            child_hashes = []
            for index, (key, child) in enumerate(node.children):
                if name == "ordpath":
                    code = sibling_codes[index]
                    if code is None:
                        code = between_ordpaths(left, right_codes[index])
                    left = code
                    child_label = label + code
                elif name == "dde":
                    code = sibling_codes[index]
                    if code is None:
                        code = dde_between(label, left, right_codes[index])
                    left = child_label = code
                elif name == "stable-path":
                    token = ("key", key) if node.kind == "object" else ("array",)
                    child_label = (*label, token)
                elif name == "pointer":
                    token = str(key).replace("~", "~0").replace("/", "~1")
                    child_label = label + "/" + token
                elif name == "prime":
                    child_label = label * next(prime_stream)
                else:
                    child_label = (*label, index + 1)
                digest = visit(child, child_label)
                if name == "hash":
                    child_hashes.append((key, digest.hex()))

            if name == "hash":
                payload = node.value if node.kind == "scalar" else child_hashes
                digest = hashlib.sha256(encode((node.kind, payload))).digest()
                labels[node.uid] = label, digest
                return digest
            return None

        root_labels = {"dewey": (1,), "hash": (1,), "ordpath": (1,),
                       "pointer": "", "prime": 1, "dde": (1,), "stable-path": ()}
        visit(tree.root, root_labels[name])
        return labels

    @staticmethod
    def _pair_ticks(events, ticks):
        starts = {}
        labels = {}
        for (uid, side), tick in zip(events, ticks):
            if side == 0:
                starts[uid] = tick
            else:
                labels[uid] = starts[uid], tick
        return labels

    @staticmethod
    def _dynamic_ticks(events, old, invalid):
        ticks = [None] * len(events)
        for index, (uid, side) in enumerate(events):
            if uid in old and uid not in invalid:
                ticks[index] = old[uid][side]
        anchors = [i for i, tick in enumerate(ticks) if tick is not None]
        for left, right in itertools.pairwise([-1, *anchors, len(ticks)]):
            if right == left + 1:
                continue
            if left == -1:
                bound = ticks[right] if right < len(ticks) else Fraction(len(ticks) + 1)
                for index in range(right):
                    ticks[index] = bound - (right - index)
            elif right == len(ticks):
                for index in range(left + 1, right):
                    ticks[index] = ticks[left] + (index - left)
            else:
                step = (ticks[right] - ticks[left]) / (right - left)
                for index in range(left + 1, right):
                    ticks[index] = ticks[left] + step * (index - left)
        return ticks

    def ancestor(self, left, right):
        if self.name == "dde":
            return dde_ancestor(left, right)
        if self.name == "stable-path":
            raise ValueError("Use StableNavigation with node IDs for instance ancestry")
        if self.name in {"region", "dynamic-region", "qed"}:
            return left[0] < right[0] and right[1] < left[1]
        if self.name == "pointer":
            return right.startswith(left + "/")
        if self.name == "prime":
            return left != right and right % left == 0
        if self.name == "hash":
            left, right = left[0], right[0]
        return prefix(left, right)

    @staticmethod
    def serialize(label):
        """Readable portable encoding, excluding the node ID."""
        def portable(value):
            if isinstance(value, Fraction):
                return [hex(value.numerator), hex(value.denominator)]
            if isinstance(value, bytes):
                return value.hex()
            if type(value) is int and value.bit_length() > 4096:
                return hex(value)
            if isinstance(value, tuple):
                return [portable(item) for item in value]
            return value

        # Hexadecimal big integers avoid Python's decimal digit conversion limit.
        return encode(hex(label) if type(label) is int else portable(label))

    @staticmethod
    def storage_bytes(label):
        return len(Scheme.serialize(label))


SCHEMES = tuple(Scheme(name) for name in (
    "region", "dewey", "ordpath", "dynamic-region", "prime", "pointer", "hash", "dde", "qed", "stable-path"
))
