"""Small deterministic GS indexed-texture sampling and inverse-quantization tools.

The TRICMN atlases are PSMT4 textures.  With TEX1.MMAG set, the GS resolves
the four neighbouring palette indexes to RGBA and then bilinearly mixes those
four colours.  These helpers model that operation at a fixed integer display
scale and solve the inverse problem under a locked palette/index contract.

This is deliberately not a generic image filter: callers decide which palette
indexes are legal at every native texel.  Transparency, reflected rim, side
wall and raised face therefore remain distinct authored layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math


class GSIndexedTextureError(ValueError):
    """Raised when the indexed-texture simulation contract is malformed."""


@dataclass(frozen=True)
class GSInverseReport:
    scale: int
    passes_requested: int
    passes_completed: int
    changed_texels: int
    initial_weighted_mse: float
    final_weighted_mse: float
    abrupt_pairs_before: int
    abrupt_pairs_after: int
    protected_abrupt_pairs_before: int
    protected_abrupt_pairs_after: int


def _validate_palette(palette: Sequence[Sequence[float]]) -> None:
    if len(palette) != 16 or any(len(color) != 4 for color in palette):
        raise GSIndexedTextureError("PSMT4 runtime palette must contain 16 RGBA colours")


def _sample_geometry(
    width: int,
    height: int,
    *,
    scale: int,
    phase_x: float,
    phase_y: float,
) -> tuple[
    int,
    int,
    list[tuple[tuple[int, float], ...]],
    list[list[tuple[int, float]]],
]:
    if width <= 0 or height <= 0 or not 2 <= scale <= 16:
        raise GSIndexedTextureError("invalid GS sampling geometry")
    if not -0.5 <= phase_x <= 0.5 or not -0.5 <= phase_y <= 0.5:
        raise GSIndexedTextureError("GS sampling phase must stay within one texel")

    output_width = width * scale
    output_height = height * scale
    samples: list[tuple[tuple[int, float], ...]] = []
    influences: list[list[tuple[int, float]]] = [
        [] for _ in range(width * height)
    ]
    for output_y in range(output_height):
        source_y = (output_y + 0.5) / scale - 0.5 + phase_y
        top = math.floor(source_y)
        fraction_y = source_y - top
        for output_x in range(output_width):
            source_x = (output_x + 0.5) / scale - 0.5 + phase_x
            left = math.floor(source_x)
            fraction_x = source_x - left
            taps = (
                (left, top, (1.0 - fraction_x) * (1.0 - fraction_y)),
                (left + 1, top, fraction_x * (1.0 - fraction_y)),
                (left, top + 1, (1.0 - fraction_x) * fraction_y),
                (left + 1, top + 1, fraction_x * fraction_y),
            )
            compact: list[tuple[int, float]] = []
            sample_index = len(samples)
            for sample_x, sample_y, weight in taps:
                if weight <= 0:
                    continue
                local = (
                    sample_y * width + sample_x
                    if 0 <= sample_x < width and 0 <= sample_y < height
                    else -1
                )
                compact.append((local, weight))
                if local >= 0:
                    influences[local].append((sample_index, weight))
            samples.append(tuple(compact))
    return output_width, output_height, samples, influences


def simulate_tex1_bilinear_rgba(
    indexes: bytes | bytearray | Sequence[int],
    *,
    width: int,
    height: int,
    palette: Sequence[Sequence[float]],
    scale: int = 4,
    phase_x: float = 0.0,
    phase_y: float = 0.0,
    border_index: int = 0,
) -> tuple[float, ...]:
    """Resolve four palette indexes and bilinearly mix their RGBA colours."""

    _validate_palette(palette)
    if len(indexes) != width * height or not 0 <= border_index <= 15:
        raise GSIndexedTextureError("indexed source geometry drift")
    _output_width, _output_height, samples, _influences = _sample_geometry(
        width,
        height,
        scale=scale,
        phase_x=phase_x,
        phase_y=phase_y,
    )
    output = [0.0] * (len(samples) * 4)
    for sample_index, taps in enumerate(samples):
        base = sample_index * 4
        for local, weight in taps:
            palette_index = indexes[local] if local >= 0 else border_index
            color = palette[palette_index]
            for channel in range(4):
                output[base + channel] += color[channel] * weight
    return tuple(output)


def simulate_tex1_bilinear_continuous_rgba(
    native_rgba: Sequence[float],
    *,
    width: int,
    height: int,
    scale: int = 4,
    phase_x: float = 0.0,
    phase_y: float = 0.0,
    border_rgba: Sequence[float] = (0.0, 0.0, 0.0, 0.0),
) -> tuple[float, ...]:
    """Apply the same TEX1 sampling kernel to a continuous native target."""

    if len(native_rgba) != width * height * 4 or len(border_rgba) != 4:
        raise GSIndexedTextureError("continuous target geometry drift")
    _output_width, _output_height, samples, _influences = _sample_geometry(
        width,
        height,
        scale=scale,
        phase_x=phase_x,
        phase_y=phase_y,
    )
    output = [0.0] * (len(samples) * 4)
    for sample_index, taps in enumerate(samples):
        base = sample_index * 4
        for local, weight in taps:
            if local >= 0:
                source = local * 4
                color = native_rgba[source : source + 4]
            else:
                color = border_rgba
            for channel in range(4):
                output[base + channel] += color[channel] * weight
    return tuple(output)


def _palette_luminance(color: Sequence[float]) -> float:
    return (54.0 * color[0] + 183.0 * color[1] + 19.0 * color[2]) / 256.0


def abrupt_luminance_pair_count(
    indexes: bytes | bytearray | Sequence[int],
    *,
    width: int,
    height: int,
    palette: Sequence[Sequence[float]],
    threshold: float = 64.0,
) -> int:
    """Count right/down non-transparent pairs with a large palette jump."""

    _validate_palette(palette)
    if len(indexes) != width * height:
        raise GSIndexedTextureError("abrupt-pair source geometry drift")
    luma = tuple(_palette_luminance(color) for color in palette)
    count = 0
    for y in range(height):
        for x in range(width):
            local = y * width + x
            first = indexes[local]
            if first == 0:
                continue
            for other in (
                local + 1 if x + 1 < width else -1,
                local + width if y + 1 < height else -1,
            ):
                if other < 0 or indexes[other] == 0:
                    continue
                if abs(luma[first] - luma[indexes[other]]) >= threshold:
                    count += 1
    return count


def inverse_quantize_tex1_bilinear(
    target_rgba: Sequence[float],
    initial_indexes: bytes | bytearray | Sequence[int],
    *,
    width: int,
    height: int,
    palette: Sequence[Sequence[float]],
    allowed_indexes: Mapping[int, Sequence[int]],
    scale: int = 4,
    passes: int = 2,
    phase_x: float = 0.0,
    phase_y: float = 0.0,
    channel_weights: Sequence[float] = (1.0, 1.0, 1.0, 0.35),
    adjacency_threshold: float = 64.0,
    adjacency_weight: float = 0.0,
    protected_edges: Sequence[tuple[int, int]] = (),
    protected_adjacency_threshold: float | None = None,
) -> tuple[bytes, GSInverseReport]:
    """Coordinate-descent inverse quantization under per-texel index locks.

    Only output samples influenced by the candidate texel are rescored.  The
    optional adjacency term discourages isolated high-contrast source steps;
    it does not blur the target or change the silhouette.
    """

    _validate_palette(palette)
    if len(initial_indexes) != width * height:
        raise GSIndexedTextureError("inverse source geometry drift")
    if not 1 <= passes <= 8 or len(channel_weights) != 4:
        raise GSIndexedTextureError("inverse optimization parameters are invalid")
    if adjacency_threshold < 0 or adjacency_weight < 0:
        raise GSIndexedTextureError("inverse adjacency parameters are invalid")
    if (
        protected_adjacency_threshold is not None
        and protected_adjacency_threshold < 0
    ):
        raise GSIndexedTextureError(
            "inverse protected-adjacency threshold is invalid"
        )

    _output_width, _output_height, samples, influences = _sample_geometry(
        width,
        height,
        scale=scale,
        phase_x=phase_x,
        phase_y=phase_y,
    )
    if len(target_rgba) != len(samples) * 4:
        raise GSIndexedTextureError("inverse target geometry drift")
    current_indexes = bytearray(initial_indexes)
    for local, choices in allowed_indexes.items():
        if not 0 <= local < width * height:
            raise GSIndexedTextureError("inverse allowed-index coordinate drift")
        normalized = tuple(dict.fromkeys(choices))
        if not normalized or any(not 0 <= value <= 15 for value in normalized):
            raise GSIndexedTextureError("inverse allowed-index palette drift")
        if current_indexes[local] not in normalized:
            raise GSIndexedTextureError("inverse initial index violates its layer lock")

    current = list(
        simulate_tex1_bilinear_rgba(
            current_indexes,
            width=width,
            height=height,
            palette=palette,
            scale=scale,
            phase_x=phase_x,
            phase_y=phase_y,
        )
    )

    def sample_loss(sample_index: int, rgba: Sequence[float]) -> float:
        base = sample_index * 4
        return sum(
            channel_weights[channel]
            * (rgba[base + channel] - target_rgba[base + channel]) ** 2
            for channel in range(4)
        )

    def full_loss() -> float:
        return sum(sample_loss(sample, current) for sample in range(len(samples)))

    palette_luma = tuple(_palette_luminance(color) for color in palette)
    protected_threshold = (
        adjacency_threshold
        if protected_adjacency_threshold is None
        else protected_adjacency_threshold
    )
    normalized_protected_edges = set()
    protected_neighbours: list[list[int]] = [
        [] for _ in range(width * height)
    ]
    for raw_first, raw_second in protected_edges:
        if (
            not 0 <= raw_first < width * height
            or not 0 <= raw_second < width * height
            or raw_first == raw_second
        ):
            raise GSIndexedTextureError("inverse protected edge is invalid")
        first, second = sorted((raw_first, raw_second))
        first_x, first_y = first % width, first // width
        second_x, second_y = second % width, second // width
        if abs(first_x - second_x) + abs(first_y - second_y) != 1:
            raise GSIndexedTextureError(
                "inverse protected edge must join direct neighbours"
            )
        normalized_protected_edges.add((first, second))
    for first, second in sorted(normalized_protected_edges):
        protected_neighbours[first].append(second)
        protected_neighbours[second].append(first)

    def is_abrupt(first: int, second: int) -> bool:
        return (
            first != 0
            and second != 0
            and abs(palette_luma[first] - palette_luma[second])
            >= protected_threshold
        )

    def protected_abrupt_count() -> int:
        return sum(
            is_abrupt(current_indexes[first], current_indexes[second])
            for first, second in normalized_protected_edges
        )

    def protected_local_count(local: int, candidate: int) -> int:
        return sum(
            is_abrupt(candidate, current_indexes[other])
            for other in protected_neighbours[local]
        )

    def adjacency_penalty(local: int, candidate: int) -> float:
        if adjacency_weight == 0 or candidate == 0:
            return 0.0
        x = local % width
        y = local // width
        penalty = 0.0
        for other in (
            local - 1 if x else -1,
            local + 1 if x + 1 < width else -1,
            local - width if y else -1,
            local + width if y + 1 < height else -1,
        ):
            if other < 0:
                continue
            neighbour = current_indexes[other]
            if neighbour == 0:
                continue
            excess = abs(palette_luma[candidate] - palette_luma[neighbour]) - adjacency_threshold
            if excess > 0:
                penalty += adjacency_weight * excess * excess
        return penalty

    initial_loss = full_loss()
    abrupt_before = abrupt_luminance_pair_count(
        current_indexes,
        width=width,
        height=height,
        palette=palette,
        threshold=adjacency_threshold,
    )
    protected_abrupt_before = protected_abrupt_count()
    changed_texels: set[int] = set()
    completed = 0
    # Stable order keeps the build deterministic.  Constrained texels with the
    # smallest choice set settle first, then the wider side/face ramps follow.
    ordered = sorted(allowed_indexes, key=lambda local: (len(allowed_indexes[local]), local))
    for _pass in range(passes):
        pass_changes = 0
        for local in ordered:
            choices = tuple(dict.fromkeys(allowed_indexes[local]))
            if len(choices) == 1:
                continue
            old_index = current_indexes[local]
            old_color = palette[old_index]
            affected = influences[local]
            old_sample_loss = sum(sample_loss(sample, current) for sample, _weight in affected)
            old_adjacency = adjacency_penalty(local, old_index)
            old_protected = protected_local_count(local, old_index)
            best_index = old_index
            best_delta = 0.0
            for candidate in choices:
                if candidate == old_index:
                    continue
                # The user-visible outer boundary is a hard acceptance layer:
                # a coordinate update may remove an abrupt protected edge but
                # may never trade an interior improvement for an extra edge
                # notch.  Because every changed pair touches this local texel,
                # this makes the protected count monotonically non-increasing.
                if protected_local_count(local, candidate) > old_protected:
                    continue
                candidate_color = palette[candidate]
                delta_loss = -old_sample_loss - old_adjacency
                for sample, weight in affected:
                    base = sample * 4
                    candidate_rgba = list(current[base : base + 4])
                    for channel in range(4):
                        candidate_rgba[channel] += (
                            candidate_color[channel] - old_color[channel]
                        ) * weight
                    target_base = sample * 4
                    delta_loss += sum(
                        channel_weights[channel]
                        * (candidate_rgba[channel] - target_rgba[target_base + channel]) ** 2
                        for channel in range(4)
                    )
                delta_loss += adjacency_penalty(local, candidate)
                if delta_loss < best_delta - 1e-9:
                    best_delta = delta_loss
                    best_index = candidate
            if best_index == old_index:
                continue
            new_color = palette[best_index]
            for sample, weight in affected:
                base = sample * 4
                for channel in range(4):
                    current[base + channel] += (
                        new_color[channel] - old_color[channel]
                    ) * weight
            current_indexes[local] = best_index
            changed_texels.add(local)
            pass_changes += 1
        completed += 1
        if pass_changes == 0:
            break

    final_loss = full_loss()
    divisor = max(1.0, len(samples) * sum(channel_weights))
    report = GSInverseReport(
        scale=scale,
        passes_requested=passes,
        passes_completed=completed,
        changed_texels=len(changed_texels),
        initial_weighted_mse=initial_loss / divisor,
        final_weighted_mse=final_loss / divisor,
        abrupt_pairs_before=abrupt_before,
        abrupt_pairs_after=abrupt_luminance_pair_count(
            current_indexes,
            width=width,
            height=height,
            palette=palette,
            threshold=adjacency_threshold,
        ),
        protected_abrupt_pairs_before=protected_abrupt_before,
        protected_abrupt_pairs_after=protected_abrupt_count(),
    )
    return bytes(current_indexes), report


__all__ = [
    "GSIndexedTextureError",
    "GSInverseReport",
    "abrupt_luminance_pair_count",
    "inverse_quantize_tex1_bilinear",
    "simulate_tex1_bilinear_continuous_rgba",
    "simulate_tex1_bilinear_rgba",
]
