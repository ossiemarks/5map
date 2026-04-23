/**
 * 5map ESP32-S2 WiFi CSI Scanner
 *
 * Captures WiFi Channel State Information with full subcarrier amplitude/phase
 * data, outputting JSON lines over USB serial to the host.
 *
 * ESP32-S2 has WiFi + USB OTG but NO Bluetooth. BLE scanning runs on
 * a separate ESP32 (original) or via the Pineapple.
 *
 * Output format (one JSON object per line):
 *   CSI:  {"t":"csi","mac":"11:22:33:44:55:66","rssi":-55,"ch":6,"bw":20,"len":128,"ns":64,"noise":-90,"rate":11,"ts":123456,"data":"<base64>"}
 *   WiFi: {"t":"wifi","mac":"AA:BB:CC:DD:EE:FF","ssid":"Name","rssi":-65,"ch":6,"auth":"WPA2-PSK","bw":"2.4GHz"}
 *   HB:   {"t":"hb","heap":123456,"csi_frames":1000,"csi_rate":100,"wifi_connected":1,"ts":123456}
 *
 * CSI data field contains base64-encoded int8 pairs [imag,real] per subcarrier.
 * Decode on host: amplitude = sqrt(real^2 + imag^2), phase = atan2(imag, real).
 *
 * Connects to a configured WiFi AP (mini router) for consistent CSI frames.
 *
 * Built with ESP-IDF v5.x, target: ESP32-S2
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
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "mbedtls/base64.h"

static const char *TAG = "5map-s2";

/* ── CSI transmitter AP config ── */
#ifndef CONFIG_CSI_AP_SSID
#define CONFIG_CSI_AP_SSID "GL-MT300N-V2-283"
#endif
#ifndef CONFIG_CSI_AP_PASS
#define CONFIG_CSI_AP_PASS "goodlife"
#endif
#ifndef CONFIG_CSI_AP_CHANNEL
#define CONFIG_CSI_AP_CHANNEL 6
#endif

/* WiFi connection state */
static EventGroupHandle_t s_wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1
static int s_retry_num = 0;
#define MAX_RETRY 10
static volatile bool s_wifi_connected = false;

/* CSI frame counter for rate tracking */
static volatile uint32_t csi_frame_count = 0;

/* WiFi scan state */
static volatile uint32_t wifi_scan_count = 0;

/* ── Helpers ── */

