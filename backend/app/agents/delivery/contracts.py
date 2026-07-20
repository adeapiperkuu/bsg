"""Stable public contracts for the Delivery Performance Agent.

Keep this module deliberately small. Phase 0 records compatibility boundaries;
scoring configuration and later-phase response shaping do not belong here.
"""

from typing import Literal

DeliveryTrafficLight = Literal["green", "yellow", "red"]
