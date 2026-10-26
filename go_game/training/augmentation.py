"""D4 augmentation of training tensors, policies and legal masks.

All planes (including history), policy and mask share the same geometry. Pass
is unchanged; augmentation never mutates canonical source records.
"""


def point(row, col, size, rotation=0, reflect=False):
    if not 0 <= rotation < 4:
        raise ValueError("rotation must be 0..3")
    for _ in range(rotation):
        row, col = col, size - 1 - row
    if reflect:
        col = size - 1 - col
    return row, col


def transform_flat(values, size, rotation=0, reflect=False, has_pass=True):
    expected = size * size + int(has_pass)
    if len(values) != expected:
        raise ValueError("Spatial dimensions/action encoding mismatch")
    output = [None] * expected
    for r in range(size):
        for c in range(size):
            nr, nc = point(r, c, size, rotation, reflect)
            output[nr * size + nc] = values[r * size + c]
    if has_pass:
        output[-1] = values[-1]
    return output


def transform_sample(sample, size, rotation=0, reflect=False):
    output = dict(sample)
    planes = []
    for plane in sample["planes"]:
        if len(plane) != size or any(len(row) != size for row in plane):
            raise ValueError("Invalid observation shape")
        flat = [v for row in plane for v in row]
        remapped = transform_flat(flat, size, rotation, reflect, has_pass=False)
        planes.append([remapped[r * size:(r + 1) * size] for r in range(size)])
    output["planes"] = planes
    for name in ("mask", "visits", "pi"):
        output[name] = transform_flat(sample[name], size, rotation, reflect)
    if sample["action"] == size * size:
        output["action"] = size * size
    else:
        row, col = divmod(sample["action"], size)
        nr, nc = point(row, col, size, rotation, reflect)
        output["action"] = nr * size + nc
    # State fingerprint remains the original record identity; this
    # transformed view is only valid as a network TRAINING input.
    return output
