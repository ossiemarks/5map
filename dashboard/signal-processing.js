/**
 * 5map Signal Processing & Visualization Algorithms
 *
 * Self-contained vanilla JS module providing signal analysis, distance
 * estimation, radar/gauge/heatmap generators, and animation helpers for
 * the Visual Indicators dashboard page.
 *
 * All public functions accept raw data.json structures and return
 * render-ready data.  Zero external dependencies.
 */
var SignalProcessing = (function () {
  'use strict';

  // ─────────────────────────────────────────────────────────────
  // CONSTANTS & CONFIGURATION
  // ─────────────────────────────────────────────────────────────

  /** Default transmit power per device class (dBm at 1 m) */
  var TX_POWER_DEFAULTS = {
    ap:      -40,
    phone:   -59,
    laptop:  -59,
    iot:     -65,
    unknown: -59
  };

  /** Environment path-loss exponents */
  var PATH_LOSS = {
    FREE_SPACE:  2.0,
    INDOOR:      2.7,
    THROUGH_WALL: 3.0
  };

  /** WiFi channels grouped by band */
  var CHANNELS_24GHZ = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];
  var CHANNELS_5GHZ  = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112,
                        116, 120, 124, 128, 132, 136, 140, 144, 149, 153,
                        157, 161, 165];

  /** Proximity ring thresholds for BLE (RSSI dBm) */
  var BLE_RINGS = {
    IMMEDIATE: -50,
    NEAR:      -70,
    FAR:       -85
  };

  /** Gaussian-noise generator (Box-Muller) */
  function gaussianRandom(mean, stdDev) {
    var u = 0, v = 0;
    while (u === 0) u = Math.random();
    while (v === 0) v = Math.random();
    var z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
    return z * stdDev + mean;
  }

  /** Clamp a value between min and max */
  function clamp(val, lo, hi) {
    return val < lo ? lo : val > hi ? hi : val;
  }

  /** Linear interpolation */
  function lerp(a, b, t) {
    return a + (b - a) * t;
  }

  /** Convert degrees to radians */
  function degToRad(deg) {
    return deg * (Math.PI / 180);
  }

  // ─────────────────────────────────────────────────────────────
  // 1. RSSI-TO-DISTANCE ESTIMATION
  // ─────────────────────────────────────────────────────────────

  /**
   * Estimate distance from an RSSI reading using the log-distance
   * path-loss model.
   *
   * Model: RSSI = TxPower - 10 * n * log10(d)
   *   =>   d = 10 ^ ((TxPower - RSSI) / (10 * n))
   *
   * @param {number} rssi          - Measured RSSI in dBm
   * @param {number} [txPower]     - Transmit power at 1 m (dBm)
   * @param {number} [pathLossExp] - Path-loss exponent n
   * @param {string} [deviceType]  - 'ap' | 'phone' | 'laptop' | 'iot' | 'unknown'
   * @returns {{ distance_m: number, confidence: number, min_m: number, max_m: number, quality: string }}
   */
  function estimateDistance(rssi, txPower, pathLossExp, deviceType) {
    var tx = (typeof txPower === 'number') ? txPower
           : TX_POWER_DEFAULTS[deviceType] || TX_POWER_DEFAULTS.unknown;
    var n  = (typeof pathLossExp === 'number') ? pathLossExp : PATH_LOSS.INDOOR;

    // Guard: if RSSI >= TxPower the device is essentially at reference distance
    if (rssi >= tx) {
      return { distance_m: 0.5, confidence: 0.95, min_m: 0.1, max_m: 1.0, quality: 'Excellent' };
    }

    var exponent = (tx - rssi) / (10 * n);
    var distance = Math.pow(10, exponent);

    // Confidence band: uncertainty widens with distance
    // At close range RSSI is reliable; at long range multipath and
    // interference dominate.  Use +-15% close, +-50% far.
    var uncertaintyFactor = clamp(0.15 + 0.35 * (distance / 50), 0.15, 0.60);
    var minDist = Math.max(0.1, distance * (1 - uncertaintyFactor));
    var maxDist = distance * (1 + uncertaintyFactor);

    // Confidence score: higher RSSI => more reliable measurement
    var confidence = clamp(1 - ((tx - rssi) / 80), 0.1, 0.95);

    var quality;
    if (rssi >= -50)      quality = 'Excellent';
    else if (rssi >= -60) quality = 'Good';
    else if (rssi >= -70) quality = 'Fair';
    else if (rssi >= -80) quality = 'Weak';
    else                  quality = 'Dead';

    return {
      distance_m: Math.round(distance * 100) / 100,
      confidence: Math.round(confidence * 100) / 100,
      min_m:      Math.round(minDist * 100) / 100,
      max_m:      Math.round(maxDist * 100) / 100,
      quality:    quality
    };
  }

  /**
   * Batch-estimate distances for all WiFi + BLE devices.
   *
   * @param {object} data - Parsed data.json root
   * @param {number} [pathLossExp] - Override path-loss exponent
   * @returns {Array<{ mac_address: string, type: string, rssi: number, estimated: object }>}
   */
  function estimateAllDistances(data, pathLossExp) {
    var results = [];
    var devices = data.devices || [];
    var btDevices = data.bluetooth_devices || [];

    for (var i = 0; i < devices.length; i++) {
      var d = devices[i];
      results.push({
        mac_address: d.mac_address,
        type:        'wifi',
        device_type: d.device_type,
        label:       d.ssid || d.mac_address,
        rssi:        d.rssi_dbm,
        estimated:   estimateDistance(d.rssi_dbm, null, pathLossExp, d.device_type)
      });
    }

    for (var j = 0; j < btDevices.length; j++) {
      var bt = btDevices[j];
      var btTx = (typeof bt.tx_power === 'number') ? bt.tx_power : -12;
      results.push({
        mac_address: bt.mac_address,
        type:        'bluetooth',
        device_type: bt.device_type,
        label:       bt.device_name || bt.mac_address,
        rssi:        bt.rssi_dbm,
        estimated:   estimateDistance(bt.rssi_dbm, btTx, pathLossExp, 'unknown')
      });
    }

    return results;
  }

  // ─────────────────────────────────────────────────────────────
  // 2. POLAR RADAR PLOT DATA GENERATOR
  // ─────────────────────────────────────────────────────────────

  /**
   * Generate polar-coordinate data for a radar-style device map.
   *
   * Layout strategy:
   *   - 2.4 GHz WiFi devices:  left half    (90 .. 270 deg, top-to-bottom)
   *   - 5 GHz WiFi devices:    right half   (270 .. 90 deg via 360/0)
   *   - BLE devices:           bottom arc   (200 .. 340 deg)
   *
   * Radius is proportional to estimated distance (closer = nearer center).
   * Color encodes risk_score, size encodes device_type.
   *
   * @param {object} data          - Parsed data.json root
   * @param {number} [maxRadius]   - Pixel radius of the radar circle (default 200)
   * @param {number} [pathLossExp] - Override path-loss exponent
   * @returns {{ devices: Array, maxDistance: number, rings: Array<number> }}
   */
  function generateRadarData(data, maxRadius, pathLossExp) {
    maxRadius = maxRadius || 200;

    var wifi24 = [];
    var wifi5  = [];
    var ble    = [];

    var devices = data.devices || [];
    var btDevices = data.bluetooth_devices || [];

    // Classify WiFi devices by band
    for (var i = 0; i < devices.length; i++) {
      var d = devices[i];
      var est = estimateDistance(d.rssi_dbm, null, pathLossExp, d.device_type);
      var entry = {
        mac_address: d.mac_address,
        label:       d.ssid && d.ssid !== '-' ? d.ssid : d.mac_address.slice(-8),
        device_type: d.device_type,
        channel:     d.channel,
        bandwidth:   d.bandwidth,
        rssi:        d.rssi_dbm,
        risk_score:  d.risk_score || 0,
        distance:    est.distance_m,
        quality:     est.quality,
        is_randomized_mac: d.is_randomized_mac
      };
      if (d.bandwidth === '5GHz') {
        wifi5.push(entry);
      } else {
        wifi24.push(entry);
      }
    }

    // BLE devices
    for (var j = 0; j < btDevices.length; j++) {
      var bt = btDevices[j];
      var btTx = (typeof bt.tx_power === 'number') ? bt.tx_power : -12;
      var btEst = estimateDistance(bt.rssi_dbm, btTx, pathLossExp, 'unknown');
      ble.push({
        mac_address: bt.mac_address,
        label:       bt.device_name || bt.mac_address.slice(-8),
        device_type: bt.device_type,
        channel:     null,
        bandwidth:   'BLE',
        rssi:        bt.rssi_dbm,
        risk_score:  0,
        distance:    btEst.distance_m,
        quality:     btEst.quality,
        is_randomized_mac: false
      });
    }

    // Find maximum distance for normalisation
    var allEntries = wifi24.concat(wifi5).concat(ble);
    var maxDist = 1;
    for (var k = 0; k < allEntries.length; k++) {
      if (allEntries[k].distance > maxDist) maxDist = allEntries[k].distance;
    }
    // Round up to a nice number for ring labels
    var ringMax = Math.ceil(maxDist / 5) * 5;
    if (ringMax < 5) ringMax = 5;

    // Distribute angles
    function assignAngles(list, startDeg, endDeg) {
      if (list.length === 0) return;
      // Sort by channel then by RSSI for consistent grouping
      list.sort(function (a, b) {
        var chDiff = (a.channel || 0) - (b.channel || 0);
        return chDiff !== 0 ? chDiff : a.rssi - b.rssi;
      });
      var span = endDeg - startDeg;
      var step = list.length > 1 ? span / (list.length - 1) : 0;
      var offset = list.length === 1 ? span / 2 : 0;
      for (var idx = 0; idx < list.length; idx++) {
        list[idx].angle_deg = startDeg + offset + step * idx;
      }
    }

    assignAngles(wifi24, 100, 260);  // left half
    assignAngles(wifi5,  280, 80);   // right half (wraps through 0)
    assignAngles(ble,    200, 340);  // bottom arc

    // Convert to cartesian render coordinates
    var result = [];
    for (var m = 0; m < allEntries.length; m++) {
      var e = allEntries[m];
      var angleDeg = e.angle_deg || 0;
      var angleRad = degToRad(angleDeg - 90); // -90 so 0 deg = top
      var normRadius = (e.distance / ringMax) * maxRadius;
      normRadius = clamp(normRadius, 8, maxRadius); // keep min visible radius

      // Risk-based color
      var color;
      if (e.risk_score > 0.6)       color = { r: 255, g: 71,  b: 87,  hex: '#ff4757' };
      else if (e.risk_score > 0.3)  color = { r: 255, g: 165, b: 2,   hex: '#ffa502' };
      else                          color = { r: 46,  g: 213, b: 115, hex: '#2ed573' };

      // Size based on device type
      var size;
      switch (e.device_type) {
        case 'ap':      size = 10; break;
        case 'phone':   size = 7;  break;
        case 'laptop':  size = 7;  break;
        default:        size = 5;  break;
      }

      result.push({
        mac_address:  e.mac_address,
        label:        e.label,
        device_type:  e.device_type,
        bandwidth:    e.bandwidth,
        channel:      e.channel,
        rssi:         e.rssi,
        risk_score:   e.risk_score,
        distance_m:   e.distance,
        quality:      e.quality,
        angle_deg:    angleDeg,
        angle_rad:    angleRad,
        radius_px:    normRadius,
        x:            Math.cos(angleRad) * normRadius,
        y:            Math.sin(angleRad) * normRadius,
        color:        color,
        size:         size,
        is_randomized_mac: e.is_randomized_mac
      });
    }

    // Distance rings
    var rings = [];
    var ringCount = 4;
    for (var ri = 1; ri <= ringCount; ri++) {
      rings.push({
        radius_px: (ri / ringCount) * maxRadius,
        distance_m: Math.round((ri / ringCount) * ringMax * 10) / 10,
        label: Math.round((ri / ringCount) * ringMax) + 'm'
      });
    }

    return {
      devices:     result,
      maxDistance:  ringMax,
      maxRadius:   maxRadius,
      rings:       rings
    };
  }

  // ─────────────────────────────────────────────────────────────
  // 3. SIGNAL STRENGTH GAUGE GENERATOR
  // ─────────────────────────────────────────────────────────────

  /**
   * Map an RSSI value to a 0-100 percentage using piecewise linear
   * interpolation across reference points.
   *
   * Reference curve:
   *   -30 dBm = 100%  (best practical)
   *   -50 dBm =  70%
   *   -70 dBm =  40%
   *   -90 dBm =  10%
   *  -100 dBm =   0%
   *
   * @param {number} rssi - RSSI in dBm
   * @returns {number} 0..100
   */
  function rssiToPercent(rssi) {
    var points = [
      { rssi: -30,  pct: 100 },
      { rssi: -50,  pct: 70 },
      { rssi: -70,  pct: 40 },
      { rssi: -90,  pct: 10 },
      { rssi: -100, pct: 0 }
    ];

    if (rssi >= points[0].rssi) return 100;
    if (rssi <= points[points.length - 1].rssi) return 0;

    for (var i = 0; i < points.length - 1; i++) {
      if (rssi >= points[i + 1].rssi) {
        var t = (rssi - points[i + 1].rssi) / (points[i].rssi - points[i + 1].rssi);
        return Math.round(lerp(points[i + 1].pct, points[i].pct, t));
      }
    }
    return 0;
  }

  /**
   * Produce gauge data for every WiFi and BLE device.
   *
   * @param {object} data - Parsed data.json root
   * @returns {Array<{ mac_address: string, label: string, rssi: number,
   *                    percentage: number, color: string, quality: string,
   *                    arc_start: number, arc_end: number }>}
   */
  function generateGaugeData(data) {
    var results = [];
    var devices = data.devices || [];
    var btDevices = data.bluetooth_devices || [];

    function processDevice(mac, label, rssi, type) {
      var pct = rssiToPercent(rssi);

      var color;
      if (pct >= 70)      color = '#2ed573'; // green
      else if (pct >= 40) color = '#ffa502'; // amber
      else if (pct >= 10) color = '#ff6348'; // orange
      else                color = '#ff4757'; // red

      var quality;
      if (pct >= 70)      quality = 'Excellent';
      else if (pct >= 55) quality = 'Good';
      else if (pct >= 35) quality = 'Fair';
      else if (pct >= 10) quality = 'Weak';
      else                quality = 'Dead';

      // Arc angles for a 240-degree gauge (starting at 150 deg, ending at 390 deg)
      var gaugeSpan = 240;
      var gaugeStart = 150;
      var arcEnd = gaugeStart + (pct / 100) * gaugeSpan;

      results.push({
        mac_address: mac,
        label:       label,
        type:        type,
        rssi:        rssi,
        percentage:  pct,
        color:       color,
        quality:     quality,
        arc_start:   gaugeStart,
        arc_end:     arcEnd,
        arc_span:    gaugeSpan
      });
    }

    for (var i = 0; i < devices.length; i++) {
      var d = devices[i];
      var lbl = d.ssid && d.ssid !== '-' ? d.ssid : d.mac_address;
      processDevice(d.mac_address, lbl, d.rssi_dbm, 'wifi');
    }
    for (var j = 0; j < btDevices.length; j++) {
      var bt = btDevices[j];
      processDevice(bt.mac_address, bt.device_name || bt.mac_address, bt.rssi_dbm, 'bluetooth');
    }

    // Sort strongest first
    results.sort(function (a, b) { return b.percentage - a.percentage; });
    return results;
  }

  // ─────────────────────────────────────────────────────────────
  // 4. CHANNEL UTILIZATION ANALYZER
  // ─────────────────────────────────────────────────────────────

  /**
   * Analyse channel utilisation across 2.4 GHz and 5 GHz bands.
   *
   * Congestion score per channel:
   *   score = min(1, (device_count / 5) * 0.6 + (1 - avg_rssi_norm) * 0.4)
   *
   * The first factor penalises channels with many devices, the second
   * factor penalises channels where the average signal is strong (meaning
   * nearby contention).
   *
   * @param {object} data - Parsed data.json root
   * @returns {{ band_24: Array, band_5: Array, summary: object }}
   */
  function analyzeChannelUtilization(data) {
    var devices = data.devices || [];

    // Bucket devices per channel
    var channelBuckets = {};
    for (var i = 0; i < devices.length; i++) {
      var ch = devices[i].channel;
      if (!ch || ch <= 0) continue;
      if (!channelBuckets[ch]) channelBuckets[ch] = [];
      channelBuckets[ch].push(devices[i]);
    }

    function buildChannelData(channelList, bandLabel) {
      var results = [];
      for (var ci = 0; ci < channelList.length; ci++) {
        var ch = channelList[ci];
        var bucket = channelBuckets[ch] || [];
        var count = bucket.length;

        // Average RSSI on this channel
        var rssiSum = 0;
        var riskSum = 0;
        for (var di = 0; di < bucket.length; di++) {
          rssiSum += bucket[di].rssi_dbm;
          riskSum += (bucket[di].risk_score || 0);
        }
        var avgRssi = count > 0 ? rssiSum / count : -100;
        var avgRisk = count > 0 ? riskSum / count : 0;

        // Normalise RSSI: -30 dBm = 1.0 (strong), -100 dBm = 0.0
        var rssiNorm = clamp((avgRssi + 100) / 70, 0, 1);

        // Congestion: more devices and stronger signals = more congestion
        var congestion = clamp(
          (Math.min(count, 5) / 5) * 0.6 + rssiNorm * 0.4,
          0, 1
        );

        // Color: low congestion = green, high = red
        var color;
        if (congestion < 0.3)      color = '#2ed573';
        else if (congestion < 0.6) color = '#ffa502';
        else                       color = '#ff4757';

        results.push({
          channel:       ch,
          band:          bandLabel,
          device_count:  count,
          avg_rssi:      Math.round(avgRssi),
          avg_risk:      Math.round(avgRisk * 100) / 100,
          congestion:    Math.round(congestion * 100) / 100,
          color:         color,
          devices:       bucket.map(function (d) {
            return { mac: d.mac_address, ssid: d.ssid, rssi: d.rssi_dbm, risk: d.risk_score };
          })
        });
      }
      return results;
    }

    var band24 = buildChannelData(CHANNELS_24GHZ, '2.4GHz');
    var band5  = buildChannelData(CHANNELS_5GHZ, '5GHz');

    // Filter to only channels that have at least 1 device (for cleaner visualisation)
    var band24Active = band24.filter(function (c) { return c.device_count > 0; });
    var band5Active  = band5.filter(function (c) { return c.device_count > 0; });

    // Summary
    var totalDevices24 = 0, totalDevices5 = 0;
    var maxCongestion24 = 0, maxCongestion5 = 0;
    var busiestCh24 = null, busiestCh5 = null;

    for (var a = 0; a < band24.length; a++) {
      totalDevices24 += band24[a].device_count;
      if (band24[a].congestion > maxCongestion24) {
        maxCongestion24 = band24[a].congestion;
        busiestCh24 = band24[a].channel;
      }
    }
    for (var b = 0; b < band5.length; b++) {
      totalDevices5 += band5[b].device_count;
      if (band5[b].congestion > maxCongestion5) {
        maxCongestion5 = band5[b].congestion;
        busiestCh5 = band5[b].channel;
      }
    }

    return {
      band_24:     band24,
      band_5:      band5,
      band_24_active: band24Active,
      band_5_active:  band5Active,
      summary: {
        total_devices_24:  totalDevices24,
        total_devices_5:   totalDevices5,
        busiest_channel_24: busiestCh24,
        busiest_channel_5:  busiestCh5,
        max_congestion_24:  maxCongestion24,
        max_congestion_5:   maxCongestion5,
        recommended_24:     _recommendChannel(band24),
        recommended_5:      _recommendChannel(band5)
      }
    };
  }

  /**
   * Recommend the least congested channel from a channel list.
   * @private
   */
  function _recommendChannel(channelData) {
    var best = null;
    var bestScore = 2;
    for (var i = 0; i < channelData.length; i++) {
      if (channelData[i].congestion < bestScore) {
        bestScore = channelData[i].congestion;
        best = channelData[i].channel;
      }
    }
    return best;
  }

  // ─────────────────────────────────────────────────────────────
  // 5. BLUETOOTH PROXIMITY RING CALCULATOR
  // ─────────────────────────────────────────────────────────────

  /**
   * Classify BLE devices into concentric proximity rings.
   *
   *   Ring 1  Immediate  (<1 m)    RSSI > -50
   *   Ring 2  Near       (1-3 m)   -50 >= RSSI > -70
   *   Ring 3  Far        (3-10 m)  -70 >= RSSI > -85
   *   Ring 4  Remote     (>10 m)   RSSI <= -85
   *
   * @param {object} data - Parsed data.json root
   * @returns {{ rings: Array<object>, devices: Array<object> }}
   */
  function calculateBleProximityRings(data) {
    var btDevices = data.bluetooth_devices || [];

    var rings = [
      { id: 1, label: 'Immediate', range: '<1m', color: '#2ed573', minRssi: BLE_RINGS.IMMEDIATE, devices: [] },
      { id: 2, label: 'Near',      range: '1-3m',  color: '#00d4ff', minRssi: BLE_RINGS.NEAR,      devices: [] },
      { id: 3, label: 'Far',       range: '3-10m', color: '#ffa502', minRssi: BLE_RINGS.FAR,       devices: [] },
      { id: 4, label: 'Remote',    range: '>10m',  color: '#ff4757', minRssi: -Infinity,            devices: [] }
    ];

    var deviceResults = [];

    for (var i = 0; i < btDevices.length; i++) {
      var bt = btDevices[i];
      var rssi = bt.rssi_dbm;
      var txPow = (typeof bt.tx_power === 'number') ? bt.tx_power : -12;
      var est = estimateDistance(rssi, txPow, PATH_LOSS.INDOOR, 'unknown');

      var ringId;
      if (rssi > BLE_RINGS.IMMEDIATE)    ringId = 1;
      else if (rssi > BLE_RINGS.NEAR)    ringId = 2;
      else if (rssi > BLE_RINGS.FAR)     ringId = 3;
      else                               ringId = 4;

      var deviceEntry = {
        mac_address:  bt.mac_address,
        device_name:  bt.device_name,
        device_type:  bt.device_type,
        manufacturer: bt.manufacturer,
        rssi:         rssi,
        tx_power:     txPow,
        ring_id:      ringId,
        ring_label:   rings[ringId - 1].label,
        ring_color:   rings[ringId - 1].color,
        distance_m:   est.distance_m,
        is_connectable: bt.is_connectable,
        service_uuids:  bt.service_uuids || []
      };

      rings[ringId - 1].devices.push(deviceEntry);
      deviceResults.push(deviceEntry);
    }

    // Compute angle offsets within each ring for even spacing
    for (var r = 0; r < rings.length; r++) {
      var ringDevices = rings[r].devices;
      if (ringDevices.length === 0) continue;
      var angleStep = 360 / ringDevices.length;
      for (var d = 0; d < ringDevices.length; d++) {
        ringDevices[d].angle_deg = angleStep * d;
        ringDevices[d].angle_rad = degToRad(angleStep * d - 90);
      }
    }

    return {
      rings:   rings,
      devices: deviceResults,
      counts: {
        immediate: rings[0].devices.length,
        near:      rings[1].devices.length,
        far:       rings[2].devices.length,
        remote:    rings[3].devices.length,
        total:     btDevices.length
      }
    };
  }

  // ─────────────────────────────────────────────────────────────
  // 6. DEVICE RISK HEATMAP GENERATOR
  // ─────────────────────────────────────────────────────────────

  /**
   * Generate a 2D risk-intensity grid.  Each WiFi device contributes a
   * Gaussian "hot spot" at its estimated position.  The result is a
   * canvas-ready RGBA colour matrix.
   *
   * Device positions are synthesised from channel+RSSI since we only
   * have distance estimates (no true bearing).  We spread devices in a
   * deterministic pattern seeded by their MAC address.
   *
   * @param {object} data       - Parsed data.json root
   * @param {number} [gridSize] - Output resolution (default 50x50)
   * @param {number} [sigma]    - Gaussian kernel sigma in grid cells (default 4)
   * @returns {{ grid: Array<Array<number>>, colorMatrix: Array<Array<{r,g,b,a}>>,
   *             width: number, height: number, maxRisk: number }}
   */
  function generateRiskHeatmap(data, gridSize, sigma) {
    gridSize = gridSize || 50;
    sigma    = sigma || 4;

    var devices = data.devices || [];
    var grid = [];
    for (var gy = 0; gy < gridSize; gy++) {
      var row = [];
      for (var gx = 0; gx < gridSize; gx++) row.push(0);
      grid.push(row);
    }

    // Simple MAC-seeded hash for deterministic position
    function macToSeed(mac) {
      var hash = 0;
      for (var ci = 0; ci < mac.length; ci++) {
        hash = ((hash << 5) - hash + mac.charCodeAt(ci)) | 0;
      }
      return Math.abs(hash);
    }

    // Place each device and apply Gaussian influence
    var twoSigmaSq = 2 * sigma * sigma;
    var kernelRadius = Math.ceil(sigma * 3);

    for (var i = 0; i < devices.length; i++) {
      var d = devices[i];
      var risk = d.risk_score || 0;
      if (risk < 0.01) continue; // skip negligible-risk devices

      var est = estimateDistance(d.rssi_dbm, null, null, d.device_type);

      // Synthesise position: distance from center + MAC-seeded angle
      var seed = macToSeed(d.mac_address);
      var angle = ((seed % 360) / 360) * 2 * Math.PI;
      var normDist = clamp(est.distance_m / 30, 0, 0.9); // normalise to grid
      var cx = Math.round((0.5 + Math.cos(angle) * normDist * 0.4) * (gridSize - 1));
      var cy = Math.round((0.5 + Math.sin(angle) * normDist * 0.4) * (gridSize - 1));
      cx = clamp(cx, 0, gridSize - 1);
      cy = clamp(cy, 0, gridSize - 1);

      // Gaussian splat
      var yStart = Math.max(0, cy - kernelRadius);
      var yEnd   = Math.min(gridSize - 1, cy + kernelRadius);
      var xStart = Math.max(0, cx - kernelRadius);
      var xEnd   = Math.min(gridSize - 1, cx + kernelRadius);

      for (var py = yStart; py <= yEnd; py++) {
        for (var px = xStart; px <= xEnd; px++) {
          var dx = px - cx;
          var dy = py - cy;
          var distSq = dx * dx + dy * dy;
          var weight = Math.exp(-distSq / twoSigmaSq);
          grid[py][px] += risk * weight;
        }
      }
    }

    // Find max for normalisation
    var maxRisk = 0;
    for (var ny = 0; ny < gridSize; ny++) {
      for (var nx = 0; nx < gridSize; nx++) {
        if (grid[ny][nx] > maxRisk) maxRisk = grid[ny][nx];
      }
    }

    // Convert to colour matrix
    var colorMatrix = [];
    for (var cy2 = 0; cy2 < gridSize; cy2++) {
      var colorRow = [];
      for (var cx2 = 0; cx2 < gridSize; cx2++) {
        var val = maxRisk > 0 ? grid[cy2][cx2] / maxRisk : 0;
        colorRow.push(_riskValueToColor(val));
      }
      colorMatrix.push(colorRow);
    }

    return {
      grid:        grid,
      colorMatrix: colorMatrix,
      width:       gridSize,
      height:      gridSize,
      maxRisk:     Math.round(maxRisk * 100) / 100
    };
  }

  /**
   * Map normalised risk [0..1] to an RGBA colour.
   *   0.0 = transparent
   *   0.0-0.3 = green (safe)
   *   0.3-0.6 = amber (caution)
   *   0.6-1.0 = red   (danger)
   * @private
   */
  function _riskValueToColor(val) {
    var alpha = clamp(val * 1.2, 0, 0.85);
    var r, g, b;
    if (val < 0.3) {
      // green to yellow
      var t = val / 0.3;
      r = Math.round(lerp(46, 255, t));
      g = Math.round(lerp(213, 165, t));
      b = Math.round(lerp(115, 2, t));
    } else if (val < 0.6) {
      // yellow to orange
      var t2 = (val - 0.3) / 0.3;
      r = 255;
      g = Math.round(lerp(165, 99, t2));
      b = Math.round(lerp(2, 72, t2));
    } else {
      // orange to red
      var t3 = (val - 0.6) / 0.4;
      r = 255;
      g = Math.round(lerp(99, 71, t3));
      b = Math.round(lerp(72, 87, t3));
    }
    return { r: r, g: g, b: b, a: alpha };
  }

  /**
   * Render the risk heatmap colour matrix directly to a canvas ImageData.
   * Call this inside your requestAnimationFrame loop.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {{ colorMatrix: Array, width: number, height: number }} heatmapData
   * @param {number} canvasWidth  - Output pixel width
   * @param {number} canvasHeight - Output pixel height
   */
  function renderRiskHeatmapToCanvas(ctx, heatmapData, canvasWidth, canvasHeight) {
    var cm = heatmapData.colorMatrix;
    var gw = heatmapData.width;
    var gh = heatmapData.height;

    var cellW = canvasWidth / gw;
    var cellH = canvasHeight / gh;

    for (var y = 0; y < gh; y++) {
      for (var x = 0; x < gw; x++) {
        var c = cm[y][x];
        if (c.a < 0.01) continue;
        ctx.fillStyle = 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + c.a.toFixed(2) + ')';
        ctx.fillRect(x * cellW, y * cellH, cellW + 0.5, cellH + 0.5);
      }
    }
  }

  // ─────────────────────────────────────────────────────────────
  // 7. SIGNAL TREND SIMULATOR (LIVE FEEL)
  // ─────────────────────────────────────────────────────────────

  /**
   * Create a signal fluctuation simulator that produces realistic RSSI
   * jitter and channel-scan sweep data.
   *
   * Usage:
   *   var sim = SignalProcessing.createSignalSimulator(data);
   *   requestAnimationFrame(function loop(ts) {
   *     var frame = sim.tick(ts);
   *     // frame.devices[i].rssi is the jittered value
   *     // frame.scanAngle is 0..360 sweep position
   *     requestAnimationFrame(loop);
   *   });
   *
   * @param {object} data - Parsed data.json root
   * @param {object} [opts]
   * @param {number} [opts.jitterStdDev]    - RSSI noise std dev (default 3)
   * @param {number} [opts.scanPeriodMs]    - Full sweep period (default 4000)
   * @param {number} [opts.smoothingAlpha]  - EMA smoothing 0..1 (default 0.15)
   * @returns {{ tick: function, reset: function }}
   */
  function createSignalSimulator(data, opts) {
    opts = opts || {};
    var jitterStd    = opts.jitterStdDev   || 3;
    var scanPeriod   = opts.scanPeriodMs   || 4000;
    var alpha        = opts.smoothingAlpha  || 0.15;

    var wifiDevices = data.devices || [];
    var btDevices   = data.bluetooth_devices || [];

    // Internal smoothed RSSI state per device
    var wifiState = [];
    for (var i = 0; i < wifiDevices.length; i++) {
      wifiState.push({
        baseRssi:     wifiDevices[i].rssi_dbm,
        smoothedRssi: wifiDevices[i].rssi_dbm,
        currentRssi:  wifiDevices[i].rssi_dbm
      });
    }
    var btState = [];
    for (var j = 0; j < btDevices.length; j++) {
      btState.push({
        baseRssi:     btDevices[j].rssi_dbm,
        smoothedRssi: btDevices[j].rssi_dbm,
        currentRssi:  btDevices[j].rssi_dbm
      });
    }

    var startTime = null;
    var prevTime  = null;

    function tick(timestamp) {
      if (startTime === null) startTime = timestamp;
      if (prevTime === null)  prevTime  = timestamp;

      var elapsed = timestamp - startTime;
      var dt = timestamp - prevTime;
      prevTime = timestamp;

      // Channel scan sweep angle (0..360)
      var scanAngle = (elapsed % scanPeriod) / scanPeriod * 360;
      var scanPhase = (elapsed % scanPeriod) / scanPeriod; // 0..1

      // Jitter each device's RSSI with exponential moving average smoothing
      var wifiOut = [];
      for (var wi = 0; wi < wifiState.length; wi++) {
        var ws = wifiState[wi];
        var noise = gaussianRandom(0, jitterStd);
        var target = clamp(ws.baseRssi + noise, -100, -10);
        ws.smoothedRssi = ws.smoothedRssi + alpha * (target - ws.smoothedRssi);
        ws.currentRssi  = Math.round(ws.smoothedRssi);

        wifiOut.push({
          mac_address: wifiDevices[wi].mac_address,
          rssi:        ws.currentRssi,
          baseRssi:    ws.baseRssi,
          delta:       ws.currentRssi - ws.baseRssi,
          percentage:  rssiToPercent(ws.currentRssi)
        });
      }

      var btOut = [];
      for (var bi = 0; bi < btState.length; bi++) {
        var bs = btState[bi];
        var btNoise = gaussianRandom(0, jitterStd * 0.7); // BLE slightly less noisy
        var btTarget = clamp(bs.baseRssi + btNoise, -100, -10);
        bs.smoothedRssi = bs.smoothedRssi + alpha * (btTarget - bs.smoothedRssi);
        bs.currentRssi  = Math.round(bs.smoothedRssi);

        btOut.push({
          mac_address: btDevices[bi].mac_address,
          rssi:        bs.currentRssi,
          baseRssi:    bs.baseRssi,
          delta:       bs.currentRssi - bs.baseRssi,
          percentage:  rssiToPercent(bs.currentRssi)
        });
      }

      return {
        timestamp:     timestamp,
        elapsed_ms:    elapsed,
        dt_ms:         dt,
        scanAngle:     scanAngle,
        scanPhase:     scanPhase,
        wifiDevices:   wifiOut,
        btDevices:     btOut
      };
    }

    function reset() {
      startTime = null;
      prevTime  = null;
      for (var i = 0; i < wifiState.length; i++) {
        wifiState[i].smoothedRssi = wifiState[i].baseRssi;
        wifiState[i].currentRssi  = wifiState[i].baseRssi;
      }
      for (var j = 0; j < btState.length; j++) {
        btState[j].smoothedRssi = btState[j].baseRssi;
        btState[j].currentRssi  = btState[j].baseRssi;
      }
    }

    return { tick: tick, reset: reset };
  }

  // ─────────────────────────────────────────────────────────────
  // 8. ESP32 CSI WAVEFORM GENERATOR (FUTURE-READY PLACEHOLDER)
  // ─────────────────────────────────────────────────────────────

  /**
   * Generate synthetic CSI (Channel State Information) amplitude and phase
   * data mimicking an ESP32 802.11n HT-LTF capture across 64 subcarriers.
   *
   * This is a placeholder producing realistic-looking waveforms until the
   * real ESP32 CSI hardware is integrated.
   *
   * CSI model:
   *   - 64 OFDM subcarriers (-32 to +31), indices 0..63
   *   - Guard / null subcarriers at edges and DC have lower amplitude
   *   - Amplitude follows an indoor multipath Rayleigh fading profile
   *   - Phase rotation is quasi-linear with random perturbation
   *
   * @param {object} [opts]
   * @param {number} [opts.subcarrierCount] - Number of subcarriers (default 64)
   * @param {number} [opts.snrDb]           - Signal-to-noise ratio (default 25)
   * @param {number} [opts.timestamp]       - Current time for animation
   * @returns {{ subcarriers: Array<{index,freq_offset,amplitude,phase_rad,is_null}>,
   *             status: string, hardware: string, metadata: object }}
   */
  function generateCSIWaveform(opts) {
    opts = opts || {};
    var N     = opts.subcarrierCount || 64;
    var snrDb = opts.snrDb || 25;
    var ts    = opts.timestamp || 0;

    // Null / guard subcarrier indices for HT-LTF (0-based mapping of -32..+31)
    // Null: DC (index 32), guard edges (0..5, 59..63)
    var nullIndices = { 0:1, 1:1, 2:1, 3:1, 4:1, 5:1, 32:1, 59:1, 60:1, 61:1, 62:1, 63:1 };

    // Pilot subcarrier indices: 7,21,43,57 (mapped from standard -21,-7,7,21)
    var pilotIndices = { 11:1, 25:1, 39:1, 53:1 };

    var noisePower = Math.pow(10, -snrDb / 10);
    var subcarriers = [];

    // Time-varying slow fade for animation
    var timeFade = 0.15 * Math.sin(ts * 0.001) + 0.1 * Math.sin(ts * 0.0007 + 1.3);

    for (var i = 0; i < N; i++) {
      var freqOffset = i - (N / 2); // -32 to +31
      var isNull = !!nullIndices[i];
      var isPilot = !!pilotIndices[i];

      var amplitude, phase;

      if (isNull) {
        // Null subcarrier: near zero
        amplitude = Math.random() * 0.05;
        phase = Math.random() * 2 * Math.PI;
      } else {
        // Rayleigh-like amplitude with frequency-selective fading
        var baseAmp = 0.6 + 0.3 * Math.cos(freqOffset * 0.12 + timeFade * 2);
        // Add multipath notch (simulates a deep fade around a subcarrier)
        var notchCenter = 15 + 8 * Math.sin(ts * 0.0003);
        var notchDepth = Math.exp(-Math.pow(i - notchCenter, 2) / 18);
        baseAmp *= (1 - 0.5 * notchDepth);

        // Add Gaussian noise
        var noiseReal = gaussianRandom(0, Math.sqrt(noisePower / 2));
        var noiseImag = gaussianRandom(0, Math.sqrt(noisePower / 2));

        amplitude = clamp(baseAmp + noiseReal * 0.3, 0, 1.2);

        // Phase: quasi-linear rotation + perturbation
        var linearPhase = freqOffset * 0.15 + ts * 0.002;
        var phasePerturbation = gaussianRandom(0, 0.2);
        phase = linearPhase + phasePerturbation;
        // Wrap to [-pi, pi]
        phase = phase - 2 * Math.PI * Math.floor((phase + Math.PI) / (2 * Math.PI));

        if (isPilot) {
          // Pilots have known amplitudes (stronger, more stable)
          amplitude = clamp(0.85 + noiseReal * 0.1, 0.5, 1.1);
        }
      }

      subcarriers.push({
        index:       i,
        freq_offset: freqOffset,
        amplitude:   Math.round(amplitude * 1000) / 1000,
        phase_rad:   Math.round(phase * 1000) / 1000,
        phase_deg:   Math.round(phase * 180 / Math.PI * 10) / 10,
        is_null:     isNull,
        is_pilot:    isPilot
      });
    }

    return {
      subcarriers: subcarriers,
      status:      'ESP32 CSI - Awaiting Hardware',
      hardware:    'ESP32-S3 (Planned)',
      metadata: {
        subcarrier_count: N,
        snr_db:           snrDb,
        bandwidth_mhz:    20,
        guard_interval:   'short',
        spatial_streams:  1,
        timestamp_ms:     ts,
        note:             'Synthetic waveform for UI development. Replace with real CSI data when ESP32 array is connected.'
      }
    };
  }

  /**
   * Create an animated CSI waveform generator that evolves over time.
   *
   * @param {object} [opts] - Options passed to generateCSIWaveform
   * @returns {{ tick: function }}
   */
  function createCSIAnimator(opts) {
    opts = opts || {};

    function tick(timestamp) {
      opts.timestamp = timestamp;
      return generateCSIWaveform(opts);
    }

    return { tick: tick };
  }

  // ─────────────────────────────────────────────────────────────
  // UTILITY: Canvas Rendering Helpers
  // ─────────────────────────────────────────────────────────────

  /**
   * Draw a radar plot onto a canvas context.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {{ devices: Array, rings: Array, maxRadius: number }} radarData
   * @param {number} centerX - Canvas center X
   * @param {number} centerY - Canvas center Y
   * @param {object} [theme] - Colour overrides
   */
  function drawRadarPlot(ctx, radarData, centerX, centerY, theme) {
    theme = theme || {};
    var ringColor    = theme.ringColor    || 'rgba(30,45,74,0.6)';
    var ringTextColor = theme.ringTextColor || 'rgba(136,146,164,0.8)';
    var labelColor   = theme.labelColor   || '#e8eaed';
    var crossColor   = theme.crossColor   || 'rgba(30,45,74,0.3)';

    // Draw crosshairs
    ctx.strokeStyle = crossColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(centerX - radarData.maxRadius, centerY);
    ctx.lineTo(centerX + radarData.maxRadius, centerY);
    ctx.moveTo(centerX, centerY - radarData.maxRadius);
    ctx.lineTo(centerX, centerY + radarData.maxRadius);
    ctx.stroke();

    // Draw range rings
    for (var ri = 0; ri < radarData.rings.length; ri++) {
      var ring = radarData.rings[ri];
      ctx.strokeStyle = ringColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(centerX, centerY, ring.radius_px, 0, 2 * Math.PI);
      ctx.stroke();

      // Ring label
      ctx.font = '10px system-ui, sans-serif';
      ctx.fillStyle = ringTextColor;
      ctx.textAlign = 'left';
      ctx.fillText(ring.label, centerX + ring.radius_px + 4, centerY - 2);
    }

    // Band labels
    ctx.font = '11px system-ui, sans-serif';
    ctx.fillStyle = 'rgba(255,165,2,0.6)';
    ctx.textAlign = 'center';
    ctx.fillText('2.4 GHz', centerX - radarData.maxRadius * 0.6, centerY - radarData.maxRadius * 0.85);
    ctx.fillStyle = 'rgba(168,85,247,0.6)';
    ctx.fillText('5 GHz', centerX + radarData.maxRadius * 0.6, centerY - radarData.maxRadius * 0.85);
    ctx.fillStyle = 'rgba(59,130,246,0.6)';
    ctx.fillText('BLE', centerX, centerY + radarData.maxRadius * 0.92);

    // Draw devices
    for (var di = 0; di < radarData.devices.length; di++) {
      var dev = radarData.devices[di];
      var px = centerX + dev.x;
      var py = centerY + dev.y;

      // Glow
      ctx.beginPath();
      ctx.arc(px, py, dev.size + 4, 0, 2 * Math.PI);
      ctx.fillStyle = 'rgba(' + dev.color.r + ',' + dev.color.g + ',' + dev.color.b + ',0.15)';
      ctx.fill();

      // Device dot
      ctx.beginPath();
      ctx.arc(px, py, dev.size, 0, 2 * Math.PI);
      ctx.fillStyle = dev.color.hex;
      ctx.fill();

      // Outline for high-risk
      if (dev.risk_score > 0.6) {
        ctx.strokeStyle = 'rgba(255,71,87,0.8)';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Label (only for devices large enough)
      if (dev.size >= 7) {
        ctx.font = '9px monospace';
        ctx.fillStyle = labelColor;
        ctx.textAlign = 'center';
        ctx.fillText(dev.label, px, py - dev.size - 4);
      }
    }
  }

  /**
   * Draw a single arc-gauge for signal strength.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {object} gaugeItem    - Single item from generateGaugeData()
   * @param {number} cx           - Center X
   * @param {number} cy           - Center Y
   * @param {number} radius       - Gauge radius in pixels
   * @param {number} [lineWidth]  - Arc thickness (default 8)
   */
  function drawSignalGauge(ctx, gaugeItem, cx, cy, radius, lineWidth) {
    lineWidth = lineWidth || 8;

    var startRad = degToRad(gaugeItem.arc_start);
    var endRad   = degToRad(gaugeItem.arc_end);
    var spanRad  = degToRad(gaugeItem.arc_start + gaugeItem.arc_span);

    // Background arc
    ctx.beginPath();
    ctx.arc(cx, cy, radius, startRad, spanRad);
    ctx.strokeStyle = 'rgba(30,45,74,0.5)';
    ctx.lineWidth = lineWidth;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Value arc
    if (gaugeItem.percentage > 0) {
      ctx.beginPath();
      ctx.arc(cx, cy, radius, startRad, endRad);
      ctx.strokeStyle = gaugeItem.color;
      ctx.lineWidth = lineWidth;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    // Centre text: percentage
    ctx.font = 'bold 14px monospace';
    ctx.fillStyle = gaugeItem.color;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(gaugeItem.percentage + '%', cx, cy - 4);

    // Quality label
    ctx.font = '9px system-ui, sans-serif';
    ctx.fillStyle = 'rgba(136,146,164,0.9)';
    ctx.fillText(gaugeItem.quality, cx, cy + 10);

    // RSSI value
    ctx.font = '8px monospace';
    ctx.fillStyle = 'rgba(74,85,104,0.9)';
    ctx.fillText(gaugeItem.rssi + ' dBm', cx, cy + 22);
  }

  /**
   * Draw a channel utilisation bar chart onto a canvas.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {Array} channelData   - band_24_active or band_5_active from analyzeChannelUtilization()
   * @param {number} x            - Left edge
   * @param {number} y            - Top edge
   * @param {number} width        - Available width
   * @param {number} height       - Available height
   * @param {string} [bandLabel]  - Band label text
   */
  function drawChannelBars(ctx, channelData, x, y, width, height, bandLabel) {
    if (channelData.length === 0) return;

    var barPadding = 3;
    var barWidth = Math.max(8, (width - barPadding * (channelData.length + 1)) / channelData.length);
    var maxBarHeight = height - 30; // leave room for labels

    // Band label
    if (bandLabel) {
      ctx.font = '11px system-ui, sans-serif';
      ctx.fillStyle = 'rgba(136,146,164,0.8)';
      ctx.textAlign = 'left';
      ctx.fillText(bandLabel, x, y + 12);
    }

    var barY = y + 20;

    for (var i = 0; i < channelData.length; i++) {
      var ch = channelData[i];
      var bx = x + barPadding + i * (barWidth + barPadding);
      var barH = ch.congestion * maxBarHeight;

      // Bar background
      ctx.fillStyle = 'rgba(30,45,74,0.3)';
      ctx.fillRect(bx, barY, barWidth, maxBarHeight);

      // Congestion bar
      ctx.fillStyle = ch.color;
      ctx.fillRect(bx, barY + maxBarHeight - barH, barWidth, barH);

      // Device count overlay
      if (ch.device_count > 0) {
        ctx.font = '9px monospace';
        ctx.fillStyle = '#e8eaed';
        ctx.textAlign = 'center';
        ctx.fillText(ch.device_count.toString(), bx + barWidth / 2, barY + maxBarHeight - barH - 4);
      }

      // Channel label
      ctx.font = '8px monospace';
      ctx.fillStyle = 'rgba(136,146,164,0.7)';
      ctx.textAlign = 'center';
      ctx.fillText('Ch' + ch.channel, bx + barWidth / 2, barY + maxBarHeight + 12);
    }
  }

  /**
   * Draw the BLE proximity rings onto a canvas.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {{ rings: Array, devices: Array }} bleData - From calculateBleProximityRings()
   * @param {number} cx - Center X
   * @param {number} cy - Center Y
   * @param {number} maxR - Maximum ring radius in pixels
   */
  function drawBleProximityRings(ctx, bleData, cx, cy, maxR) {
    var ringRadii = [maxR * 0.25, maxR * 0.5, maxR * 0.75, maxR];

    for (var ri = 0; ri < bleData.rings.length; ri++) {
      var ring = bleData.rings[ri];
      var r = ringRadii[ri];

      // Ring circle
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, 2 * Math.PI);
      ctx.strokeStyle = ring.color;
      ctx.lineWidth = 1;
      ctx.globalAlpha = 0.3;
      ctx.stroke();
      ctx.globalAlpha = 1;

      // Ring label
      ctx.font = '9px system-ui, sans-serif';
      ctx.fillStyle = ring.color;
      ctx.textAlign = 'right';
      ctx.fillText(ring.label + ' ' + ring.range, cx + r - 4, cy - r + 14);

      // Devices in this ring
      for (var di = 0; di < ring.devices.length; di++) {
        var dev = ring.devices[di];
        var devR = r * 0.8; // Place slightly inside the ring
        var devX = cx + Math.cos(dev.angle_rad) * devR;
        var devY = cy + Math.sin(dev.angle_rad) * devR;

        // Dot
        ctx.beginPath();
        ctx.arc(devX, devY, 5, 0, 2 * Math.PI);
        ctx.fillStyle = ring.color;
        ctx.fill();

        // Label
        ctx.font = '8px monospace';
        ctx.fillStyle = '#e8eaed';
        ctx.textAlign = 'center';
        ctx.fillText(dev.device_name, devX, devY - 9);
      }
    }
  }

  /**
   * Draw synthetic CSI waveform (amplitude + phase).
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {object} csiData - From generateCSIWaveform()
   * @param {number} x       - Left edge
   * @param {number} y       - Top edge
   * @param {number} width   - Available width
   * @param {number} height  - Available height
   */
  function drawCSIWaveform(ctx, csiData, x, y, width, height) {
    var subs = csiData.subcarriers;
    var halfH = height / 2;
    var ampY = y;
    var phaseY = y + halfH;

    // Step width per subcarrier
    var step = width / (subs.length - 1);

    // --- Amplitude plot ---
    ctx.font = '10px system-ui, sans-serif';
    ctx.fillStyle = 'rgba(136,146,164,0.6)';
    ctx.textAlign = 'left';
    ctx.fillText('CSI Amplitude (64 subcarriers)', x + 4, ampY + 14);

    // Status label
    ctx.font = '9px monospace';
    ctx.fillStyle = 'rgba(255,165,2,0.8)';
    ctx.textAlign = 'right';
    ctx.fillText(csiData.status, x + width - 4, ampY + 14);

    // Amplitude waveform
    ctx.beginPath();
    for (var i = 0; i < subs.length; i++) {
      var sx = x + i * step;
      var ampHeight = subs[i].amplitude * (halfH - 24);
      var sy = ampY + halfH - 4 - ampHeight;
      if (i === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    }
    ctx.strokeStyle = '#00d4ff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Fill under amplitude
    ctx.lineTo(x + (subs.length - 1) * step, ampY + halfH - 4);
    ctx.lineTo(x, ampY + halfH - 4);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0,212,255,0.08)';
    ctx.fill();

    // Highlight null subcarriers
    for (var ni = 0; ni < subs.length; ni++) {
      if (subs[ni].is_null) {
        var nx = x + ni * step;
        ctx.fillStyle = 'rgba(255,71,87,0.15)';
        ctx.fillRect(nx - step * 0.4, ampY + 20, step * 0.8, halfH - 24);
      }
      if (subs[ni].is_pilot) {
        var px = x + ni * step;
        ctx.fillStyle = 'rgba(46,213,115,0.3)';
        ctx.fillRect(px - 1, ampY + 20, 2, halfH - 24);
      }
    }

    // --- Phase plot ---
    ctx.font = '10px system-ui, sans-serif';
    ctx.fillStyle = 'rgba(136,146,164,0.6)';
    ctx.textAlign = 'left';
    ctx.fillText('Phase Rotation', x + 4, phaseY + 14);

    // Zero line
    ctx.strokeStyle = 'rgba(30,45,74,0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, phaseY + halfH / 2);
    ctx.lineTo(x + width, phaseY + halfH / 2);
    ctx.stroke();

    // Phase waveform
    ctx.beginPath();
    for (var pi = 0; pi < subs.length; pi++) {
      var psx = x + pi * step;
      // Map phase [-pi..pi] to [top..bottom]
      var phaseNorm = (subs[pi].phase_rad + Math.PI) / (2 * Math.PI);
      var psy = phaseY + 20 + phaseNorm * (halfH - 28);
      if (pi === 0) ctx.moveTo(psx, psy);
      else ctx.lineTo(psx, psy);
    }
    ctx.strokeStyle = '#a855f7';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // ─────────────────────────────────────────────────────────────
  // UTILITY: Scan Sweep Overlay
  // ─────────────────────────────────────────────────────────────

  /**
   * Draw a rotating scan-line over a radar plot for live feel.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {number} cx         - Center X
   * @param {number} cy         - Center Y
   * @param {number} radius     - Sweep radius
   * @param {number} angleDeg   - Current sweep angle (0..360)
   * @param {string} [color]    - Sweep line colour
   */
  function drawScanSweep(ctx, cx, cy, radius, angleDeg, color) {
    color = color || 'rgba(0,212,255,0.6)';
    var angleRad = degToRad(angleDeg - 90);

    // Trailing fan (faded arc behind sweep line)
    var fanSpan = degToRad(30);
    var gradient = ctx.createConicGradient(angleRad - fanSpan, cx, cy);
    gradient.addColorStop(0, 'rgba(0,212,255,0)');
    gradient.addColorStop(0.8, 'rgba(0,212,255,0.06)');
    gradient.addColorStop(1, 'rgba(0,212,255,0.12)');

    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, radius, angleRad - fanSpan, angleRad);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Sweep line
    var endX = cx + Math.cos(angleRad) * radius;
    var endY = cy + Math.sin(angleRad) * radius;

    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(endX, endY);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // ─────────────────────────────────────────────────────────────
  // PUBLIC API
  // ─────────────────────────────────────────────────────────────

  return {
    // Constants
    TX_POWER_DEFAULTS: TX_POWER_DEFAULTS,
    PATH_LOSS:         PATH_LOSS,
    BLE_RINGS:         BLE_RINGS,

    // Core algorithms
    estimateDistance:           estimateDistance,
    estimateAllDistances:      estimateAllDistances,
    generateRadarData:         generateRadarData,
    generateGaugeData:         generateGaugeData,
    analyzeChannelUtilization: analyzeChannelUtilization,
    calculateBleProximityRings: calculateBleProximityRings,
    generateRiskHeatmap:       generateRiskHeatmap,
    generateCSIWaveform:       generateCSIWaveform,

    // Animators / simulators
    createSignalSimulator:     createSignalSimulator,
    createCSIAnimator:         createCSIAnimator,

    // Canvas rendering helpers
    drawRadarPlot:             drawRadarPlot,
    drawSignalGauge:           drawSignalGauge,
    drawChannelBars:           drawChannelBars,
    drawBleProximityRings:     drawBleProximityRings,
    drawCSIWaveform:           drawCSIWaveform,
    drawScanSweep:             drawScanSweep,
    renderRiskHeatmapToCanvas: renderRiskHeatmapToCanvas,

    // Utility
    rssiToPercent:             rssiToPercent,
    clamp:                     clamp,
    lerp:                      lerp,
    degToRad:                  degToRad
  };

})();