static void mac_to_str(const uint8_t *mac, char *out) {
    sprintf(out, "%02x:%02x:%02x:%02x:%02x:%02x",
            mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void format_mac_upper(const uint8_t *mac, char *out) {
    sprintf(out, "%02X:%02X:%02X:%02X:%02X:%02X",
            mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

/* ── WiFi event handler ── */

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                                int32_t event_id, void *event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_wifi_connected = false;
        if (s_retry_num < MAX_RETRY) {
            esp_wifi_connect();
            s_retry_num++;
            ESP_LOGI(TAG, "Retrying WiFi (%d/%d)", s_retry_num, MAX_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
            ESP_LOGW(TAG, "WiFi failed after %d retries, CSI from beacons only", MAX_RETRY);
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Connected to CSI AP, IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_num = 0;
        s_wifi_connected = true;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

/* ── WiFi CSI callback with full subcarrier data ── */

static void wifi_csi_cb(void *ctx, wifi_csi_info_t *info) {
    if (!info || !info->buf || info->len == 0) return;

    char mac_str[18];
    mac_to_str(info->mac, mac_str);

    /* Base64-encode the raw CSI buffer (int8 I/Q pairs) */
    size_t b64_len = 0;
    mbedtls_base64_encode(NULL, 0, &b64_len,
                          (const unsigned char *)info->buf, info->len);

    char *b64_buf = malloc(b64_len + 1);
    if (!b64_buf) return;

    mbedtls_base64_encode((unsigned char *)b64_buf, b64_len + 1, &b64_len,
                          (const unsigned char *)info->buf, info->len);
    b64_buf[b64_len] = '\0';

    int bw = info->rx_ctrl.cwb == 0 ? 20 : 40;
    int num_subcarriers = info->len / 2;

    printf("{\"t\":\"csi\",\"mac\":\"%s\",\"rssi\":%d,"
           "\"ch\":%d,\"bw\":%d,\"len\":%d,\"ns\":%d,"
           "\"noise\":%d,\"rate\":%d,"
           "\"ts\":%lld,\"data\":\"%s\"}\n",
           mac_str, info->rx_ctrl.rssi,
           info->rx_ctrl.channel, bw,
           info->len, num_subcarriers,
           info->rx_ctrl.noise_floor,
           info->rx_ctrl.rate,
           (long long)(esp_timer_get_time() / 1000),
           b64_buf);
    fflush(stdout);

    free(b64_buf);
    csi_frame_count++;
}

/* ── WiFi AP scan (replaces BLE for device discovery on S2) ── */

static const char *auth_mode_str(wifi_auth_mode_t mode) {
    switch (mode) {
    case WIFI_AUTH_OPEN:            return "open";
    case WIFI_AUTH_WEP:             return "WEP";
    case WIFI_AUTH_WPA_PSK:         return "WPA-PSK";
    case WIFI_AUTH_WPA2_PSK:        return "WPA2-PSK";
    case WIFI_AUTH_WPA_WPA2_PSK:    return "WPA/WPA2-PSK";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-Enterprise";
    case WIFI_AUTH_WPA3_PSK:        return "WPA3-PSK";
    case WIFI_AUTH_WPA2_WPA3_PSK:   return "WPA2/WPA3-PSK";
    default:                        return "unknown";
    }
}

static void wifi_scan_task(void *pvParameters) {
    /* Periodic WiFi AP scan for environment mapping */
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000));

        wifi_scan_config_t scan_config = {
            .ssid = NULL,
            .bssid = NULL,
            .channel = 0,
            .show_hidden = true,
            .scan_type = WIFI_SCAN_TYPE_ACTIVE,
            .scan_time.active.min = 100,
            .scan_time.active.max = 300,
        };

        esp_err_t err = esp_wifi_scan_start(&scan_config, true);
        if (err != ESP_OK) continue;

        uint16_t ap_count = 0;
        esp_wifi_scan_get_ap_num(&ap_count);
        if (ap_count == 0) continue;
        if (ap_count > 30) ap_count = 30;

        wifi_ap_record_t *ap_list = malloc(sizeof(wifi_ap_record_t) * ap_count);
        if (!ap_list) continue;

        esp_wifi_scan_get_ap_records(&ap_count, ap_list);

        for (int i = 0; i < ap_count; i++) {
            char mac_str[18];
            format_mac_upper(ap_list[i].bssid, mac_str);

            char ssid_safe[33];
            size_t j = 0, k = 0;
            for (; j < 32 && ap_list[i].ssid[j]; j++) {
                char c = (char)ap_list[i].ssid[j];
                if (c == '"' || c == '\\') {
                    ssid_safe[k++] = '\\';
                    if (k >= 31) break;
                }
                if (c >= 0x20 && c < 0x7F) {
                    ssid_safe[k++] = c;
                    if (k >= 32) break;
                }
            }
            ssid_safe[k] = '\0';

            printf("{\"t\":\"wifi\",\"mac\":\"%s\",\"ssid\":\"%s\","
                   "\"rssi\":%d,\"ch\":%d,"
                   "\"auth\":\"%s\",\"bw\":\"%s\"}\n",
                   mac_str,
                   k > 0 ? ssid_safe : "-",
                   ap_list[i].rssi,
                   ap_list[i].primary,
                   auth_mode_str(ap_list[i].authmode),
                   ap_list[i].primary <= 14 ? "2.4GHz" : "5GHz");
            fflush(stdout);
        }

        free(ap_list);
        wifi_scan_count++;
    }
}

/* ── WiFi CSI + STA setup ── */

static void init_wifi(void) {
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, &instance_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, &instance_got_ip));

    /* Configure STA to connect to the CSI transmitter router */
    wifi_config_t wifi_config = {
        .sta = {
            .ssid = CONFIG_CSI_AP_SSID,
            .password = CONFIG_CSI_AP_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
            .sae_pwe_h2e = WPA3_SAE_PWE_BOTH,
        },
    };

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    /* Enable CSI capture — may not be supported on all S2 revisions */
    wifi_csi_config_t csi_cfg = {
        .lltf_en           = true,
        .htltf_en          = true,
        .stbc_htltf2_en    = true,
        .ltf_merge_en      = true,
        .channel_filter_en = false,
        .manu_scale        = false,
        .shift             = false,
    };
    esp_err_t csi_err = esp_wifi_set_csi_config(&csi_cfg);
    if (csi_err == ESP_OK) {
        esp_wifi_set_csi_rx_cb(wifi_csi_cb, NULL);
        esp_wifi_set_csi(true);
        ESP_LOGI(TAG, "CSI capture enabled");
    } else {
        ESP_LOGW(TAG, "CSI not supported on this chip revision (err=0x%x), WiFi scan only", csi_err);
    }

    ESP_ERROR_CHECK(esp_wifi_start());

    /* Wait for connection */
    ESP_LOGI(TAG, "Connecting to CSI AP: %s", CONFIG_CSI_AP_SSID);
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
        WIFI_CONNECTED_BIT | WIFI_FAIL_BIT, pdFALSE, pdFALSE,
        pdMS_TO_TICKS(15000));

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Connected to CSI transmitter AP: %s", CONFIG_CSI_AP_SSID);
    } else {
        ESP_LOGW(TAG, "CSI AP not found, capturing ambient CSI from beacons");
    }

    ESP_LOGI(TAG, "WiFi CSI capture enabled (full subcarrier data)");
}

/* ── Heartbeat task ── */

static void heartbeat_task(void *pvParameters) {
    uint32_t prev_csi_count = 0;
    while (1) {
        uint32_t cur_csi = csi_frame_count;
        uint32_t csi_rate = (cur_csi - prev_csi_count);
        prev_csi_count = cur_csi;

        printf("{\"t\":\"hb\",\"heap\":%lu,\"csi_frames\":%lu,"
               "\"csi_rate\":%lu,\"wifi_connected\":%d,"
               "\"scans\":%lu,\"ts\":%lld}\n",
               (unsigned long)esp_get_free_heap_size(),
               (unsigned long)cur_csi,
               (unsigned long)csi_rate,
               s_wifi_connected ? 1 : 0,
               (unsigned long)wifi_scan_count,
               (long long)(esp_timer_get_time() / 1000));
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}

/* ── Main ── */

void app_main(void) {
    /* NVS init (required for WiFi) */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ESP_LOGI(TAG, "5map ESP32-S2 CSI scanner starting...");

    /* Boot message */
    printf("{\"t\":\"boot\",\"sid\":\"esp32s2-001\",\"fw\":\"csi_scanner_s2\","
           "\"ver\":\"2.0.0\",\"target\":\"esp32s2\"}\n");
    fflush(stdout);

    /* Init WiFi with CSI capture */
    init_wifi();

    /* WiFi AP scan task for environment mapping */
    xTaskCreate(wifi_scan_task, "wifi_scan", 4096, NULL, 2, NULL);

    /* Heartbeat for health monitoring */
    xTaskCreate(heartbeat_task, "heartbeat", 2048, NULL, 1, NULL);

    ESP_LOGI(TAG, "5map ESP32-S2 ready - streaming CSI + WiFi data");
}
