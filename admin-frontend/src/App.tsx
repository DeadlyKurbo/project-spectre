import { Navigate, Route, Routes } from "react-router-dom";
import { PageShell } from "./components/PageShell";
import { AppealsPage } from "./pages/AppealsPage";
import { AuditPage } from "./pages/AuditPage";
import { CasesPage } from "./pages/CasesPage";
import { UsersPage } from "./pages/UsersPage";

export function App() {
  return (
    <PageShell>
      <Routes>
        <Route path="/" element={<Navigate to="/users" replace />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/appeals" element={<AppealsPage />} />
        <Route path="/audit" element={<AuditPage />} />
      </Routes>
    </PageShell>
  );
}
