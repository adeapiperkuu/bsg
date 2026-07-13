"""Shared Governance cache and first-paint constants.

GOVERNANCE_FIRST_PAINT_LIMIT must match the frontend dashboard table page size
(TABLE_PAGE_SIZE / GOVERNANCE_DEFAULT_TABLE_PARAMS.limit = 6). Changing the
frontend page size requires reviewing backend cache eligibility and tests.
Do not share a runtime constant with TypeScript — keep both sides named and tested.
"""

from __future__ import annotations

# Production dashboard first-page size (frontend TABLE_PAGE_SIZE).
GOVERNANCE_FIRST_PAINT_LIMIT = 6
GOVERNANCE_FIRST_PAINT_OFFSET = 0

# Legacy dependencies cache shape retained for intentional limit=50 callers.
LEGACY_DEPENDENCIES_CACHE_LIMIT = 50

DEPENDENCIES_CACHEABLE_LIMITS = frozenset(
    {
        GOVERNANCE_FIRST_PAINT_LIMIT,
        LEGACY_DEPENDENCIES_CACHE_LIMIT,
    }
)

# Register historically cached 25/50; add first-paint 6 for the Register tab.
REGISTER_CACHEABLE_LIMITS = frozenset(
    {
        GOVERNANCE_FIRST_PAINT_LIMIT,
        25,
        50,
    }
)

CACHE_SHAPE_FIRST_PAINT_UNFILTERED = "first_paint_unfiltered"
CACHE_SHAPE_LEGACY_FIRST_PAGE = "legacy_first_page"
CACHE_SHAPE_UNCACHED_FILTERED = "uncached_filtered"
CACHE_SHAPE_UNCACHED_OFFSET = "uncached_offset"
CACHE_SHAPE_UNCACHED_LIMIT = "uncached_limit"
