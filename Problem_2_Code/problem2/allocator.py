"""连续地址空间的确定性分配器。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IntervalAllocator:
    capacity: int
    free_intervals: list[tuple[int, int]]

    @classmethod
    def empty(cls, capacity: int) -> "IntervalAllocator":
        return cls(capacity=capacity, free_intervals=[(0, capacity)])

    def clone(self) -> "IntervalAllocator":
        return IntervalAllocator(self.capacity, list(self.free_intervals))

    @property
    def total_free(self) -> int:
        return sum(end - start for start, end in self.free_intervals)

    @property
    def largest_hole(self) -> int:
        return max((end - start for start, end in self.free_intervals), default=0)

    def allocate(self, size: int, strategy: str) -> int | None:
        if size <= 0:
            raise ValueError("申请长度必须为正数")
        candidates = [
            (index, start, end)
            for index, (start, end) in enumerate(self.free_intervals)
            if end - start >= size
        ]
        if not candidates:
            return None
        if strategy == "first_fit":
            index, start, end = candidates[0]
        elif strategy == "best_fit":
            index, start, end = min(candidates, key=lambda item: (item[2] - item[1] - size, item[1]))
        else:
            raise ValueError(f"未知地址分配策略：{strategy}")

        new_intervals: list[tuple[int, int]] = []
        if start + size < end:
            new_intervals.append((start + size, end))
        self.free_intervals[index : index + 1] = new_intervals
        return start

    def reserve(self, offset: int, size: int) -> bool:
        """验证器使用：在指定地址申请区间。"""

        if offset < 0 or size <= 0 or offset + size > self.capacity:
            return False
        for index, (start, end) in enumerate(self.free_intervals):
            if start <= offset and offset + size <= end:
                replacement: list[tuple[int, int]] = []
                if start < offset:
                    replacement.append((start, offset))
                if offset + size < end:
                    replacement.append((offset + size, end))
                self.free_intervals[index : index + 1] = replacement
                return True
        return False

    def release(self, offset: int, size: int) -> None:
        if offset < 0 or size <= 0 or offset + size > self.capacity:
            raise ValueError(f"释放区间越界：[{offset}, {offset + size}) / {self.capacity}")
        self.free_intervals.append((offset, offset + size))
        self.free_intervals.sort()
        merged: list[tuple[int, int]] = []
        for start, end in self.free_intervals:
            if not merged or merged[-1][1] < start:
                merged.append((start, end))
            else:
                old_start, old_end = merged[-1]
                if start < old_end:
                    raise ValueError(
                        f"释放区间与已有空闲区间重叠：[{start},{end}) 与 [{old_start},{old_end})"
                    )
                merged[-1] = (old_start, max(old_end, end))
        self.free_intervals = merged
