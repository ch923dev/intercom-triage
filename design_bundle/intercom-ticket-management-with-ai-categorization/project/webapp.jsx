// Webapp surface — full Kanban triage view.
// Reads tickets from window.TRIAGE_TICKETS; exposes <TriageWebapp> on window.
// Sized for 1440 x 900 artboard.

const { useState, useEffect, useMemo, useRef } = React;

// ─── tokens ────────────────────────────────────────────────────────────────
const tokens = (dark, accent) => ({
  bg: dark ? '#0e0f0e' : '#faf9f6',
  panel: dark ? '#15161a' : '#ffffff',
  ink: dark ? '#f5f4ef' : '#111111',
  ink2: dark ? '#a3a39d' : '#555555',
  ink3: dark ? '#6a6a64' : '#8a8a82',
  line: dark ? '#26282d' : '#e6e3db',
  lineSoft: dark ? '#1e2025' : '#efece4',
  chipBg: dark ? '#1c1d22' : '#f3efe6',
  hover: dark ? '#1a1b20' : '#f5f2ea',
  shadow: dark ? '0 12px 36px rgba(0,0,0,.45)' : '0 12px 32px rgba(40,30,20,.10)',
  accent,
  dark,
});

const fontStack = `'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`;
const monoStack = `'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace`;

// ─── small components ─────────────────────────────────────────────────────
function CatDot({ catId, size = 8 }) {
  const c = window.TRIAGE_CAT_BY_ID[catId];
  if (!c) return null;
  return <span style={{
    display: 'inline-block', width: size, height: size, borderRadius: 2,
    background: c.swatch, flex: '0 0 auto',
  }} />;
}

function Mono({ children, style }) {
  return <span style={{ fontFamily: monoStack, fontSize: 10.5, letterSpacing: '.04em', textTransform: 'uppercase', ...style }}>{children}</span>;
}

// ─── follow-up chip ───────────────────────────────────────────────────────
function FollowupChip({ followup, T, tick, compact }) {
  if (!followup) return null;
  const ms = followup.dueAt - Date.now();
  const due = ms <= 0;
  const label = window.formatCountdown(ms);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: compact ? '0 5px' : '1px 6px',
      border: '0.5px solid ' + (due ? T.accent : T.line),
      borderRadius: 2,
      fontFamily: monoStack, fontSize: 9.5, letterSpacing: '.04em', textTransform: 'uppercase',
      color: due ? T.accent : T.ink2,
      background: due ? (T.dark ? 'rgba(255,77,46,.12)' : 'rgba(255,77,46,.08)') : 'transparent',
      animation: due ? 'triagePulse 1.4s ease-in-out infinite' : 'none',
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: 5, background: due ? T.accent : T.ink3,
      }} />
      {due ? 'Follow up · ' + label : 'F/U ' + label}
    </span>
  );
}

