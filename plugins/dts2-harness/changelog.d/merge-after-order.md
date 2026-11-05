### Fixed
- Merge order now honors `merge_after`: `valid_order`, `merge_sequence` and `unmerged_needs` use depends_on plus the merge_after edges `merge-plan` already orders by, so a saved order that violates merge_after is rejected and `merge-go` is not granted while a merge_after provider is unmerged.
