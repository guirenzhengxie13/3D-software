"""The owned, normalized frame contract used by every input adapter."""

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True, slots=True)
class PointCloudFrame:
    """An owned snapshot, with xyz in metres and RGB in the range [0, 1].

    xyz has shape (N, 3). colors is either None or has the same shape.
    coordinate_frame names the source coordinate system; callers must not
    assume two different sources share axes, handedness, or an origin.
    timestamp is seconds in timestamp_domain, never an implied UTC time.

    Arrays are copied and made read-only. A future native SDK callback may
    recycle its input buffers as soon as it returns, so it must construct
    this snapshot before returning. Frame IDs are source-local integers.
    """

    xyz: NDArray[np.float64]
    colors: NDArray[np.float32] | None = None
    frame_id: int = 0
    timestamp: float = 0.0
    timestamp_domain: str = "host_monotonic"
    coordinate_frame: str = "source_local"
    unit: str = "m"

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, int) or isinstance(self.frame_id, bool):
            raise ValueError("frame_id must be an integer")
        if self.frame_id < 0:
            raise ValueError("frame_id must be non-negative")
        if not math.isfinite(self.timestamp) or self.timestamp < 0:
            raise ValueError("timestamp must be finite, non-negative seconds")
        if self.unit != "m":
            raise ValueError("PointCloudFrame xyz must be normalized to metres (unit='m')")
        if not self.coordinate_frame.strip() or not self.timestamp_domain.strip():
            raise ValueError("coordinate_frame and timestamp_domain must be specified")

        xyz = self._owned_array(self.xyz, np.float64, "xyz")
        object.__setattr__(self, "xyz", xyz)
        if self.colors is not None:
            colors = self._owned_array(self.colors, np.float32, "colors")
            if colors.shape != xyz.shape:
                raise ValueError("colors must have the same (N, 3) shape as xyz")
            if np.any((colors < 0.0) | (colors > 1.0)):
                raise ValueError("colors must contain normalized RGB values in [0, 1]")
            object.__setattr__(self, "colors", colors)

    @staticmethod
    def _owned_array(value: ArrayLike, dtype: type, name: str) -> NDArray:
        array = np.array(value, dtype=dtype, order="C", copy=True)
        if array.ndim != 2 or array.shape[1] != 3:
            raise ValueError(f"{name} must have shape (N, 3)")
        if not np.isfinite(array).all():
            raise ValueError(f"{name} contains NaN or infinity; filter invalid SDK points first")
        array.setflags(write=False)
        return array