// ─── ticket card ──────────────────────────────────────────────────────────
function TicketCard({ ticket, T, tweaks, onClick, onDragStart, overridden, isSelected, followup, note, tick }) {
  const cat = window.TRIAGE_CAT_BY_ID[ticket.cat];
  const dense = tweaks.density === 'compact';
  const rich = tweaks.density === 'comfy';
  const showSummary = tweaks.showSummary && !dense;
  const showConf = tweaks.showConfidence;
  const dueNow = followup && (followup.dueAt - Date.now()) <= 0;

  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, ticket)}
      onClick={onClick}
      style={{
        background: T.panel,
        border: '0.5px solid ' + (isSelected ? T.accent : dueNow ? T.accent : T.line),
        boxShadow: isSelected ? '0 0 0 1px ' + T.accent
          : dueNow ? '0 0 0 1px ' + T.accent + ', 0 0 0 4px ' + (T.dark ? 'rgba(255,77,46,.12)' : 'rgba(255,77,46,.08)') : 'none',
        borderRadius: 4,
        padding: dense ? '8px 10px' : '11px 12px 12px',
        cursor: 'grab',
        position: 'relative',
        transition: 'border-color .12s, background .12s, box-shadow .25s',
      }}
      onMouseEnter={(e) => e.currentTarget.style.background = T.hover}
      onMouseLeave={(e) => e.currentTarget.style.background = T.panel}
    >
      {/* override marker — diamond on left edge */}
      {overridden && (
        <div title="Manually moved" style={{
          position: 'absolute', left: -3, top: 14, width: 5, height: 5,
          background: T.accent, transform: 'rotate(45deg)',
        }} />
      )}

      {/* top row: id mono + ago */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: dense ? 4 : 6 }}>
        <Mono style={{ color: T.ink3 }}>{ticket.id}</Mono>
        <Mono style={{ color: T.ink3 }}>{window.formatAgo(ticket.updatedAgoMin)}</Mono>
      </div>

      {/* title */}
      <div style={{
        fontFamily: fontStack, fontSize: dense ? 12.5 : 13.5, lineHeight: 1.35,
        color: T.ink, fontWeight: 500, letterSpacing: '-0.005em',
        marginBottom: showSummary ? 6 : 8,
        textWrap: 'pretty',
        display: '-webkit-box', WebkitLineClamp: dense ? 2 : 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
      }}>{ticket.title}</div>

      {/* summary */}
      {showSummary && (
        <div style={{
          fontFamily: fontStack, fontSize: 11.5, lineHeight: 1.45,
          color: T.ink2, marginBottom: 9,
          display: '-webkit-box', WebkitLineClamp: rich ? 4 : 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>{ticket.summary}</div>
      )}

      {/* meta row */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{
          fontFamily: fontStack, fontSize: 11, color: T.ink2,
          maxWidth: 110, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{ticket.customer}</span>
        {ticket.plan !== 'Free' && ticket.plan !== '—' && (
          <Mono style={{
            color: T.ink2, padding: '1px 5px', border: '0.5px solid ' + T.line, borderRadius: 2, fontSize: 9.5,
          }}>{ticket.plan}</Mono>
        )}
        {ticket.msgs > 1 && (
          <Mono style={{ color: T.ink3, fontSize: 9.5 }}>{ticket.msgs} msgs</Mono>
        )}
        {showConf && (
          <Mono style={{
            color: ticket.conf < 0.5 ? '#c34a2b' : T.ink3,
            fontSize: 9.5, marginLeft: 'auto',
          }}>{Math.round(ticket.conf * 100)}%</Mono>
        )}
      </div>

      {/* follow-up + notes row */}
      {(followup || note) && (
        <div style={{
          display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
          marginTop: dense ? 6 : 8, paddingTop: dense ? 6 : 8,
          borderTop: '0.5px dashed ' + T.lineSoft,
        }}>
          <FollowupChip followup={followup} T={T} tick={tick} />
          {note && (
            <Mono style={{
              color: T.ink2, fontSize: 9.5,
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}>
              <span style={{ width: 5, height: 5, background: T.ink3 }} />
              Notes ({note.split(/\n/).filter(Boolean).length})
            </Mono>
          )}
        </div>
      )}
    </div>
  );
}

// ─── column ───────────────────────────────────────────────────────────────
function Column({ cat, tickets, T, tweaks, onCardClick, onDragStart, onDrop, dragOver, setDragOver, selectedId, overrides, followups, notes, tick }) {
  const isDragOver = dragOver === cat.id;
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(cat.id); }}
      onDragLeave={() => setDragOver(null)}
      onDrop={(e) => { e.preventDefault(); onDrop(cat.id); setDragOver(null); }}
      style={{
        flex: '0 0 280px', display: 'flex', flexDirection: 'column',
        background: isDragOver ? T.hover : 'transparent',
        borderRight: '0.5px solid ' + T.lineSoft,
        transition: 'background .12s',
      }}
    >
      {/* header */}
      <div style={{
        padding: '14px 14px 10px', borderBottom: '0.5px solid ' + T.line,
        display: 'flex', alignItems: 'center', gap: 8, position: 'sticky', top: 0,
        background: isDragOver ? T.hover : T.bg, zIndex: 1,
      }}>
        <CatDot catId={cat.id} size={9} />
        <div style={{ fontFamily: fontStack, fontSize: 12.5, color: T.ink, fontWeight: 500, letterSpacing: '-0.005em' }}>
          {cat.label}
        </div>
        <Mono style={{ color: T.ink3, marginLeft: 'auto' }}>{tickets.length}</Mono>
      </div>

      {/* cards */}
      <div style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto', flex: 1 }}>
        {tickets.length === 0 ? (
          <div style={{
            fontFamily: monoStack, fontSize: 10, letterSpacing: '.04em', textTransform: 'uppercase',
            color: T.ink3, textAlign: 'center', padding: '24px 8px',
            border: '0.5px dashed ' + T.line, borderRadius: 3,
          }}>empty</div>
        ) : tickets.map(tk => (
          <TicketCard key={tk.id} ticket={tk} T={T} tweaks={tweaks}
            onClick={() => onCardClick(tk)}
            onDragStart={(e, t) => onDragStart(e, t)}
            overridden={!!overrides[tk.id]}
            isSelected={selectedId === tk.id}
            followup={followups[tk.id]}
            note={notes[tk.id]}
            tick={tick} />
        ))}
      </div>
    </div>
  );
}

