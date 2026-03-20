#include <string.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "mqtt_client.h"
#include "cJSON.h"

#include "waveshare_rgb_lcd_port.h"
#include "ui.h"

/*
 * wifi_creds.h is git-ignored.  Copy wifi_creds.h.example → wifi_creds.h
 * and fill in your SSID / password / broker IP before building.
 */
#include "wifi_creds.h"

static const char *TAG = "main";

/* Zone name → index mapping (must match ui.c row-major order 0-8) */
static const char *s_zone_names[9] = {
    "L1Z1", "L1Z2", "L1Z3",
    "L2Z1", "L2Z2", "L2Z3",
    "L3Z1", "L3Z2", "L3Z3",
};
#define ZONE_COUNT 9

#define MQTT_TOPIC "Conveyor/Current_Count/Day_Total_Count"

/* ── MQTT event handler ─────────────────────────────────────────────── */
static void mqtt_event_handler(void *handler_args, esp_event_base_t base,
                               int32_t event_id, void *event_data)
{
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)event_data;

    switch (event->event_id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT connected, subscribing to %s", MQTT_TOPIC);
        esp_mqtt_client_subscribe(event->client, MQTT_TOPIC, 0);
        break;

    case MQTT_EVENT_DATA: {
        /* Parse JSON payload and update UI cells */
        char *payload = (char *)malloc(event->data_len + 1);
        if (!payload) break;
        memcpy(payload, event->data, event->data_len);
        payload[event->data_len] = '\0';

        cJSON *root = cJSON_Parse(payload);
        free(payload);
        if (!root) break;

        for (int i = 0; i < ZONE_COUNT; i++) {
            cJSON *zone = cJSON_GetObjectItemCaseSensitive(root, s_zone_names[i]);
            if (!zone) continue;
            cJSON *cur = cJSON_GetObjectItemCaseSensitive(zone, "current");
            cJSON *day = cJSON_GetObjectItemCaseSensitive(zone, "day_total");
            if (cJSON_IsNumber(cur) && cJSON_IsNumber(day)) {
                app_ui_set_zone(i, cur->valueint, day->valueint);
            }
        }
        cJSON_Delete(root);
        break;
    }

    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "MQTT disconnected");
        break;

    default:
        break;
    }
}

/* ── Wi-Fi event handler ────────────────────────────────────────────── */
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT &&
               event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected, retrying…");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&e->ip_info.ip));
    }
}

/* ── Wi-Fi initialisation ───────────────────────────────────────────── */
static void wifi_init(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_cfg));

    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                        wifi_event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                        wifi_event_handler, NULL, NULL);

    wifi_config_t wifi_cfg = {
        .sta = {
            .ssid     = WIFI_SSID,
            .password = WIFI_PASSWORD,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "Wi-Fi init complete, connecting to %s…", WIFI_SSID);
}

/* ── MQTT client initialisation ─────────────────────────────────────── */
static void mqtt_start(void)
{
    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = "mqtt://" WIFI_MQTT_BROKER,
    };
    esp_mqtt_client_handle_t client = esp_mqtt_client_init(&cfg);
    esp_mqtt_client_register_event(client, ESP_EVENT_ANY_ID,
                                   mqtt_event_handler, NULL);
    esp_mqtt_client_start(client);
}

/* ── Entry point ────────────────────────────────────────────────────── */
void app_main(void)
{
    ESP_ERROR_CHECK(waveshare_esp32_s3_rgb_lcd_init());

    ESP_LOGI(TAG, "Initialising conveyor display UI");
    if (lvgl_port_lock(-1)) {
        app_ui_init();
        lvgl_port_unlock();
    }

    wifi_init();
    mqtt_start();
}
