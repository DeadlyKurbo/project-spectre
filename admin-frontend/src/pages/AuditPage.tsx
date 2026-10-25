import { useEffect, useState } from "react";
import { moderationFetch } from "../api";

type AuditEvent = {
  id: string;
  eventType: string;
  source: string;
  occurredAt: string;
};

export function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    moderationFetch<{ events: AuditEvent[] }>("/audit-events?limit=100")
      .then((data) => setEvents(data.events))
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <section className="panel">
      <h2>Audit Timeline</h2>
      <p>Immutable moderation event stream with retention controls.</p>
      {error ? <p className="error">{error}</p> : null}
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Type</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id}>
              <td>{new Date(event.occurredAt).toLocaleString()}</td>
              <td>{event.eventType}</td>
              <td>{event.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