// ─── recency slider ───────────────────────────────────────────────────────
function RecencySlider({ value, unit, onChange, T }) {
  const max = unit === 'hours' ? 168 : 30;
  const min = 1;
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 320 }}>
      <Mono style={{ color: T.ink3 }}>Window</Mono>
      <input type="range" min={min} max={max} value={value}
        onChange={(e) => onChange({ value: +e.target.value, unit })}
        style={{
          flex: 1, height: 2, appearance: 'none', WebkitAppearance: 'none',
          background: `linear-gradient(to right, ${T.ink} 0%, ${T.ink} ${pct}%, ${T.line} ${pct}%, ${T.line} 100%)`,
          outline: 'none',
        }} />
      <div style={{
        display: 'flex', alignItems: 'center', border: '0.5px solid ' + T.line, borderRadius: 3,
        fontFamily: monoStack, fontSize: 11,
      }}>
        <div style={{ padding: '4px 8px', color: T.ink, minWidth: 36, textAlign: 'right' }}>{value}</div>
        <div style={{ borderLeft: '0.5px solid ' + T.line, display: 'flex' }}>
          {['hours','days'].map(u => (
            <button key={u} onClick={() => onChange({ value, unit: u })}
              style={{
                padding: '4px 7px', border: 0, background: unit === u ? T.ink : 'transparent',
                color: unit === u ? T.bg : T.ink3, fontFamily: monoStack, fontSize: 10,
                letterSpacing: '.04em', textTransform: 'uppercase', cursor: 'pointer',
              }}>{u.slice(0,1)}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── filter pill ──────────────────────────────────────────────────────────
function FilterPill({ label, active, onClick, T, swatch }) {
  return (
    <button onClick={onClick} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 9px 4px ' + (swatch ? 8 : 9) + 'px', border: '0.5px solid ' + (active ? T.ink : T.line),
      borderRadius: 999, background: active ? T.ink : 'transparent',
      color: active ? T.bg : T.ink, fontFamily: fontStack, fontSize: 11.5,
      cursor: 'pointer', transition: 'all .12s',
    }}>
      {swatch && <span style={{ width: 7, height: 7, borderRadius: 2, background: swatch }} />}
      {label}
    </button>
  );
}

// ─── flyout (detail panel) ────────────────────────────────────────────────
function Flyout({ ticket, T, tweaks, onClose, onCategorize, overridden,
                  followup, note, onSetFollowup, onClearFollowup, onChangeNote, tick }) {
  if (!ticket) return null;
  const cat = window.TRIAGE_CAT_BY_ID[ticket.cat];
  const dueMs = followup ? followup.dueAt - Date.now() : null;
  const dueNow = followup && dueMs <= 0;
  return (
    <div style={{
      position: 'absolute', top: 0, right: 0, bottom: 0, width: 440,
      background: T.panel, borderLeft: '0.5px solid ' + T.line,
      boxShadow: T.shadow, display: 'flex', flexDirection: 'column',
      fontFamily: fontStack, zIndex: 5,
    }}>
      {/* header */}
      <div style={{ padding: '16px 20px 14px', borderBottom: '0.5px solid ' + T.line }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <Mono style={{ color: T.ink3 }}>{ticket.id}</Mono>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={() => window.open('about:blank', '_blank')} style={{
              border: '0.5px solid ' + T.line, background: 'transparent', color: T.ink,
              fontFamily: monoStack, fontSize: 10, letterSpacing: '.04em', textTransform: 'uppercase',
              padding: '5px 9px', borderRadius: 3, cursor: 'pointer',
            }}>Open in Intercom ↗</button>
            <button onClick={onClose} style={{
              border: '0.5px solid ' + T.line, background: 'transparent', color: T.ink,
              width: 26, height: 26, borderRadius: 3, cursor: 'pointer', fontSize: 14,
            }}>×</button>
          </div>
        </div>
        <div style={{ fontSize: 18, fontWeight: 500, color: T.ink, lineHeight: 1.3, letterSpacing: '-0.01em', textWrap: 'pretty' }}>
          {ticket.title}
        </div>
      </div>

      {/* scrollable body */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {/* meta */}
        <div style={{ padding: '14px 20px', borderBottom: '0.5px solid ' + T.lineSoft }}>
          <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr', rowGap: 7, fontSize: 12 }}>
            <Mono style={{ color: T.ink3 }}>Customer</Mono>
            <div style={{ color: T.ink }}>{ticket.customer} · {ticket.company}</div>
            <Mono style={{ color: T.ink3 }}>Plan</Mono>
            <div style={{ color: T.ink }}>{ticket.plan}</div>
            <Mono style={{ color: T.ink3 }}>Updated</Mono>
            <div style={{ color: T.ink }}>{window.formatAgo(ticket.updatedAgoMin)}</div>
            <Mono style={{ color: T.ink3 }}>State</Mono>
            <div style={{ color: T.ink, textTransform: 'capitalize' }}>{ticket.state}</div>
          </div>
        </div>

        {/* AI block */}
        <div style={{ padding: '14px 20px', borderBottom: '0.5px solid ' + T.lineSoft }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <Mono style={{ color: T.ink3 }}>AI Summary</Mono>
            {tweaks.showConfidence && <Mono style={{ color: T.ink3 }}>· {Math.round(ticket.conf * 100)}% confidence</Mono>}
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.55, color: T.ink, textWrap: 'pretty' }}>
            {ticket.summary}
          </div>
        </div>

        {/* follow-up */}
        <div style={{ padding: '14px 20px', borderBottom: '0.5px solid ' + T.lineSoft,
                      background: dueNow ? (T.dark ? 'rgba(255,77,46,.06)' : 'rgba(255,77,46,.04)') : 'transparent' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <Mono style={{ color: T.ink3 }}>Follow-up</Mono>
            {followup && (
              <Mono style={{
                color: dueNow ? T.accent : T.ink2,
                animation: dueNow ? 'triagePulse 1.4s ease-in-out infinite' : 'none',
              }}>
                · {dueNow ? '⚠ ' : ''}{window.formatCountdown(dueMs)}
                {followup.reason ? ' · ' + followup.reason : ''}
              </Mono>
            )}
            {followup && (
              <button onClick={onClearFollowup} style={{
                marginLeft: 'auto', border: 0, background: 'transparent',
                color: T.ink3, fontFamily: monoStack, fontSize: 9.5,
                letterSpacing: '.04em', textTransform: 'uppercase', cursor: 'pointer',
              }}>Clear</button>
            )}
          </div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {window.TRIAGE_FOLLOWUP_PRESETS.map(p => (
              <button key={p.label} onClick={() => onSetFollowup(p.min)} style={{
                padding: '4px 10px', border: '0.5px solid ' + T.line, borderRadius: 3,
                background: 'transparent', color: T.ink,
                fontFamily: monoStack, fontSize: 10.5, letterSpacing: '.04em',
                textTransform: 'uppercase', cursor: 'pointer',
              }}>+ {p.label}</button>
            ))}
            <button onClick={() => onSetFollowup(0.2)} title="Demo: fire in ~12s" style={{
              padding: '4px 10px', border: '0.5px dashed ' + T.line, borderRadius: 3,
              background: 'transparent', color: T.ink3,
              fontFamily: monoStack, fontSize: 10.5, letterSpacing: '.04em',
              textTransform: 'uppercase', cursor: 'pointer',
            }}>+ 12s test</button>
          </div>
        </div>

        {/* next steps / notes */}
        <div style={{ padding: '14px 20px', borderBottom: '0.5px solid ' + T.lineSoft }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <Mono style={{ color: T.ink3 }}>Next steps</Mono>
            <Mono style={{ color: T.ink3 }}>· how to proceed</Mono>
          </div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 9 }}>
            {window.TRIAGE_NEXT_STEPS.map(s => (
              <button key={s} onClick={() => onChangeNote((note ? note + '\n' : '') + '• ' + s)} style={{
                padding: '3px 8px', border: '0.5px solid ' + T.line, borderRadius: 999,
                background: 'transparent', color: T.ink2,
                fontFamily: fontStack, fontSize: 11, cursor: 'pointer',
              }}>+ {s}</button>
            ))}
          </div>
          <textarea
            value={note || ''}
            onChange={(e) => onChangeNote(e.target.value)}
            placeholder="Write the next action. Cite teammates, link tickets, drop repro steps."
            spellCheck={false}
            style={{
              width: '100%', minHeight: 84, resize: 'vertical', boxSizing: 'border-box',
              padding: 10, border: '0.5px solid ' + T.line, borderRadius: 4,
              background: T.bg, color: T.ink, fontFamily: monoStack, fontSize: 11.5,
              lineHeight: 1.55, outline: 'none', letterSpacing: '.005em',
            }}
            onFocus={(e) => e.target.style.borderColor = T.accent}
            onBlur={(e) => e.target.style.borderColor = T.line}
          />
          {note && (
            <Mono style={{ color: T.ink3, marginTop: 6, display: 'block' }}>
              Last edit just now · {note.split(/\n/).filter(Boolean).length} steps
            </Mono>
          )}
        </div>

        {/* category override */}
        <div style={{ padding: '14px 20px', borderBottom: '0.5px solid ' + T.lineSoft }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <Mono style={{ color: T.ink3 }}>Category</Mono>
            {overridden && <Mono style={{ color: T.accent }}>· manually set</Mono>}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
            {window.TRIAGE_CATEGORIES.map(c => (
              <FilterPill key={c.id} label={c.label} swatch={c.swatch}
                active={c.id === ticket.cat}
                onClick={() => onCategorize(c.id)} T={T} />
            ))}
          </div>
        </div>

        {/* latest message */}
        <div style={{ padding: '14px 20px' }}>
          <Mono style={{ color: T.ink3, display: 'block', marginBottom: 10 }}>Latest message</Mono>
          <div style={{
            background: T.chipBg, border: '0.5px solid ' + T.lineSoft, borderRadius: 4,
            padding: '12px 14px', fontSize: 13, lineHeight: 1.5, color: T.ink,
          }}>
            <div style={{ fontFamily: monoStack, fontSize: 10, letterSpacing: '.04em', textTransform: 'uppercase', color: T.ink3, marginBottom: 6 }}>
              {ticket.customer}
            </div>
            “{ticket.lastMsg}”
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── main webapp ──────────────────────────────────────────────────────────
function TriageWebapp({ tweaks }) {
  const T = tokens(tweaks.dark, tweaks.accent);

  // shared state via window so popup mirrors
  const [recency, setRecency] = useState(() => window.__triageRecency || { value: 24, unit: 'hours' });
  const [states, setStates] = useState(() => window.__triageStates || ['open']);
  const [cats, setCats] = useState(() => window.__triageCats || window.TRIAGE_CATEGORIES.map(c => c.id));
  const [overrides, setOverrides] = useState({}); // ticketId -> catId
  const [followups, setFollowups] = useState(() => ({ ...window.__triageFollowups }));
  const [notes, setNotes] = useState(() => ({ ...window.__triageNotes }));
  const [alarms, setAlarms] = useState([]); // { id, ticketId, dueAt, snoozedUntil? }
  const [selected, setSelected] = useState(null);
  const [dragOver, setDragOver] = useState(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const [tick, setTickState] = useState(0);
  const [muted, setMuted] = useState(false);

  // inject pulse keyframes once
  useEffect(() => {
    if (document.getElementById('triage-pulse-kf')) return;
    const s = document.createElement('style');
    s.id = 'triage-pulse-kf';
    s.textContent = `
      @keyframes triagePulse { 0%,100%{opacity:1} 50%{opacity:.45} }
      @keyframes triageRing { 0%{box-shadow:0 0 0 0 rgba(255,77,46,.55)} 100%{box-shadow:0 0 0 14px rgba(255,77,46,0)} }
      @keyframes triageSlide { from{transform:translateX(20px);opacity:0} to{transform:translateX(0);opacity:1} }
    `;
    document.head.appendChild(s);
  }, []);

  // tick once per second for countdowns + alarm detection
  useEffect(() => {
    const i = setInterval(() => setTickState(t => t + 1), 1000);
    return () => clearInterval(i);
  }, []);

  // sync to window for cross-surface
  useEffect(() => { window.__triageRecency = recency; window.dispatchEvent(new Event('triage-sync')); }, [recency]);
  useEffect(() => { window.__triageStates = states; window.dispatchEvent(new Event('triage-sync')); }, [states]);
  useEffect(() => { window.__triageCats = cats; window.dispatchEvent(new Event('triage-sync')); }, [cats]);
  useEffect(() => { window.__triageFollowups = followups; window.dispatchEvent(new Event('triage-sync')); }, [followups]);
  useEffect(() => { window.__triageNotes = notes; window.dispatchEvent(new Event('triage-sync')); }, [notes]);

  // alarm detection — when a followup crosses dueAt and hasn't fired, queue + ding
  useEffect(() => {
    const now = Date.now();
    const newlyDue = [];
    Object.entries(followups).forEach(([tid, f]) => {
      if (!f.fired && f.dueAt <= now) newlyDue.push(tid);
    });
    if (newlyDue.length === 0) return;
    setFollowups(prev => {
      const next = { ...prev };
      newlyDue.forEach(tid => { next[tid] = { ...next[tid], fired: true }; });
      return next;
    });
    setAlarms(prev => [
      ...prev,
      ...newlyDue.filter(tid => !prev.find(a => a.ticketId === tid)).map(tid => ({
        id: tid + '-' + Date.now(), ticketId: tid, dueAt: followups[tid].dueAt,
      })),
    ]);
    if (!muted) window.playTriageAlarm();
  }, [tick]);

  const recencyMs = (recency.unit === 'hours' ? 3600 : 86400) * 1000 * recency.value;
  const cutoff = window.TRIAGE_NOW - recencyMs;

  // visible tickets
  const filtered = useMemo(() => {
    return window.TRIAGE_TICKETS
      .filter(t => t.updatedAt.getTime() >= cutoff)
      .filter(t => states.includes(t.state))
      .map(t => ({ ...t, cat: overrides[t.id] || t.cat }))
      .filter(t => cats.includes(t.cat));
  }, [cutoff, states, cats, overrides]);

  // group by category — pinned-to-top if alarm is firing
  const grouped = useMemo(() => {
    const g = Object.fromEntries(window.TRIAGE_CATEGORIES.map(c => [c.id, []]));
    filtered.forEach(t => g[t.cat].push(t));
    Object.values(g).forEach(arr => arr.sort((a, b) => {
      const aDue = followups[a.id] && (followups[a.id].dueAt - Date.now()) <= 0 ? -1 : 0;
      const bDue = followups[b.id] && (followups[b.id].dueAt - Date.now()) <= 0 ? -1 : 0;
      if (aDue !== bDue) return aDue - bDue;
      return a.updatedAgoMin - b.updatedAgoMin;
    }));
    return g;
  }, [filtered, followups, tick]);

  // drag
  const dragId = useRef(null);
  const onDragStart = (e, t) => { dragId.current = t.id; e.dataTransfer.effectAllowed = 'move'; };
  const onDrop = (catId) => {
    if (!dragId.current) return;
    setOverrides(o => ({ ...o, [dragId.current]: catId }));
    dragId.current = null;
  };

  // follow-up + notes mutators (operate on `selected`)
  const setFollowupFor = (tid, minutesFromNow, reason = '') => {
    setFollowups(prev => ({
      ...prev,
      [tid]: { dueAt: Date.now() + minutesFromNow * 60 * 1000, fired: false, reason },
    }));
    setAlarms(prev => prev.filter(a => a.ticketId !== tid));
  };
  const clearFollowupFor = (tid) => {
    setFollowups(prev => { const n = { ...prev }; delete n[tid]; return n; });
    setAlarms(prev => prev.filter(a => a.ticketId !== tid));
  };
  const setNoteFor = (tid, text) => {
    setNotes(prev => ({ ...prev, [tid]: text }));
  };

  // alarm actions
  const dismissAlarm = (id) => setAlarms(prev => prev.filter(a => a.id !== id));
  const snoozeAlarm = (a, mins) => {
    setFollowups(prev => ({
      ...prev,
      [a.ticketId]: { dueAt: Date.now() + mins * 60 * 1000, fired: false,
                      reason: (prev[a.ticketId]?.reason || '') },
    }));
    dismissAlarm(a.id);
  };

  const visibleCats = window.TRIAGE_CATEGORIES.filter(c => cats.includes(c.id));
  const pendingFollowupsCount = Object.values(followups).filter(f => f.dueAt > Date.now()).length;

  return (
    <div style={{
      width: '100%', height: '100%', background: T.bg, color: T.ink,
      display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden',
      fontFamily: fontStack,
    }}>
      {/* top bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 16, padding: '12px 20px',
        borderBottom: '0.5px solid ' + T.line, background: T.bg, flex: '0 0 auto',
      }}>
        {/* wordmark */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <div style={{ width: 8, height: 8, background: T.accent }} />
          <span style={{
            fontFamily: monoStack, fontSize: 12, letterSpacing: '.14em',
            textTransform: 'uppercase', color: T.ink, fontWeight: 600,
          }}>Triage</span>
          <span style={{ fontFamily: monoStack, fontSize: 10, color: T.ink3, letterSpacing: '.06em' }}>v1.0</span>
        </div>

        <div style={{ width: 1, height: 18, background: T.line }} />

        <RecencySlider value={recency.value} unit={recency.unit} onChange={setRecency} T={T} />

        <div style={{ flex: 1 }} />

        <Mono style={{ color: T.ink3 }}>{filtered.length} tickets</Mono>

        {/* follow-up status + mute */}
        <div title={muted ? 'Alarms muted' : 'Alarms on'}
             onClick={() => setMuted(m => !m)}
             style={{
               display: 'flex', alignItems: 'center', gap: 6, padding: '5px 9px',
               border: '0.5px solid ' + T.line, borderRadius: 3, cursor: 'pointer',
               background: alarms.length > 0 ? (T.dark ? 'rgba(255,77,46,.12)' : 'rgba(255,77,46,.08)') : 'transparent',
             }}>
          <span style={{
            width: 6, height: 6, borderRadius: 6,
            background: muted ? T.ink3 : T.accent,
            animation: alarms.length > 0 && !muted ? 'triagePulse 1.4s ease-in-out infinite' : 'none',
          }} />
          <Mono style={{ color: T.ink2 }}>
            {alarms.length > 0 ? alarms.length + ' due' : pendingFollowupsCount + ' f/u'}
          </Mono>
          {muted && <Mono style={{ color: T.ink3, fontSize: 9.5 }}>muted</Mono>}
        </div>

        {/* filter button */}
        <button onClick={() => { setFilterOpen(o => !o); setColPickerOpen(false); }} style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px',
          border: '0.5px solid ' + (filterOpen ? T.ink : T.line), background: filterOpen ? T.ink : 'transparent',
          color: filterOpen ? T.bg : T.ink, borderRadius: 3, cursor: 'pointer',
          fontFamily: monoStack, fontSize: 10.5, letterSpacing: '.04em', textTransform: 'uppercase',
        }}>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1 2h8M2.5 5h5M4 8h2" stroke="currentColor" strokeWidth="1" strokeLinecap="round"/></svg>
          Filter
        </button>

        {/* column picker */}
        <button onClick={() => { setColPickerOpen(o => !o); setFilterOpen(false); }} style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px',
          border: '0.5px solid ' + (colPickerOpen ? T.ink : T.line), background: colPickerOpen ? T.ink : 'transparent',
          color: colPickerOpen ? T.bg : T.ink, borderRadius: 3, cursor: 'pointer',
          fontFamily: monoStack, fontSize: 10.5, letterSpacing: '.04em', textTransform: 'uppercase',
        }}>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><rect x=".5" y=".5" width="2.5" height="9" stroke="currentColor"/><rect x="3.75" y=".5" width="2.5" height="9" stroke="currentColor"/><rect x="7" y=".5" width="2.5" height="9" stroke="currentColor"/></svg>
          Columns ({cats.length}/7)
        </button>
      </div>

      {/* filter / column picker drawer */}
      {(filterOpen || colPickerOpen) && (
        <div style={{
          padding: '14px 20px', background: T.panel, borderBottom: '0.5px solid ' + T.line,
          display: 'flex', gap: 24, alignItems: 'flex-start', flex: '0 0 auto',
        }}>
          {filterOpen && (
            <>
              <div>
                <Mono style={{ color: T.ink3, display: 'block', marginBottom: 8 }}>State</Mono>
                <div style={{ display: 'flex', gap: 5 }}>
                  {window.TRIAGE_STATES.map(s => (
                    <FilterPill key={s} label={s} active={states.includes(s)} T={T}
                      onClick={() => setStates(p => p.includes(s) ? p.filter(x => x!==s) : [...p, s])} />
                  ))}
                </div>
              </div>
              <div style={{ width: 1, alignSelf: 'stretch', background: T.line }} />
              <div>
                <Mono style={{ color: T.ink3, display: 'block', marginBottom: 8 }}>Category</Mono>
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', maxWidth: 560 }}>
                  {window.TRIAGE_CATEGORIES.map(c => (
                    <FilterPill key={c.id} label={c.label} swatch={c.swatch}
                      active={cats.includes(c.id)} T={T}
                      onClick={() => setCats(p => p.includes(c.id) ? p.filter(x => x!==c.id) : [...p, c.id])} />
                  ))}
                </div>
              </div>
            </>
          )}
          {colPickerOpen && (
            <div style={{ flex: 1 }}>
              <Mono style={{ color: T.ink3, display: 'block', marginBottom: 8 }}>Columns visible on board</Mono>
              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {window.TRIAGE_CATEGORIES.map(c => (
                  <FilterPill key={c.id} label={c.label} swatch={c.swatch}
                    active={cats.includes(c.id)} T={T}
                    onClick={() => setCats(p => p.includes(c.id) ? p.filter(x => x!==c.id) : [...p, c.id])} />
                ))}
              </div>
              <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
                <button onClick={() => setCats(window.TRIAGE_CATEGORIES.map(c => c.id))} style={pillBtn(T)}>All 7</button>
                <button onClick={() => setCats(['urgent','bug','billing'])} style={pillBtn(T)}>Action queue</button>
                <button onClick={() => setCats(['question','feature'])} style={pillBtn(T)}>Backlog</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* board */}
      <div style={{ flex: 1, display: 'flex', overflowX: 'auto', overflowY: 'hidden', position: 'relative' }}>
        {visibleCats.map(c => (
          <Column key={c.id} cat={c} tickets={grouped[c.id]} T={T} tweaks={tweaks}
            onCardClick={setSelected}
            onDragStart={onDragStart}
            onDrop={onDrop}
            dragOver={dragOver} setDragOver={setDragOver}
            selectedId={selected?.id}
            overrides={overrides}
            followups={followups}
            notes={notes}
            tick={tick} />
        ))}
        <div style={{ flex: 1, minWidth: 40 }} />

        <Flyout
          ticket={selected ? { ...selected, cat: overrides[selected.id] || selected.cat } : null}
          T={T} tweaks={tweaks}
          onClose={() => setSelected(null)}
          onCategorize={(catId) => setOverrides(o => ({ ...o, [selected.id]: catId }))}
          overridden={selected && !!overrides[selected.id]}
          followup={selected ? followups[selected.id] : null}
          note={selected ? notes[selected.id] : ''}
          onSetFollowup={(min) => setFollowupFor(selected.id, min)}
          onClearFollowup={() => clearFollowupFor(selected.id)}
          onChangeNote={(text) => setNoteFor(selected.id, text)}
          tick={tick} />

        {/* alarm banners — stacked top-right */}
        <div style={{
          position: 'absolute', top: 12, right: selected ? 452 : 12, zIndex: 6,
          display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none',
        }}>
          {alarms.map(a => {
            const tk = window.TRIAGE_TICKETS.find(t => t.id === a.ticketId);
            if (!tk) return null;
            const cat = window.TRIAGE_CAT_BY_ID[overrides[tk.id] || tk.cat];
            return (
              <div key={a.id} style={{
                width: 340, background: T.panel,
                border: '0.5px solid ' + T.accent,
                boxShadow: '0 12px 36px rgba(40,30,20,.18), 0 0 0 4px ' + (T.dark ? 'rgba(255,77,46,.10)' : 'rgba(255,77,46,.06)'),
                borderRadius: 4, padding: '12px 14px',
                pointerEvents: 'auto', animation: 'triageSlide .25s ease-out',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: 8, background: T.accent,
                    animation: 'triageRing 1.6s ease-out infinite',
                  }} />
                  <Mono style={{ color: T.accent, fontWeight: 600 }}>Follow-up due</Mono>
                  <Mono style={{ color: T.ink3, marginLeft: 'auto' }}>
                    {window.formatCountdown(a.dueAt - Date.now())}
                  </Mono>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
                  <CatDot catId={overrides[tk.id] || tk.cat} size={7} />
                  <Mono style={{ color: T.ink3 }}>{tk.id}</Mono>
                  <Mono style={{ color: T.ink3 }}>· {cat.label}</Mono>
                </div>
                <div style={{ fontSize: 13, color: T.ink, fontWeight: 500, lineHeight: 1.35,
                              marginBottom: 8, textWrap: 'pretty',
                              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                  {tk.title}
                </div>
                {followups[tk.id]?.reason && (
                  <div style={{ fontSize: 11.5, color: T.ink2, marginBottom: 8, fontStyle: 'italic' }}>
                    “{followups[tk.id].reason}”
                  </div>
                )}
                <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  <button onClick={() => { setSelected(tk); dismissAlarm(a.id); }}
                    style={alarmBtn(T, true)}>Open ticket</button>
                  <button onClick={() => snoozeAlarm(a, 15)} style={alarmBtn(T)}>Snooze 15m</button>
                  <button onClick={() => snoozeAlarm(a, 60)} style={alarmBtn(T)}>Snooze 1h</button>
                  <button onClick={() => dismissAlarm(a.id)} style={alarmBtn(T)}>Dismiss</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* footer */}
      <div style={{
        padding: '8px 20px', borderTop: '0.5px solid ' + T.line, background: T.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flex: '0 0 auto',
      }}>
        <Mono style={{ color: T.ink3 }}>
          Showing tickets updated in the last {recency.value} {recency.unit} · auto-categorized by AI · drag to override
        </Mono>
        <Mono style={{ color: T.ink3 }}>last sync 12s ago ●</Mono>
      </div>
    </div>
  );
}

function pillBtn(T) {
  return {
    padding: '4px 9px', border: '0.5px solid ' + T.line, borderRadius: 999,
    background: 'transparent', color: T.ink, fontFamily: fontStack, fontSize: 11.5,
    cursor: 'pointer',
  };
}

function alarmBtn(T, primary) {
  return {
    padding: '4px 9px', border: '0.5px solid ' + (primary ? T.ink : T.line), borderRadius: 3,
    background: primary ? T.ink : 'transparent', color: primary ? T.bg : T.ink,
    fontFamily: monoStack, fontSize: 10, letterSpacing: '.04em', textTransform: 'uppercase',
    cursor: 'pointer',
  };
}

window.TriageWebapp = TriageWebapp;
window.triageTokens = tokens;
window.triageFontStack = fontStack;
window.triageMonoStack = monoStack;
window.TriageMono = Mono;
window.TriageCatDot = CatDot;
