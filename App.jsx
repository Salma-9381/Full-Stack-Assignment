import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ─── Tiny hook: fetch JSON ───────────────────────────────────────────────────
function useApi(path, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const fetch_ = useCallback(async () => {
    try {
      setLoading(true);
      const r = await fetch(`${API}${path}`);
      setData(await r.json());
    } catch (_) {}
    finally { setLoading(false); }
  }, [path]);
  useEffect(() => { fetch_(); }, deps);
  return { data, loading, refresh: fetch_ };
}

// ─── Colours ─────────────────────────────────────────────────────────────────
const C = {
  bg: "#0a0a0f",
  surface: "#111118",
  border: "#1e1e2e",
  accent: "#7c6af7",
  accentHover: "#9581ff",
  success: "#34d399",
  error: "#f87171",
  warn: "#fbbf24",
  text: "#e2e8f0",
  muted: "#64748b",
};

// ─── Sparkline (SVG) ─────────────────────────────────────────────────────────
function Sparkline({ data = [], color = C.accent, height = 40 }) {
  if (!data.length) return null;
  const w = 200, h = height, pad = 2;
  const vals = data.map(Number);
  const mn = Math.min(...vals), mx = Math.max(...vals) || 1;
  const pts = vals.map((v, i) => {
    const x = pad + (i / (vals.length - 1 || 1)) * (w - pad * 2);
    const y = h - pad - ((v - mn) / (mx - mn || 1)) * (h - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={w} height={h} style={{ overflow: "visible" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Stat card ───────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color = C.accent, spark }) {
  return (
    <div style={{
      background: C.surface, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: "20px 24px",
      display: "flex", flexDirection: "column", gap: 4,
      minWidth: 160, flex: 1,
    }}>
      <div style={{ color: C.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
      <div style={{ color, fontSize: 28, fontWeight: 700, fontFamily: "monospace" }}>{value}</div>
      {sub && <div style={{ color: C.muted, fontSize: 12 }}>{sub}</div>}
      {spark && <div style={{ marginTop: 8 }}><Sparkline data={spark} color={color} /></div>}
    </div>
  );
}

// ─── Dashboard Tab ───────────────────────────────────────────────────────────
function Dashboard() {
  const { data: overview, refresh: refOv } = useApi("/api/analytics/overview", []);
  const { data: latency } = useApi("/api/analytics/latency", []);
  const { data: errors } = useApi("/api/analytics/errors", []);
  const { data: throughput } = useApi("/api/analytics/throughput", []);
  const { data: logs } = useApi("/api/logs?limit=20", []);

  useEffect(() => { const t = setInterval(refOv, 5000); return () => clearInterval(t); }, []);

  const ov = overview || {};
  const latArr = (latency || []).map(d => d.avg_latency);
  const tpArr = (throughput || []).map(d => d.requests);
  const errArr = (errors || []).map(d => d.errors);

  return (
    <div style={{ padding: "24px", display: "flex", flexDirection: "column", gap: 24, overflowY: "auto" }}>
      <div style={{ color: C.text, fontSize: 20, fontWeight: 700 }}>📊 Observability Dashboard</div>

      {/* Overview */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <StatCard label="Total Requests" value={ov.total_requests ?? "—"} color={C.accent} spark={tpArr} />
        <StatCard label="Avg Latency" value={ov.avg_latency_ms ? `${ov.avg_latency_ms}ms` : "—"} color={C.success} spark={latArr} />
        <StatCard label="Error Rate" value={ov.error_rate != null ? `${ov.error_rate}%` : "—"} color={ov.error_rate > 5 ? C.error : C.success} spark={errArr} />
        <StatCard label="Total Tokens" value={ov.total_tokens ? ov.total_tokens.toLocaleString() : "—"} color={C.warn} />
        <StatCard label="Conversations" value={ov.total_conversations ?? "—"} sub={`${ov.active_conversations ?? 0} active`} color={C.accent} />
      </div>

      {/* Latency chart */}
      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 20 }}>
        <div style={{ color: C.muted, fontSize: 12, marginBottom: 12, textTransform: "uppercase", letterSpacing: 1 }}>Latency Over Time (ms)</div>
        {latency?.length ? (
          <div style={{ position: "relative", height: 120 }}>
            <svg width="100%" height="120" viewBox="0 0 800 120" preserveAspectRatio="none">
              {latency.map((d, i) => {
                const x = (i / (latency.length - 1 || 1)) * 800;
                const mn = Math.min(...latency.map(l => l.avg_latency));
                const mx = Math.max(...latency.map(l => l.avg_latency)) || 1;
                const y = 110 - ((d.avg_latency - mn) / (mx - mn || 1)) * 100;
                return <circle key={i} cx={x} cy={y} r="3" fill={C.accent} opacity="0.8" />;
              })}
              <polyline
                points={latency.map((d, i) => {
                  const x = (i / (latency.length - 1 || 1)) * 800;
                  const mn = Math.min(...latency.map(l => l.avg_latency));
                  const mx = Math.max(...latency.map(l => l.avg_latency)) || 1;
                  const y = 110 - ((d.avg_latency - mn) / (mx - mn || 1)) * 100;
                  return `${x},${y}`;
                }).join(" ")}
                fill="none" stroke={C.accent} strokeWidth="2"
              />
            </svg>
          </div>
        ) : <div style={{ color: C.muted, fontSize: 13 }}>No data yet. Send some messages!</div>}
      </div>

      {/* Recent logs */}
      <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 20 }}>
        <div style={{ color: C.muted, fontSize: 12, marginBottom: 12, textTransform: "uppercase", letterSpacing: 1 }}>Recent Inference Logs</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["Time", "Model", "Latency", "Tokens", "Status", "Input Preview"].map(h => (
                  <th key={h} style={{ textAlign: "left", color: C.muted, padding: "6px 10px", borderBottom: `1px solid ${C.border}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(logs || []).map(l => (
                <tr key={l.id}>
                  <td style={{ padding: "8px 10px", color: C.muted }}>{l.timestamp?.slice(11, 19)}</td>
                  <td style={{ padding: "8px 10px", color: C.accent }}>{l.model?.slice(-15)}</td>
                  <td style={{ padding: "8px 10px", color: l.latency_ms > 2000 ? C.warn : C.success }}>{l.latency_ms?.toFixed(0)}ms</td>
                  <td style={{ padding: "8px 10px", color: C.text }}>{l.total_tokens}</td>
                  <td style={{ padding: "8px 10px" }}>
                    <span style={{
                      background: l.status === "success" ? "#1a3a2a" : "#3a1a1a",
                      color: l.status === "success" ? C.success : C.error,
                      padding: "2px 8px", borderRadius: 4, fontSize: 11
                    }}>{l.status}</span>
                  </td>
                  <td style={{ padding: "8px 10px", color: C.muted, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {l.input_preview}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!logs?.length && <div style={{ color: C.muted, fontSize: 13, paddingTop: 8 }}>No logs yet.</div>}
        </div>
      </div>
    </div>
  );
}

// ─── Conversations Sidebar ────────────────────────────────────────────────────
function ConvList({ active, onSelect, onNew }) {
  const { data: convs, refresh } = useApi("/api/conversations", []);
  useEffect(() => { const t = setInterval(refresh, 3000); return () => clearInterval(t); }, []);

  return (
    <div style={{
      width: 240, minWidth: 240, background: C.surface,
      borderRight: `1px solid ${C.border}`, display: "flex", flexDirection: "column",
      height: "100%", overflowY: "auto",
    }}>
      <div style={{ padding: "16px 16px 8px", borderBottom: `1px solid ${C.border}` }}>
        <button onClick={onNew} style={{
          width: "100%", background: C.accent, color: "#fff", border: "none",
          borderRadius: 8, padding: "10px 0", cursor: "pointer", fontWeight: 600, fontSize: 13
        }}>+ New Chat</button>
      </div>
      <div style={{ padding: "8px 0", flex: 1, overflowY: "auto" }}>
        {(convs || []).map(c => (
          <div key={c.id}
            onClick={() => onSelect(c)}
            style={{
              padding: "10px 16px", cursor: "pointer",
              background: active?.id === c.id ? "#1a1a2e" : "transparent",
              borderLeft: active?.id === c.id ? `3px solid ${C.accent}` : "3px solid transparent",
              transition: "all 0.15s",
            }}>
            <div style={{
              color: c.status === "cancelled" ? C.muted : C.text,
              fontSize: 13, fontWeight: 500,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              textDecoration: c.status === "cancelled" ? "line-through" : "none"
            }}>{c.title}</div>
            <div style={{ color: C.muted, fontSize: 11, marginTop: 2, display: "flex", justifyContent: "space-between" }}>
              <span>{c.model?.slice(-10)}</span>
              <span style={{
                color: c.status === "cancelled" ? C.error : C.success,
                fontSize: 10
              }}>{c.status}</span>
            </div>
            <div style={{ color: C.muted, fontSize: 10 }}>{c.message_count} msgs</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Chat Tab ────────────────────────────────────────────────────────────────
function ChatView() {
  const [activeConv, setActiveConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [useStream, setUseStream] = useState(true);
  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  const scrollBottom = () => bottomRef.current?.scrollIntoView({ behavior: "smooth" });

  const loadConv = async (conv) => {
    setActiveConv(conv);
    try {
      const r = await fetch(`${API}/api/conversations/${conv.id}`);
      const data = await r.json();
      setMessages(data.messages || []);
    } catch (_) {}
    setTimeout(scrollBottom, 100);
  };

  const newConv = async () => {
    const r = await fetch(`${API}/api/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: "anthropic", model: "claude-sonnet-4-20250514" })
    });
    const data = await r.json();
    setActiveConv(data);
    setMessages([]);
  };

  const cancelConv = async () => {
    if (!activeConv) return;
    if (abortRef.current) abortRef.current.abort();
    await fetch(`${API}/api/conversations/${activeConv.id}/cancel`, { method: "PATCH" });
    setActiveConv({ ...activeConv, status: "cancelled" });
    setLoading(false);
    setStreaming(false);
  };

  const send = async () => {
    if (!input.trim() || loading) return;
    const msg = input.trim();
    setInput("");
    setLoading(true);

    const userMsg = { role: "user", content: msg, id: Date.now() + "u" };
    setMessages(prev => [...prev, userMsg]);

    try {
      if (useStream) {
        setStreaming(true);
        setStreamText("");
        const ctrl = new AbortController();
        abortRef.current = ctrl;

        const r = await fetch(`${API}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conversation_id: activeConv?.id,
            message: msg,
            stream: true,
          }),
          signal: ctrl.signal,
        });

        let conv_id = activeConv?.id;
        let full = "";
        const reader = r.body.getReader();
        const dec = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = dec.decode(value);
          for (const line of chunk.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try {
              const d = JSON.parse(line.slice(6));
              if (d.chunk) { full += d.chunk; setStreamText(full); }
              if (d.conversation_id && !conv_id) {
                conv_id = d.conversation_id;
                setActiveConv(prev => prev ? prev : { id: conv_id });
              }
              if (d.done) {
                setMessages(prev => [...prev, { role: "assistant", content: full, id: Date.now() + "a" }]);
                setStreamText("");
                setStreaming(false);
              }
            } catch (_) {}
          }
        }
      } else {
        const r = await fetch(`${API}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation_id: activeConv?.id, message: msg, stream: false }),
        });
        const data = await r.json();
        if (!activeConv) setActiveConv({ id: data.conversation_id });
        setMessages(prev => [...prev, { role: "assistant", content: data.message, id: Date.now() + "a" }]);
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setMessages(prev => [...prev, { role: "assistant", content: `⚠️ Error: ${e.message}`, id: Date.now() + "e" }]);
      }
    } finally {
      setLoading(false);
      setStreaming(false);
      setTimeout(scrollBottom, 50);
    }
  };

  useEffect(() => { scrollBottom(); }, [messages, streamText]);

  const isCancelled = activeConv?.status === "cancelled";

  return (
    <div style={{ display: "flex", flex: 1, height: "100%", overflow: "hidden" }}>
      <ConvList active={activeConv} onSelect={loadConv} onNew={newConv} />

      {/* Chat area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Header */}
        <div style={{
          padding: "14px 20px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: C.surface
        }}>
          <div>
            <div style={{ color: C.text, fontWeight: 600, fontSize: 14 }}>
              {activeConv ? activeConv.title || "Chat" : "Select or start a conversation"}
            </div>
            {activeConv && (
              <div style={{ color: C.muted, fontSize: 11 }}>
                {activeConv.model || "claude-sonnet-4-20250514"} · {activeConv.status}
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <label style={{ color: C.muted, fontSize: 12, display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" checked={useStream} onChange={e => setUseStream(e.target.checked)} />
              Stream
            </label>
            {activeConv && activeConv.status === "active" && (
              <button onClick={cancelConv} style={{
                background: "#3a1a1a", color: C.error, border: `1px solid ${C.error}`,
                borderRadius: 6, padding: "5px 12px", cursor: "pointer", fontSize: 12
              }}>Cancel</button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 16 }}>
          {messages.length === 0 && !streaming && (
            <div style={{ textAlign: "center", color: C.muted, marginTop: 60 }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>🤖</div>
              <div style={{ fontSize: 16 }}>Start a conversation</div>
              <div style={{ fontSize: 13, marginTop: 4 }}>All inferences are logged automatically</div>
            </div>
          )}
          {messages.map(m => (
            <div key={m.id} style={{
              display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start",
            }}>
              <div style={{
                maxWidth: "75%", padding: "12px 16px", borderRadius: 12,
                background: m.role === "user" ? C.accent : C.surface,
                border: m.role === "assistant" ? `1px solid ${C.border}` : "none",
                color: C.text, fontSize: 14, lineHeight: 1.6,
                whiteSpace: "pre-wrap",
              }}>{m.content}</div>
            </div>
          ))}
          {streaming && (
            <div style={{ display: "flex", justifyContent: "flex-start" }}>
              <div style={{
                maxWidth: "75%", padding: "12px 16px", borderRadius: 12,
                background: C.surface, border: `1px solid ${C.border}`,
                color: C.text, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap",
              }}>
                {streamText}
                <span style={{ animation: "blink 1s infinite", color: C.accent }}>▊</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={{ padding: "16px 20px", borderTop: `1px solid ${C.border}`, background: C.surface }}>
          {isCancelled && (
            <div style={{ color: C.error, fontSize: 12, marginBottom: 8, textAlign: "center" }}>
              This conversation was cancelled. Start a new one.
            </div>
          )}
          <div style={{ display: "flex", gap: 10 }}>
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
              disabled={loading || isCancelled}
              placeholder={isCancelled ? "Conversation cancelled" : "Type a message... (Enter to send)"}
              style={{
                flex: 1, background: C.bg, border: `1px solid ${C.border}`,
                borderRadius: 8, padding: "10px 14px", color: C.text,
                fontSize: 14, outline: "none",
                opacity: isCancelled ? 0.5 : 1
              }}
            />
            <button onClick={send} disabled={loading || isCancelled || !input.trim()} style={{
              background: (loading || isCancelled) ? C.muted : C.accent,
              color: "#fff", border: "none", borderRadius: 8,
              padding: "10px 18px", cursor: loading ? "wait" : "pointer",
              fontWeight: 600, fontSize: 13, transition: "background 0.15s"
            }}>
              {loading ? "..." : "Send"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Root App ────────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState("chat");

  return (
    <div style={{ background: C.bg, color: C.text, height: "100vh", display: "flex", flexDirection: "column", fontFamily: "'Inter', sans-serif" }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: ${C.bg}; }
        ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 3px; }
        @keyframes blink { 0%,100%{opacity:1}50%{opacity:0} }
        input::placeholder { color: ${C.muted}; }
      `}</style>

      {/* Top Nav */}
      <div style={{
        borderBottom: `1px solid ${C.border}`, background: C.surface,
        display: "flex", alignItems: "center", padding: "0 20px", height: 52,
        gap: 0,
      }}>
        <div style={{ color: C.accent, fontWeight: 700, fontSize: 16, marginRight: 32, letterSpacing: -0.5 }}>
          ⚡ LLM Logger
        </div>
        {[["chat", "💬 Chat"], ["dashboard", "📊 Dashboard"]].map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)} style={{
            background: "none", border: "none", color: tab === id ? C.text : C.muted,
            padding: "0 16px", height: 52, cursor: "pointer", fontSize: 13, fontWeight: 600,
            borderBottom: tab === id ? `2px solid ${C.accent}` : "2px solid transparent",
            transition: "all 0.15s",
          }}>{label}</button>
        ))}
        <div style={{ marginLeft: "auto", color: C.muted, fontSize: 11 }}>
          claude-sonnet-4-20250514 · Anthropic
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: "hidden", display: "flex" }}>
        {tab === "chat" ? <ChatView /> : <Dashboard />}
      </div>
    </div>
  );
}
