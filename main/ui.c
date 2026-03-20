/*
 * ui.c – 3×3 conveyor-zone display
 *
 * Nine cells are arranged in a 3×3 grid (rows = Lines 1-3, cols = Zones 1-3).
 * Each cell shows:
 *   • A zone label at the top  (e.g. "L1Z1")
 *   • A horizontal fill-bar   (lv_bar) reflecting the current box count
 *   • A "NOW: N"  label – current number of boxes in the zone
 *   • A "DAY: N"  label – total boxes that passed through today
 *
 * Row layout (top → bottom):
 *   Row 0 – Line 1:  L1Z1  L1Z2  L1Z3
 *   Row 1 – Line 2:  L2Z1  L2Z2  L2Z3
 *   Row 2 – Line 3:  L3Z1  L3Z2  L3Z3
 *
 * A left strip carries row labels: L1 / L2 / L3.
 *
 * Public API
 * ----------
 *   app_ui_init()                           – call once inside lvgl_port_lock
 *   app_ui_set_zone(idx, current, day_total) – update a single cell (thread-safe
 *                                             via lvgl_port_lock / unlock)
 *
 * Colour mapping for the fill bar (current count, max = VALUE_MAX):
 *    0 – 20 %  : solid green
 *   21 – 50 %  : green → yellow
 *   51 – 75 %  : yellow → red
 *   76 – 100 % : solid red
 */

#include "ui.h"
#include "lvgl.h"
#include "lvgl_port.h"

/* ── constants ──────────────────────────────────────────────────────── */
#define BAR_COUNT   9
#define GRID_COLS   3
#define GRID_ROWS   3
#define VALUE_MAX   20   /* max boxes per zone for full-scale bar */

#define LEFT_STRIP_W  60
#define BAR_H         44   /* fill-bar height in pixels */

/* ── zone names and row labels ──────────────────────────────────────── */
static const char *s_zone_names[BAR_COUNT] = {
    "L1Z1", "L1Z2", "L1Z3",   /* row 0 – Line 1 */
    "L2Z1", "L2Z2", "L2Z3",   /* row 1 – Line 2 */
    "L3Z1", "L3Z2", "L3Z3",   /* row 2 – Line 3 */
};

static const char *s_line_labels[GRID_ROWS] = {
    "L1",   /* row 0 */
    "L2",   /* row 1 */
    "L3",   /* row 2 */
};

/* ── per-cell state ─────────────────────────────────────────────────── */
typedef struct {
    lv_obj_t *bar;          /* horizontal fill bar                  */
    lv_obj_t *lbl_current;  /* "NOW: N"  label                      */
    lv_obj_t *lbl_day;      /* "DAY: N"  label                      */
    int32_t   current;
    int32_t   day_total;
} bar_cell_t;

static bar_cell_t  s_cells[BAR_COUNT];
static lv_color_t  s_row_bg_colors[GRID_ROWS];
static lv_obj_t   *s_bg_bands[GRID_ROWS];

/* ── colour helper ──────────────────────────────────────────────────── */
static lv_color_t count_to_color(int32_t v)
{
    /* Map 0..VALUE_MAX to green→yellow→red */
    uint8_t r = 0, g = 0;
    int pct = (int)((int64_t)v * 100 / VALUE_MAX);

    if (pct <= 20) {
        r = 0;   g = 200;
    } else if (pct <= 50) {
        int t = pct - 21;
        r = (uint8_t)(t * 255 / 29); g = 200;
    } else if (pct <= 75) {
        int t = pct - 51;
        r = 255; g = (uint8_t)(200 * (24 - t) / 24);
    } else {
        r = 220; g = 0;
    }
    return lv_color_make(r, g, 0);
}

/* ── public API ──────────────────────────────────────────────────────── */

void app_ui_set_zone(int zone_idx, int current, int day_total)
{
    if (zone_idx < 0 || zone_idx >= BAR_COUNT) return;

    if (!lvgl_port_lock(-1)) return;

    s_cells[zone_idx].current   = current;
    s_cells[zone_idx].day_total = day_total;

    int32_t bar_val = current > VALUE_MAX ? VALUE_MAX : current;
    if (bar_val < 0) bar_val = 0;
    lv_bar_set_value(s_cells[zone_idx].bar, bar_val, LV_ANIM_OFF);
    lv_obj_set_style_bg_color(s_cells[zone_idx].bar,
                              count_to_color(bar_val),
                              LV_PART_INDICATOR);

    char buf[32];
    snprintf(buf, sizeof(buf), "NOW: %d", current);
    lv_label_set_text(s_cells[zone_idx].lbl_current, buf);

    snprintf(buf, sizeof(buf), "DAY: %d", day_total);
    lv_label_set_text(s_cells[zone_idx].lbl_day, buf);

    lvgl_port_unlock();
}

