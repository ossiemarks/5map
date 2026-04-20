import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Device } from '../types';

interface DeviceCardProps {
  device: Device;
}

const DEVICE_ICONS: Record<Device['device_type'], string> = {
  phone: '📱',
  laptop: '💻',
  iot: '🏠',
  ap: '📡',
  unknown: '❓',
};

function getRiskBadge(score: number): { label: string; color: string } {
  if (score >= 0.6) return { label: 'HIGH', color: '#ff4757' };
  if (score >= 0.3) return { label: 'MED', color: '#ffa502' };
  return { label: 'LOW', color: '#2ed573' };
}

function rssiToPercent(rssi: number): number {
  const clamped = Math.max(-100, Math.min(-30, rssi));
  return ((clamped + 100) / 70) * 100;
}

function rssiBarColor(rssi: number): string {
  if (rssi >= -50) return '#2ed573';
  if (rssi >= -70) return '#ffa502';
  return '#ff4757';
}

const DeviceCard: React.FC<DeviceCardProps> = ({ device }) => {
  const icon = DEVICE_ICONS[device.device_type];
  const risk = getRiskBadge(device.risk_score);
  const signalPercent = rssiToPercent(device.rssi_dbm);
  const barColor = rssiBarColor(device.rssi_dbm);

  return (
    <View style={styles.card}>
      <View style={styles.iconContainer}>
        <Text style={styles.icon}>{icon}</Text>
      </View>

      <View style={styles.infoContainer}>
        <Text style={styles.mac}>{device.mac_address}</Text>
        <Text style={styles.vendor}>
          {device.vendor ?? 'Unknown vendor'}
        </Text>

        <View style={styles.signalRow}>
          <Text style={styles.rssiText}>{device.rssi_dbm} dBm</Text>
          <View style={styles.signalBarBg}>
            <View
              style={[
                styles.signalBarFill,
                { width: `${signalPercent}%`, backgroundColor: barColor },
              ]}
            />
          </View>
        </View>

        <Text style={styles.channel}>Ch {device.channel ?? '—'}</Text>
      </View>

      <View style={[styles.riskBadge, { backgroundColor: risk.color }]}>
        <Text style={styles.riskText}>{risk.label}</Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#131a2b',
    borderRadius: 12,
    padding: 14,
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: 6,
    marginHorizontal: 12,
  },
  iconContainer: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#0a0e17',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  icon: {
    fontSize: 22,
  },
  infoContainer: {
    flex: 1,
  },
  mac: {
    fontFamily: 'monospace',
    fontSize: 13,
    color: '#e8eaed',
    marginBottom: 2,
  },
  vendor: {
    fontSize: 12,
    color: '#8892a4',
    marginBottom: 6,
  },
  signalRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  rssiText: {
    fontSize: 11,
    color: '#8892a4',
    width: 60,
  },
  signalBarBg: {
    flex: 1,
    height: 6,
    backgroundColor: '#0a0e17',
    borderRadius: 3,
    overflow: 'hidden',
  },
  signalBarFill: {
    height: '100%',
    borderRadius: 3,
  },
  channel: {
    fontSize: 11,
    color: '#8892a4',
  },
  riskBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    marginLeft: 10,
  },
  riskText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#ffffff',
  },
});

export default DeviceCard;
