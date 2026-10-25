import { Link, NavLink } from "react-router-dom";
import type { PropsWithChildren } from "react";

const tabs = [
  { to: "/users", label: "Users" },
  { to: "/cases", label: "Cases" },
  { to: "/appeals", label: "Appeals" },
  { to: "/audit", label: "Audit" }
];

export function PageShell({ children }: PropsWithChildren) {
  return (
    <div className="shell">
      <header className="header">
        <div>
          <h1>Spectre Moderation Console</h1>
          <p>Cross-surface moderation for website + Discord.</p>
        </div>
        <Link className="header-link" to="/users">
          Open User Search
        </Link>
      </header>
      <nav className="tabs">
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) => (isActive ? "tab active" : "tab")}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <main>{children}</main>
    </div>
  );
}
