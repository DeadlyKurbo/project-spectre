import { useEffect, useState } from "react";
import { moderationFetch } from "../api";

type CaseRow = {
  id: string;
  subjectId: string;
  title: string;
  priority: string;
  status: string;
};

export function CasesPage() {
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    moderationFetch<{ cases: CaseRow[] }>("/cases")
      .then((data) => setCases(data.cases))
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <section className="panel">
      <h2>Case Management</h2>
      <p>Investigations, assignees, and status tracking.</p>
      {error ? <p className="error">{error}</p> : null}
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>Subject</th>
            <th>Priority</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((item) => (
            <tr key={item.id}>
              <td>{item.title}</td>
              <td>{item.subjectId}</td>
              <td>{item.priority}</td>
              <td>{item.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
