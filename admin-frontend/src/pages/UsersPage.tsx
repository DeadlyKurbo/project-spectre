import { useEffect, useState } from "react";
import { moderationFetch } from "../api";

type Subject = {
  id: string;
  canonicalLabel: string;
  status: string;
};

export function UsersPage() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [newLabel, setNewLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    moderationFetch<{ subjects: Subject[] }>("/subjects")
      .then((data) => setSubjects(data.subjects))
      .catch((err: Error) => setError(err.message));
  }, []);

  async function createSubject() {
    setError(null);
    const payload = await moderationFetch<{ subject: Subject }>("/subjects", {
      method: "POST",
      body: JSON.stringify({ canonicalLabel: newLabel })
    });
    setSubjects((prev) => [payload.subject, ...prev]);
    setNewLabel("");
  }

  return (
    <section className="panel">
      <h2>Unified User Profiles</h2>
      <p>Create and review cross-surface moderated subjects.</p>
      <div className="row">
        <input
          placeholder="Canonical subject label"
          value={newLabel}
          onChange={(event) => setNewLabel(event.target.value)}
        />
        <button onClick={createSubject} disabled={newLabel.trim().length < 2}>
          Add
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <ul className="list">
        {subjects.map((subject) => (
          <li key={subject.id}>
            <strong>{subject.canonicalLabel}</strong>
            <span>{subject.status}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
