"""DDE, QED interval endpoints and stable structural path labels."""

from fractions import Fraction


def dde_between(parent, left, right):
    if left is None and right is None:
        return (*parent, 1)
    if left is None:
        return (*right[:-1], right[-1] - 1)
    if right is None:
        return (*left[:-1], left[-1] + 1)
    return tuple(a + b for a, b in zip(left, right))


def dde_order(label):
    return tuple(Fraction(component, label[0]) for component in label)


def dde_ancestor(left, right):
    return len(left) < len(right) and all(
        a * right[0] == b * left[0] for a, b in zip(left, right)
    )


def qed_between(left, right):
    """Return the two interior codes of Li and Ling's allocation algorithm."""
    if left is None and right is None:
        return "2", "3"
    if right is not None and (left is None or len(left) < len(right)):
        stem = right[:-1] + "1"
    else:
        stem = left
    return stem + "2", stem + "3"


def qed_fill(count, left=None, right=None):
    """Recursively split an open interval into thirds."""
    if count == 0:
        return []
    first, second = qed_between(left, right)
    if count == 1:
        return [first]
    lower, remainder = divmod(count - 2, 3)
    middle = lower + (remainder > 0)
    upper = lower + (remainder > 1)
    return [*qed_fill(lower, left, first), first,
            *qed_fill(middle, first, second), second,
            *qed_fill(upper, second, right)]


def qed_ticks(events, old, invalid):
    ticks = [old[uid][side] if uid in old and uid not in invalid else None
             for uid, side in events]
    left_index = -1
    left = None
    for index, right in enumerate([*ticks, None]):
        if right is None and index != len(ticks):
            continue
        ticks[left_index + 1:index] = qed_fill(index - left_index - 1, left, right)
        left_index, left = index, right
    return ticks


class StableNavigation:
    """Parent links and preorder ranks for one tree snapshot, keyed by stable UID."""

    def __init__(self, tree):
        self.parents = {tree.root.uid: None}
        self.order = {}

        def visit(node):
            self.order[node.uid] = len(self.order)
            for _, child in node.children:
                self.parents[child.uid] = node.uid
                visit(child)

        visit(tree.root)

    def ancestor(self, left_uid, right_uid):
        parent = self.parents[right_uid]
        while parent is not None:
            if parent == left_uid:
                return True
            parent = self.parents[parent]
        return False

    def before(self, left_uid, right_uid):
        return self.order[left_uid] < self.order[right_uid]
