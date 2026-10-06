"""Mutable state for one alignment run."""


class Side:
    SOURCE = 'source'
    TARGET = 'target'


class PointPair:
    """One source↔target link. Each end fills in independently."""

    __slots__ = (
        'id', 'label', 'color',
        'src_obj', 'src_vert', 'src_world',
        'tgt_obj', 'tgt_vert', 'tgt_world',
    )

    def __init__(self, pair_id, label, color):
        self.id = pair_id
        self.label = label
        self.color = tuple(color)

        self.src_obj = self.src_vert = self.src_world = None
        self.tgt_obj = self.tgt_vert = self.tgt_world = None

    def get(self, side):
        if side == Side.SOURCE:
            return self.src_obj, self.src_vert, self.src_world
        return self.tgt_obj, self.tgt_vert, self.tgt_world

    def put(self, side, obj, vert, world):
        if side == Side.SOURCE:
            self.src_obj, self.src_vert, self.src_world = obj, vert, world
        else:
            self.tgt_obj, self.tgt_vert, self.tgt_world = obj, vert, world

    def clear(self, side):
        if side == Side.SOURCE:
            self.src_obj = self.src_vert = self.src_world = None
        else:
            self.tgt_obj = self.tgt_vert = self.tgt_world = None

    @property
    def ready(self):
        return self.src_world is not None and self.tgt_world is not None

    @property
    def partial(self):
        return (self.src_world is None) != (self.tgt_world is None)

    @property
    def empty(self):
        return self.src_world is None and self.tgt_world is None


class Session:
    SLOTS = 3

    def __init__(self, source_obj, target_obj, settings):
        self.source_obj = source_obj
        self.target_obj = target_obj
        self.settings = settings

        self.pairs = [
            PointPair(i, f"连线 {i+1}", c) for i, c in enumerate((
                settings.line1_color,
                settings.line2_color,
                settings.line3_color,
            ))
        ]
        self._claimed = {}
        self.cursor_pair_id = 0

    # ----- vertex ownership table -----

    def owner_of(self, obj, vert):
        return self._claimed.get((obj.name, vert.index))

    def claim(self, obj, vert, pair_id):
        self._claimed[(obj.name, vert.index)] = pair_id

    def drop(self, obj, vert):
        self._claimed.pop((obj.name, vert.index), None)

    # ----- object helpers -----

    def side_of(self, obj):
        if obj.name == self.source_obj.name:
            return Side.SOURCE
        if obj.name == self.target_obj.name:
            return Side.TARGET
        return None

    def pair_by_id(self, pid):
        if 0 <= pid < len(self.pairs):
            return self.pairs[pid]
        return None

    def next_open(self, side):
        for p in self.pairs:
            if p.get(side)[2] is None:
                return p
        return None

    @property
    def finished(self):
        return all(p.ready for p in self.pairs)