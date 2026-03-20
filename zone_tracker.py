"""
zone_tracker.py – Conveyor zone box-count tracker.

Loads sensor tag names from sensor_tags.json and tracks per-zone current
counts and daily totals using rising-edge detection on entry/exit Boolean
sensors.

Zone order (index 0-8):
  L1Z1, L1Z2, L1Z3  (Line 1, Zones 1-3)
  L2Z1, L2Z2, L2Z3  (Line 2, Zones 1-3)
  L3Z1, L3Z2, L3Z3  (Line 3, Zones 1-3)

Conveyor paths:
  Short: L1Z1 → L1Z2 → L1Z3 → L2Z1 → L2Z2 → L2Z3 → Exit
  Long:  L1Z1 → L1Z2 → L1Z3 → L2Z1 → L2Z2 → L2Z3 → L3Z1 → L3Z2 → L3Z3 → Exit

Each zone has two sensors:
  entry – photoeye that fires (True) when a box enters the zone
  exit  – photoeye that fires (True) when a box leaves the zone

A rising edge (False → True) on the entry sensor increments both the
current count and the daily total for that zone.
A rising edge on the exit sensor decrements the current count only
(minimum 0).
"""

import json
import os
from threading import Lock

ZONES = ["L1Z1", "L1Z2", "L1Z3", "L2Z1", "L2Z2", "L2Z3", "L3Z1", "L3Z2", "L3Z3"]
SENSOR_TAGS_FILE = "sensor_tags.json"


class ZoneTracker:
    """Thread-safe tracker for conveyor zone box counts."""

    def __init__(self, sensor_tags_file=SENSOR_TAGS_FILE):
        self._lock = Lock()
        self.sensor_tags = self._load_sensor_tags(sensor_tags_file)

        # {zone: int}
        self.current_count = {z: 0 for z in ZONES}
        self.daily_total = {z: 0 for z in ZONES}

        # Previous boolean state per tag for rising-edge detection
        self._prev_state = {}

        # Build reverse lookup: tag_name -> (zone, "entry"|"exit")
        self._tag_map = {}
        for zone, cfg in self.sensor_tags.items():
            entry = cfg.get("entry", "")
            exit_ = cfg.get("exit", "")
            if entry:
                self._tag_map[entry] = (zone, "entry")
            if exit_:
                self._tag_map[exit_] = (zone, "exit")

    # ── internal helpers ───────────────────────────────────────────────

    def _load_sensor_tags(self, path):
        if os.path.exists(path):
            with open(path, "r") as fh:
                data = json.load(fh)
            # Strip the comment key if present
            data.pop("comment", None)
            return data
        return {z: {"entry": "", "exit": ""} for z in ZONES}

    # ── public API ─────────────────────────────────────────────────────

    def get_all_tags(self):
        """Return a flat list of all configured sensor tag names for PLC polling."""
        return list(self._tag_map.keys())

    def init_prev_state(self, tag_values):
        """
        Initialise previous-state dict from a {tag: value} snapshot so that
        no false rising edges fire on the first poll cycle.
        """
        with self._lock:
            for tag, value in tag_values.items():
                self._prev_state[tag] = bool(value)

    def process_reading(self, tag_name, value):
        """
        Call once per poll cycle for each sensor tag value (bool).

        Returns a list of (zone, event_type, new_count) tuples for any
        rising-edge events detected.  Returns an empty list when no edge
        was detected or the tag is not a configured sensor.
        """
        value = bool(value)
        prev = self._prev_state.get(tag_name, False)
        self._prev_state[tag_name] = value

        if prev or not value:
            # Not a rising edge
            return []

        mapping = self._tag_map.get(tag_name)
        if mapping is None:
            return []

        zone, sensor_type = mapping
        with self._lock:
            if sensor_type == "entry":
                self.current_count[zone] = max(0, self.current_count[zone] + 1)
                self.daily_total[zone] += 1
                new_count = self.current_count[zone]
            else:  # exit
                self.current_count[zone] = max(0, self.current_count[zone] - 1)
                new_count = self.current_count[zone]

        return [(zone, sensor_type, new_count)]

    def get_snapshot(self):
        """
        Return a dict snapshot suitable for MQTT publishing::

            {
              "L1Z1": {"current": 3, "day_total": 45},
              ...
            }
        """
        with self._lock:
            return {
                z: {
                    "current": self.current_count[z],
                    "day_total": self.daily_total[z],
                }
                for z in ZONES
            }

    def reset_daily_totals(self):
        """Reset all daily totals to zero (call at midnight)."""
        with self._lock:
            for z in ZONES:
                self.daily_total[z] = 0

    def restore_daily_totals(self, totals_dict):
        """Restore daily totals from a persisted source (e.g. DBLogger)."""
        with self._lock:
            for z in ZONES:
                self.daily_total[z] = totals_dict.get(z, 0)
