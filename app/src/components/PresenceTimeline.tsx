import React from 'react';
import { View, Text, StyleSheet, FlatList } from 'react-native';
import { PresenceEvent } from '../types';

interface PresenceTimelineProps {
  events: PresenceEvent[];
}

const EVENT_COLORS: Record<PresenceEvent['event_type'], string> = {
  entry: '#2ed573',
  exit: '#ff4757',
  moving: '#00d4ff',
  stationary: '#8892a4',
  empty: '#1e2a3a',
};

const EVENT_LABELS: Record<PresenceEvent['event_type'], string> = {
  entry: 'Entry',
  exit: 'Exit',
  moving: 'Moving',
  stationary: 'Stationary',
  empty: 'Empty',
};

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

const TimelineItem: React.FC<{ event: PresenceEvent; isLast: boolean }> = ({
  event,
  isLast,
}) => {
  const dotColor = EVENT_COLORS[event.event_type];

  return (
    <View style={styles.itemRow}>
      <View style={styles.timelineTrack}>
        <View style={[styles.dot, { backgroundColor: dotColor }]} />
        {!isLast && <View style={styles.line} />}
      </View>

      <View style={styles.itemContent}>
        <View style={styles.itemHeader}>
          <Text style={[styles.eventLabel, { color: dotColor }]}>
            {EVENT_LABELS[event.event_type]}
          </Text>
          <Text style={styles.timestamp}>{formatTimestamp(event.timestamp)}</Text>
        </View>
        <Text style={styles.zone}>{event.zone}</Text>
        <Text style={styles.confidence}>
          Confidence: {Math.round(event.confidence * 100)}%
        </Text>
      </View>
    </View>
  );
};

const PresenceTimeline: React.FC<PresenceTimelineProps> = ({ events }) => {
  const sortedEvents = [...events].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={sortedEvents}
        keyExtractor={(item) => item.event_id}
        renderItem={({ item, index }) => (
          <TimelineItem event={item} isLast={index === sortedEvents.length - 1} />
        )}
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0e17',
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  itemRow: {
    flexDirection: 'row',
    minHeight: 72,
  },
  timelineTrack: {
    width: 24,
    alignItems: 'center',
  },
  dot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    marginTop: 4,
  },
  line: {
    width: 2,
    flex: 1,
    backgroundColor: '#1e2a3a',
    marginTop: 4,
  },
  itemContent: {
    flex: 1,
    marginLeft: 12,
    paddingBottom: 16,
  },
  itemHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  eventLabel: {
    fontSize: 14,
    fontWeight: '600',
  },
  timestamp: {
    fontSize: 11,
    color: '#8892a4',
  },
  zone: {
    fontSize: 13,
    color: '#e8eaed',
    marginBottom: 2,
  },
  confidence: {
    fontSize: 11,
    color: '#8892a4',
  },
});

export default PresenceTimeline;
