import { useEffect, useState } from "react";

type ServiceStatus = { ok: boolean; [key: string]: unknown };
type Health = Record<string, ServiceStatus>;

// Status page: shows whether backend, database and QGIS are running.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 640, margin: "48px auto", padding: 16 }}>
      <h1>Geo-Agent</h1>
      {error && <p>Backend not reachable: {error}</p>}
      {!health && !error && <p>Checking services …</p>}
      {health &&
        Object.entries(health).map(([name, status]) => (
          <section key={name}>
            <h2>
              {status.ok ? "✅" : "❌"} {name}
            </h2>
            <pre>{JSON.stringify(status, null, 2)}</pre>
          </section>
        ))}
    </main>
  );
}
