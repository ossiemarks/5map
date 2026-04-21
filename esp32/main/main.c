/**
 * 5map ESP32 BLE + CSI Scanner
 *
 * Scans for Bluetooth (BLE + Classic) devices and captures WiFi CSI data,
 * outputting JSON lines over USB serial to the Raspberry Pi host.
 *
 * Output format (one JSON object per line):
 *   BLE:  {"t":"ble","mac":"aa:bb:cc:dd:ee:ff","name":"iPhone","rssi":-62,"tx":-12,"adv":0,"svc":["FE2C"],"mfr":"4C00","conn":1}
 *   CSI:  {"t":"csi","mac":"11:22:33:44:55:66","rssi":-55,"ch":6,"bw":20,"len":128,"ts":123456}
 *
 * Built with ESP-IDF v5.x
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include "esp_bt.h"
#include "esp_bt_main.h"
#include "esp_gap_ble_api.h"
#include "esp_bt_defs.h"
#include "esp_gap_bt_api.h"
#include "esp_gattc_api.h"

static const char *TAG = "5map-esp32";

/* ── BLE scan parameters ── */
static esp_ble_scan_params_t ble_scan_params = {
    .scan_type          = BLE_SCAN_TYPE_ACTIVE,
    .own_addr_type      = BLE_ADDR_TYPE_PUBLIC,
    .scan_filter_policy = BLE_SCAN_FILTER_ALLOW_ALL,
    .scan_interval      = 0x50,    /* 50ms */
    .scan_window        = 0x30,    /* 30ms */
    .scan_duplicate     = BLE_SCAN_DUPLICATE_DISABLE,
};

/* ── Helpers ── */