void app_ui_init(void)
{
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_set_style_border_width(scr, 0, 0);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(scr, lv_color_make(20, 45, 100), 0);

    /* Row background colours */
    s_row_bg_colors[0] = lv_color_make(20,  45, 100);   /* L1 – dark navy   */
    s_row_bg_colors[1] = lv_color_make(50, 120, 190);   /* L2 – steel blue  */
    s_row_bg_colors[2] = lv_color_make(20,  45, 100);   /* L3 – dark navy   */

    lv_color_t row_border_colors[GRID_ROWS];
    row_border_colors[0] = lv_color_make(50,  75, 135);
    row_border_colors[1] = lv_color_make(80, 155, 215);
    row_border_colors[2] = lv_color_make(50,  75, 135);

    /* ── Full-width background bands ─────────────────────────────── */
    lv_coord_t band_h = LVGL_PORT_V_RES / GRID_ROWS;
    for (int r = 0; r < GRID_ROWS; r++) {
        lv_coord_t this_h = (r == GRID_ROWS - 1)
                            ? (LVGL_PORT_V_RES - r * band_h)
                            : band_h;
        lv_obj_t *band = lv_obj_create(scr);
        lv_obj_add_flag(band, LV_OBJ_FLAG_IGNORE_LAYOUT);
        lv_obj_clear_flag(band, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
        lv_obj_set_pos(band, 0, r * band_h);
        lv_obj_set_size(band, LVGL_PORT_H_RES, this_h);
        lv_obj_set_style_bg_color(band, s_row_bg_colors[r], 0);
        lv_obj_set_style_bg_opa(band, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(band, 0, 0);
        lv_obj_set_style_radius(band, 0, 0);
        lv_obj_set_style_pad_all(band, 0, 0);
        s_bg_bands[r] = band;
    }

    /* ── Left strip: line labels (L1 / L2 / L3) ──────────────────── */
    lv_obj_t *left_strip = lv_obj_create(scr);
    lv_obj_set_size(left_strip, LEFT_STRIP_W, LVGL_PORT_V_RES);
    lv_obj_set_pos(left_strip, 0, 0);
    lv_obj_set_style_bg_opa(left_strip, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(left_strip, 0, 0);
    lv_obj_set_style_pad_all(left_strip, 0, 0);
    lv_obj_clear_flag(left_strip, LV_OBJ_FLAG_SCROLLABLE);

    lv_coord_t seg_h = LVGL_PORT_V_RES / GRID_ROWS;
    for (int row_idx = 0; row_idx < GRID_ROWS; row_idx++) {
        lv_obj_t *seg = lv_obj_create(left_strip);
        lv_obj_add_flag(seg, LV_OBJ_FLAG_IGNORE_LAYOUT);
        lv_obj_clear_flag(seg, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_pos(seg, 0, row_idx * seg_h);
        lv_obj_set_size(seg, LEFT_STRIP_W, seg_h);
        lv_obj_set_style_bg_opa(seg, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(seg, 0, 0);
        lv_obj_set_style_pad_all(seg, 0, 0);
        lv_obj_set_style_radius(seg, 0, 0);

        lv_obj_t *lbl = lv_label_create(seg);
        lv_label_set_text(lbl, s_line_labels[row_idx]);
        lv_obj_set_style_text_color(lbl, lv_color_white(), 0);
        lv_obj_set_style_text_align(lbl, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_width(lbl, LEFT_STRIP_W);
        lv_obj_center(lbl);
    }

    /* ── 3×3 grid container ───────────────────────────────────────── */
    static lv_coord_t col_dsc[] = {
        LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_TEMPLATE_LAST
    };
    static lv_coord_t row_dsc[] = {
        LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_FR(1), LV_GRID_TEMPLATE_LAST
    };

    lv_obj_t *grid = lv_obj_create(scr);
    lv_obj_set_size(grid, LVGL_PORT_H_RES - LEFT_STRIP_W, LVGL_PORT_V_RES);
    lv_obj_set_pos(grid, LEFT_STRIP_W, 0);
    lv_obj_set_style_bg_opa(grid, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(grid, 0, 0);
    lv_obj_set_style_pad_all(grid, 4, 0);
    lv_obj_set_style_pad_column(grid, 4, 0);
    lv_obj_set_style_pad_row(grid, 4, 0);
    lv_obj_clear_flag(grid, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_layout(grid, LV_LAYOUT_GRID);
    lv_obj_set_grid_dsc_array(grid, col_dsc, row_dsc);

    for (int i = 0; i < BAR_COUNT; i++) {
        int col = i % GRID_COLS;
        int row = i / GRID_COLS;

        s_cells[i].current   = 0;
        s_cells[i].day_total = 0;

        /* ── Cell container ───────────────────────────────────────── */
        lv_obj_t *cell = lv_obj_create(grid);
        lv_obj_set_grid_cell(cell,
                             LV_GRID_ALIGN_STRETCH, col, 1,
                             LV_GRID_ALIGN_STRETCH, row, 1);
        lv_obj_set_style_pad_all(cell, 6, 0);
        lv_obj_set_style_bg_opa(cell, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_color(cell, row_border_colors[row], 0);
        lv_obj_set_style_border_width(cell, 1, 0);
        lv_obj_set_style_radius(cell, 4, 0);
        lv_obj_clear_flag(cell, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_layout(cell, LV_LAYOUT_FLEX);
        lv_obj_set_flex_flow(cell, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(cell,
                              LV_FLEX_ALIGN_SPACE_BETWEEN,
                              LV_FLEX_ALIGN_CENTER,
                              LV_FLEX_ALIGN_CENTER);

        /* ── Zone label (top) ─────────────────────────────────────── */
        lv_obj_t *zone_lbl = lv_label_create(cell);
        lv_label_set_text(zone_lbl, s_zone_names[i]);
        lv_obj_set_style_text_color(zone_lbl, lv_color_white(), 0);
        lv_obj_set_style_text_align(zone_lbl, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_width(zone_lbl, lv_pct(100));

        /* ── Fill bar ─────────────────────────────────────────────── */
        lv_obj_t *bar = lv_bar_create(cell);
        lv_obj_set_size(bar, lv_pct(100), BAR_H);
        lv_bar_set_range(bar, 0, VALUE_MAX);
        lv_bar_set_value(bar, 0, LV_ANIM_OFF);
        lv_obj_set_style_bg_color(bar, lv_color_make(50, 50, 70), LV_PART_MAIN);
        lv_obj_set_style_radius(bar, 4, LV_PART_MAIN);
        lv_obj_set_style_border_color(bar, lv_color_make(80, 80, 110), LV_PART_MAIN);
        lv_obj_set_style_border_width(bar, 1, LV_PART_MAIN);
        lv_obj_set_style_pad_all(bar, 0, LV_PART_MAIN);
        lv_obj_set_style_bg_color(bar, count_to_color(0), LV_PART_INDICATOR);
        lv_obj_set_style_radius(bar, 4, LV_PART_INDICATOR);
        lv_obj_clear_flag(bar, LV_OBJ_FLAG_CLICKABLE);
        s_cells[i].bar = bar;

        /* ── Count label row ──────────────────────────────────────── */
        lv_obj_t *count_row = lv_obj_create(cell);
        lv_obj_set_size(count_row, lv_pct(100), LV_SIZE_CONTENT);
        lv_obj_set_style_bg_opa(count_row, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(count_row, 0, 0);
        lv_obj_set_style_pad_all(count_row, 2, 0);
        lv_obj_set_style_pad_column(count_row, 4, 0);
        lv_obj_clear_flag(count_row, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_layout(count_row, LV_LAYOUT_FLEX);
        lv_obj_set_flex_flow(count_row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(count_row,
                              LV_FLEX_ALIGN_SPACE_EVENLY,
                              LV_FLEX_ALIGN_CENTER,
                              LV_FLEX_ALIGN_CENTER);

        /* NOW label */
        lv_obj_t *lbl_cur = lv_label_create(count_row);
        lv_label_set_text(lbl_cur, "NOW: 0");
        lv_obj_set_style_text_color(lbl_cur, lv_color_make(100, 240, 100), 0);
        s_cells[i].lbl_current = lbl_cur;

        /* DAY label */
        lv_obj_t *lbl_day = lv_label_create(count_row);
        lv_label_set_text(lbl_day, "DAY: 0");
        lv_obj_set_style_text_color(lbl_day, lv_color_make(100, 180, 255), 0);
        s_cells[i].lbl_day = lbl_day;
    }
}
