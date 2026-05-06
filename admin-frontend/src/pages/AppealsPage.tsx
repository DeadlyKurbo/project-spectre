import { useEffect, useState } from "react";
import { moderationFetch } from "../api";

type AppealRow = {
  id: string;
  sanctionId: string;
  status: string;
  appealReason: string;
};

export function AppealsPage() {
  const [appeals, setAppeals] = useState<AppealRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    moderationFetch<{ appeals: AppealRow[] }>("/appeals")
      .then((data) => setAppeals(data.appeals))
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <section className="panel">
      <h2>Appeals Queue</h2>
      <p>Review sanction disputes and issue decisions with notes.</p>
      {error ? <p className="error">{error}</p> : null}
      <ul className="list">
        {appeals.map((appeal) => (
          <li key={appeal.id}>
            <strong>{appeal.status}</strong>
            <span>{appeal.appealReason}</span>
            <small>Sanction: {appeal.sanctionId}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}
