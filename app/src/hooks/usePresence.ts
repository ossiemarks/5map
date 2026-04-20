import { useEffect } from 'react';
import { useStore } from '../store';
import { api } from '../services/api';
import { storage } from '../services/storage';

export function usePresence(sessionId: string | null) {
  const events = useStore((s) => s.events);
  const setEvents = useStore((s) => s.setEvents);

  useEffect(() => {
    if (!sessionId) return;

    (async () => {
      const cached = await storage.getPresence(sessionId);
      if (cached) setEvents(cached);

      const { data, error } = await api.getPresence(sessionId);
      if (data && !error) {
        setEvents(data);
        storage.setPresence(sessionId, data);
      }
    })();
  }, [sessionId]);

  const sortedEvents = [...events].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );

  const zones = [...new Set(events.map((e) => e.zone))];

  return { events: sortedEvents, zones, totalCount: events.length };
}
