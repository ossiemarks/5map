import React, { useState, useMemo } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ScrollView,
  StyleSheet,
} from 'react-native';
import { useStore } from '../store';
import { usePresence } from '../hooks/usePresence';
import { PresenceTimeline } from '../components/PresenceTimeline';
import type { PresenceEvent } from '../types';

function getEventIcon(eventType: PresenceEvent['event_type']): string {
  switch (eventType) {
    case 'entry':
      return '➡️';
    case 'exit':
      return '⬅️';
    case 'moving':
      return '🚶';
    case 'stationary':
      return '⏺️';
    case 'empty':
      return '⭕';
    default:
      return '⭕';
  }
}

function formatTimestamp(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function PresenceScreen() {
  const currentSession = useStore((s) => s.currentSession);
  const sessionId = currentSession?.session_id ?? null;
  const { events, zones, totalCount } = usePresence(sessionId);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);

  const filteredEvents = useMemo(() => {
    if (!selectedZone) return events;
    return events.filter((e) => e.zone === selectedZone);
  }, [events, selectedZone]);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Presence Events</Text>
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{totalCount}</Text>
        </View>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.filterContainer}
        contentContainerStyle={styles.filterContent}
      >
        <TouchableOpacity
          style={[
            styles.filterChip,
            !selectedZone && styles.filterChipActive,
          ]}
          onPress={() => setSelectedZone(null)}
          activeOpacity={0.7}
        >
          <Text
            style={[
              styles.filterChipText,
              !selectedZone && styles.filterChipTextActive,
            ]}
          >
            All Zones
          </Text>
        </TouchableOpacity>
        {zones.map((zone) => (
          <TouchableOpacity
            key={zone}
            style={[
              styles.filterChip,
              selectedZone === zone && styles.filterChipActive,
            ]}
            onPress={() => setSelectedZone(zone)}
            activeOpacity={0.7}
          >
            <Text
              style={[
                styles.filterChipText,
                selectedZone === zone && styles.filterChipTextActive,
              ]}
            >
              {zone}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {filteredEvents.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyIcon}>👁️</Text>
          <Text style={styles.emptyText}>No presence events recorded</Text>
          <Text style={styles.emptySubtext}>
            Events will appear as occupancy changes are detected
          </Text>
        </View>
      ) : (
        <PresenceTimeline
          events={filteredEvents}
          getEventIcon={getEventIcon}
          formatTimestamp={formatTimestamp}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0e17',
    padding: 16,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#e8eaed',
    flex: 1,
  },
  badge: {
    backgroundColor: '#131a2b',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1e2a42',
  },
  badgeText: {
    fontSize: 13,
    color: '#00d4ff',
    fontWeight: '600',
  },
  filterContainer: {
    maxHeight: 44,
    marginBottom: 16,
  },
  filterContent: {
    gap: 8,
    paddingRight: 16,
  },
  filterChip: {
    backgroundColor: '#131a2b',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#1e2a42',
  },
  filterChipActive: {
    backgroundColor: '#00d4ff22',
    borderColor: '#00d4ff',
  },
  filterChipText: {
    fontSize: 13,
    color: '#6b7280',
    fontWeight: '500',
  },
  filterChipTextActive: {
    color: '#00d4ff',
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
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
