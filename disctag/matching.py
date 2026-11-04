from __future__ import annotations

from copy import deepcopy

from .models import TrackMetadata


def align_tracks_by_duration(
    local_durations_ms: list[float | None],
    tracks: list[TrackMetadata],
    tolerance_ms: int = 3000,
) -> list[TrackMetadata | None] | None:
    local_count = len(local_durations_ms)
    online_count = len(tracks)
    if local_count <= online_count:
        return None
    if any(not duration or duration <= 0 for duration in local_durations_ms):
        return None
    if any(track.duration_ms <= 0 for track in tracks):
        return None

    infinity = float("inf")
    costs = [[infinity] * (online_count + 1) for _ in range(local_count + 1)]
    operations: list[list[str | None]] = [[None] * (online_count + 1) for _ in range(local_count + 1)]
    costs[0][0] = 0.0
    for local_index in range(1, local_count + 1):
        costs[local_index][0] = 0.0
        operations[local_index][0] = "missing"
        for online_index in range(1, min(local_index, online_count) + 1):
            best_cost = infinity
            best_operation = None
            if local_index > online_index and costs[local_index - 1][online_index] < infinity:
                best_cost = costs[local_index - 1][online_index]
                best_operation = "missing"
            difference = abs(float(local_durations_ms[local_index - 1]) - tracks[online_index - 1].duration_ms)
            if difference <= tolerance_ms and costs[local_index - 1][online_index - 1] < infinity:
                candidate = costs[local_index - 1][online_index - 1] + difference
                if candidate < best_cost:
                    best_cost = candidate
                    best_operation = "match"
            costs[local_index][online_index] = best_cost
            operations[local_index][online_index] = best_operation

    if operations[local_count][online_count] is None:
        return None
    aligned: list[TrackMetadata | None] = []
    local_index = local_count
    online_index = online_count
    while local_index:
        operation = operations[local_index][online_index]
        if operation == "match":
            aligned.append(deepcopy(tracks[online_index - 1]))
            online_index -= 1
        else:
            aligned.append(None)
        local_index -= 1
    aligned.reverse()
    return aligned