static void mac_to_str(const uint8_t *mac, char *out) {
    sprintf(out, "%02x:%02x:%02x:%02x:%02x:%02x",
            mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void escape_json_string(const char *in, char *out, size_t max_len) {
    size_t j = 0;
    for (size_t i = 0; in[i] && j < max_len - 2; i++) {
        char c = in[i];
        if (c == '"' || c == '\\') {
            out[j++] = '\\';
            if (j >= max_len - 1) break;
        }
        if (c >= 0x20 && c < 0x7F) {
            out[j++] = c;
        }
    }
    out[j] = '\0';
}

/* Extract 16-bit service UUIDs from advertisement data */
static int extract_service_uuids(uint8_t *adv_data, uint8_t adv_len, char *out, size_t max) {
    int pos = 0;
    uint8_t i = 0;
    int first = 1;

    pos += snprintf(out + pos, max - pos, "[");

    while (i < adv_len) {
        uint8_t field_len = adv_data[i];
        if (field_len == 0 || i + field_len >= adv_len) break;
        uint8_t field_type = adv_data[i + 1];

        /* 0x02/0x03 = incomplete/complete 16-bit UUID list */
        if (field_type == 0x02 || field_type == 0x03) {
            for (uint8_t j = 2; j < field_len + 1 && j + 1 < field_len + 1; j += 2) {
                uint16_t uuid = adv_data[i + j] | (adv_data[i + j + 1] << 8);
                if (!first) pos += snprintf(out + pos, max - pos, ",");
                pos += snprintf(out + pos, max - pos, "\"%04X\"", uuid);
                first = 0;
                if ((size_t)pos >= max - 10) break;
            }
        }
        i += field_len + 1;
    }
    pos += snprintf(out + pos, max - pos, "]");
    return pos;
}

/* Extract manufacturer data (first 2 bytes = company ID) */
static int extract_manufacturer(uint8_t *adv_data, uint8_t adv_len, char *out, size_t max) {
    uint8_t i = 0;
    while (i < adv_len) {
        uint8_t field_len = adv_data[i];
        if (field_len == 0 || i + field_len >= adv_len) break;
        uint8_t field_type = adv_data[i + 1];

        if (field_type == 0xFF && field_len >= 3) {
            uint16_t company = adv_data[i + 2] | (adv_data[i + 3] << 8);
            snprintf(out, max, "%04X", company);
            return 1;
        }
        i += field_len + 1;
    }
    out[0] = '\0';
    return 0;
}

/* ── BLE GAP callback ── */

static void gap_ble_cb(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
    switch (event) {
    case ESP_GAP_BLE_SCAN_RESULT_EVT: {
        esp_ble_gap_cb_param_t *scan_result = param;
        if (scan_result->scan_rst.search_evt == ESP_GAP_SEARCH_INQ_RES_EVT) {
            char mac_str[18];
            mac_to_str(scan_result->scan_rst.bda, mac_str);

            /* Device name */
            uint8_t *adv_name = NULL;
            uint8_t name_len = 0;
            adv_name = esp_ble_resolve_adv_data(
                scan_result->scan_rst.ble_adv,
                ESP_BLE_AD_TYPE_NAME_CMPL, &name_len);
            if (!adv_name) {
                adv_name = esp_ble_resolve_adv_data(
                    scan_result->scan_rst.ble_adv,
                    ESP_BLE_AD_TYPE_NAME_SHORT, &name_len);
            }

            char name_escaped[64] = "";
            if (adv_name && name_len > 0) {
                char name_raw[64];
                size_t copy_len = name_len < 63 ? name_len : 63;
                memcpy(name_raw, adv_name, copy_len);
                name_raw[copy_len] = '\0';
                escape_json_string(name_raw, name_escaped, sizeof(name_escaped));
            }

            /* TX power */
            uint8_t *tx_data = NULL;
            uint8_t tx_len = 0;
            int8_t tx_power = 0;
            int has_tx = 0;
            tx_data = esp_ble_resolve_adv_data(
                scan_result->scan_rst.ble_adv,
                ESP_BLE_AD_TYPE_TX_PWR, &tx_len);
            if (tx_data && tx_len > 0) {
                tx_power = (int8_t)tx_data[0];
                has_tx = 1;
            }

            /* Service UUIDs */
            char svc_str[256];
            extract_service_uuids(scan_result->scan_rst.ble_adv,
                                  scan_result->scan_rst.adv_data_len,
                                  svc_str, sizeof(svc_str));

            /* Manufacturer */
            char mfr_str[16];
            extract_manufacturer(scan_result->scan_rst.ble_adv,
                                 scan_result->scan_rst.adv_data_len,
                                 mfr_str, sizeof(mfr_str));

            /* Connectable */
            int connectable = (scan_result->scan_rst.ble_evt_type == ESP_BLE_EVT_CONN_ADV ||
                               scan_result->scan_rst.ble_evt_type == ESP_BLE_EVT_CONN_DIR_ADV);

            /* Output JSON line */
            printf("{\"t\":\"ble\",\"mac\":\"%s\",\"name\":\"%s\","
                   "\"rssi\":%d,\"tx\":%d,\"tx_v\":%d,"
                   "\"adv\":%d,\"svc\":%s,\"mfr\":\"%s\",\"conn\":%d}\n",
                   mac_str, name_escaped,
                   scan_result->scan_rst.rssi,
                   has_tx ? tx_power : 0, has_tx,
                   scan_result->scan_rst.ble_evt_type,
                   svc_str, mfr_str, connectable);
            fflush(stdout);
        }
        else if (scan_result->scan_rst.search_evt == ESP_GAP_SEARCH_INQ_CMPL_EVT) {
            /* Restart scan continuously */
            esp_ble_gap_start_scanning(0);
        }
        break;
    }
    case ESP_GAP_BLE_SCAN_START_COMPLETE_EVT:
        if (param->scan_start_cmpl.status != ESP_BT_STATUS_SUCCESS) {
            ESP_LOGE(TAG, "BLE scan start failed: %d", param->scan_start_cmpl.status);
        } else {
            ESP_LOGI(TAG, "BLE scan started");
        }
        break;
    default:
        break;
    }
}

/* ── WiFi CSI callback ── */

static void wifi_csi_cb(void *ctx, wifi_csi_info_t *info) {
    if (!info || !info->buf || info->len == 0) return;

    char mac_str[18];
    mac_to_str(info->mac, mac_str);

    printf("{\"t\":\"csi\",\"mac\":\"%s\",\"rssi\":%d,"
           "\"ch\":%d,\"bw\":%d,\"len\":%d,\"ts\":%lld}\n",
           mac_str, info->rx_ctrl.rssi,
           info->rx_ctrl.channel,
           info->rx_ctrl.cwb == 0 ? 20 : 40,
           info->len,
           (long long)(esp_timer_get_time() / 1000));
    fflush(stdout);
}

/* ── WiFi CSI setup ── */

static void init_wifi_csi(void) {
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_start());

    wifi_csi_config_t csi_cfg = {
        .lltf_en           = true,
        .htltf_en          = true,
        .stbc_htltf2_en    = true,
        .ltf_merge_en      = true,
        .channel_filter_en = false,
        .manu_scale        = false,
        .shift             = false,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));

    ESP_LOGI(TAG, "WiFi CSI capture enabled");
}

/* ── BLE setup ── */

static void init_ble(void) {
    ESP_ERROR_CHECK(esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT));

    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bt_controller_init(&bt_cfg));
    ESP_ERROR_CHECK(esp_bt_controller_enable(ESP_BT_MODE_BLE));
    ESP_ERROR_CHECK(esp_bluedroid_init());
    ESP_ERROR_CHECK(esp_bluedroid_enable());
    ESP_ERROR_CHECK(esp_ble_gap_register_callback(gap_ble_cb));
    ESP_ERROR_CHECK(esp_ble_gap_set_scan_params(&ble_scan_params));

    /* Start continuous scan (0 = indefinite) */
    esp_ble_gap_start_scanning(0);

    ESP_LOGI(TAG, "BLE scanner started");
}

/* ── Heartbeat task ── */

static void heartbeat_task(void *pvParameters) {
    while (1) {
        printf("{\"t\":\"hb\",\"heap\":%lu,\"ts\":%lld}\n",
               (unsigned long)esp_get_free_heap_size(),
               (long long)(esp_timer_get_time() / 1000));
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}

/* ── Main ── */

void app_main(void) {
    /* NVS init (required for WiFi + BT) */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ESP_LOGI(TAG, "5map ESP32 scanner starting...");

    /* Init WiFi CSI first (needs WiFi stack) */
    init_wifi_csi();

    /* Init BLE scanner */
    init_ble();

    /* Heartbeat for health monitoring */
    xTaskCreate(heartbeat_task, "heartbeat", 2048, NULL, 1, NULL);

    ESP_LOGI(TAG, "5map ESP32 ready - streaming BLE + CSI data");
}
