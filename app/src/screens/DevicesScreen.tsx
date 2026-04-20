import React, { useMemo } from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
} from 'react-native';
import { useStore } from '../store';
import { useDevices } from '../hooks/useDevices';
import { DeviceCard } from '../components/DeviceCard';
import type { Device } from '../types';

function getDeviceIcon(deviceType: Device['device_type']): string {
  switch (deviceType) {
    case 'phone':
      return '📱';
    case 'laptop':
      return '💻';
    case 'iot':
      return '🔌';
    case 'ap':
      return '📡';
    default:
      return '❓';
  }
}

function getRiskBadgeColor(riskScore: number): string {
  if (riskScore >= 0.6) return '#ff4757';
  if (riskScore >= 0.3) return '#ffa502';
  return '#2ed573';
}

function getSignalBars(rssi: number): string {
  if (rssi >= -50) return '▂▄▆█';
  if (rssi >= -60) return '▂▄▆░';
  if (rssi >= -70) return '▂▄░░';
  if (rssi >= -80) return '▂░░░';
  return '░░░░';
}

export function DevicesScreen() {
  const currentSession = useStore((s) => s.currentSession);
  const sessionId = currentSession?.session_id ?? null;
  const { devices, rogueDevices, totalCount } = useDevices(sessionId);

  const renderDevice = useMemo(
    () =>
      ({ item }: { item: Device }) => (
        <DeviceCard
          device={item}
          icon={getDeviceIcon(item.device_type)}
          signalBars={getSignalBars(item.rssi_dbm)}
          riskColor={getRiskBadgeColor(item.risk_score)}
          showRiskBadge={item.risk_score >= 0.6}
        />
      ),
    [],
  );

  const keyExtractor = (item: Device) => item.mac_address;

  const ListHeader = () => (
    <View style={styles.headerContainer}>
      <View style={styles.statRow}>
        <View style={styles.statCard}>
          <Text style={styles.statValue}>{totalCount}</Text>
          <Text style={styles.statLabel}>Total Devices</Text>
        </View>
        <View style={[styles.statCard, styles.statCardDanger]}>
          <Text style={[styles.statValue, styles.statValueDanger]}>
            {rogueDevices.length}
          </Text>
          <Text style={styles.statLabel}>Rogue Devices</Text>
        </View>
      </View>
    </View>
  );

  const ListEmpty = () => (
    <View style={styles.emptyState}>
      <Text style={styles.emptyIcon}>🔍</Text>
      <Text style={styles.emptyText}>No devices discovered yet</Text>
      <Text style={styles.emptySubtext}>
        Devices will appear as they are detected on the network
      </Text>
    </View>
  );

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Discovered Devices</Text>
      <FlatList
        data={devices}
        renderItem={renderDevice}
        keyExtractor={keyExtractor}
        ListHeaderComponent={ListHeader}
        ListEmptyComponent={ListEmpty}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0e17',
    padding: 16,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#e8eaed',
    marginBottom: 16,
  },
  headerContainer: {
    marginBottom: 16,
  },
  statRow: {
    flexDirection: 'row',
    gap: 12,
  },
  statCard: {
    flex: 1,
    backgroundColor: '#131a2b',
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#1e2a42',
  },
  statCardDanger: {
    borderColor: '#ff475733',
  },
  statValue: {
    fontSize: 28,
    fontWeight: '700',
    color: '#00d4ff',
  },
  statValueDanger: {
    color: '#ff4757',
  },
  statLabel: {
    fontSize: 12,
    color: '#6b7280',
    marginTop: 4,
  },
  listContent: {
    paddingBottom: 24,
  },
  separator: {
    height: 8,
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 64,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 16,
  },
  emptyText: {
    fontSize: 16,
    color: '#e8eaed',
    fontWeight: '600',
    marginBottom: 8,
  },
  emptySubtext: {
    fontSize: 13,
    color: '#6b7280',
    textAlign: 'center',
  },
});
