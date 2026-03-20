#pragma once

/**
 * @brief Initialise the 3×3 conveyor-zone grid UI.
 *
 * Call once, inside an lvgl_port_lock() / lvgl_port_unlock() section.
 *
 * Creates nine cells in a 3×3 grid on the 800×480 display:
 *   Row 0 (top)    – Line 1: L1Z1  L1Z2  L1Z3
 *   Row 1 (middle) – Line 2: L2Z1  L2Z2  L2Z3
 *   Row 2 (bottom) – Line 3: L3Z1  L3Z2  L3Z3
 *
 * Each cell contains:
 *   - A zone label (e.g. "L1Z1")
 *   - A horizontal fill-bar reflecting the current box count
 *   - A "NOW: N"  label – boxes currently in the zone
 *   - A "DAY: N"  label – total boxes processed today
 *
 * Update individual cells at run-time with app_ui_set_zone().
 */
void app_ui_init(void);

/**
 * @brief Update a single zone cell with new counts.
 *
 * Thread-safe: acquires lvgl_port_lock() internally.
 *
 * @param zone_idx  Cell index 0–8 (row-major: 0=L1Z1 … 8=L3Z3)
 * @param current   Current number of boxes in the zone
 * @param day_total Total boxes processed in this zone today
 */
void app_ui_set_zone(int zone_idx, int current, int day_total);
