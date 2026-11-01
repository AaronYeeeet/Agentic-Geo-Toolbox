// Settings panel: model picker (from /api/models) plus agent parameters.
// Values are kept in localStorage, so they survive reloads and backend restarts.

const STORAGE_KEY = "geo-toolbox-settings";

export const DEFAULT_SETTINGS = { model: null, max_steps: null, temperature: null };

export function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* private mode etc.: settings just aren't remembered */
  }
}

function modelLabel(m) {
  const tags = [m.free === true ? "free" : m.free === false ? "paid" : null,
    m.context_length ? `${Math.round(m.context_length / 1000)}k` : null,
    m.available ? null : "kein Key"].filter(Boolean);
  return `${m.name}${tags.length ? ` (${tags.join(", ")})` : ""}`;
}

export default function Settings({ models, settings, health, onChange, onClose }) {
  const set = (patch) => onChange({ ...settings, ...patch });
  const providers = [...new Set(models.map((m) => m.provider))];
  const selected = models.find((m) => m.id === (settings.model || health?.model));
  const isClaude = (selected?.id || "").startsWith("anthropic/");

  return (
    <div className="settings">
      <div className="settings-head">
        <strong>Einstellungen</strong>
        <button className="link" onClick={onClose}>schließen</button>
      </div>

      <label>
        Modell
        <select value={settings.model || ""} onChange={(e) => set({ model: e.target.value || null })}>
          <option value="">Standard aus .env ({health?.model || "…"})</option>
          {providers.map((p) => (
            <optgroup key={p} label={p}>
              {models.filter((m) => m.provider === p).map((m) => (
                <option key={m.id} value={m.id} disabled={!m.available}>{modelLabel(m)}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {selected && (
        <div className="settings-note">
          <code>{selected.id}</code>
          {selected.note && <> · {selected.note}</>}
          {!selected.available && (
            <> · fehlt in <code>backend/.env</code>: {selected.missing_keys.join(" oder ")}</>
          )}
        </div>
      )}

      <label>
        Max. Schritte pro Anfrage
        <input type="number" min="1" max="30" placeholder={String(health?.max_steps ?? 12)}
          value={settings.max_steps ?? ""}
          onChange={(e) => set({ max_steps: e.target.value ? Number(e.target.value) : null })} />
      </label>

      <label>
        Temperatur {isClaude && <span className="settings-note">(von Claude ignoriert)</span>}
        <input type="number" min="0" max="2" step="0.1" placeholder="0"
          value={settings.temperature ?? ""} disabled={isClaude}
          onChange={(e) => set({ temperature: e.target.value ? Number(e.target.value) : null })} />
      </label>

      <button className="link" onClick={() => onChange(DEFAULT_SETTINGS)}>zurücksetzen</button>
    </div>
  );
}
