import { useEffect, useState } from "react";

type ServiceStatus = { ok: boolean; [key: string]: unknown };
type Health = Record<string, ServiceStatus>;

// Status page: shows whether backend, database, QGIS and the LLM proxy are running.
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ping, setPing] = useState<ServiceStatus | null>(null);
  const [pinging, setPinging] = useState(false);

  // Services may still be starting, so check again every 5 s until all are up.
  useEffect(() => {
    let timer: number | undefined;
    const check = () => {
      fetch("/api/health")
        .then((r) => r.json())
        .then((h: Health) => {
          setHealth(h);
          setError(null);
          if (!Object.values(h).every((s) => s.ok)) timer = window.setTimeout(check, 5000);
        })
        .catch((e) => {
          setError(String(e));
          timer = window.setTimeout(check, 5000);
        });
    };
    check();
    return () => window.clearTimeout(timer);
  }, []);

  // Calls a real model once; costs a few tokens, so only on click.
  const pingLlm = () => {
    setPinging(true);
    fetch("/api/llm-ping")
      .then((r) => r.json())
      .then(setPing)
      .catch((e) => setPing({ ok: false, error: String(e) }))
      .finally(() => setPinging(false));
  };

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
      <section>
        <h2>LLM test</h2>
        <button onClick={pingLlm} disabled={pinging}>
          {pinging ? "Waiting for model …" : "Send test prompt"}
        </button>
        {ping && (
          <pre>
            {ping.ok ? "✅ " : "❌ "}
            {JSON.stringify(ping, null, 2)}
          </pre>
        )}
      </section>
    </main>
  );
}
