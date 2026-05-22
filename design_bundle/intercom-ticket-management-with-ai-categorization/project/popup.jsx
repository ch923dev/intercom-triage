// Chrome extension popup surface — compact list view with category tabs.
// Mirrors filter/recency from the webapp via window.__triage* shared state.

const { useState: useStateP, useEffect: useEffectP, useMemo: useMemoP } = React;

function TriagePopup({ tweaks }) {
  const T = window.triageTokens(tweaks.dark, tweaks.accent);
  const fontStack = window.triageFontStack;
  const monoStack = window.triageMonoStack;
  const Mono = window.TriageMono;
  const CatDot = window.TriageCatDot;

  // shared state, mirrored
  const [tick, setTick] = useStateP(0);
  useEffectP(() => {
    const h = () => setTick(x => x + 1);
    window.addEventListener('triage-sync', h);
    return () => window.removeEventListener('triage-sync', h);
  }, []);

  const recency = window.__triageRecency || { value: 24, unit: 'hours' };
  const states = window.__triageStates || ['open'];
  const cats = window.__triageCats || window.TRIAGE_CATEGORIES.map(c => c.id);
  const followups = window.__triageFollowups || {};
  const notes = window.__triageNotes || {};

  const [activeCat, setActiveCat] = useStateP('all');

  // local 1s tick for live countdowns
  useEffectP(() => {
    const i = setInterval(() => setTick(x => x + 1), 1000);
    return () => clearInterval(i);
  }, []);

  const recencyMs = (recency.unit === 'hours' ? 3600 : 86400) * 1000 * recency.value;
  const cutoff = window.TRIAGE_NOW - recencyMs;

  const filtered = useMemoP(() => {
    return window.TRIAGE_TICKETS
      .filter(t => t.updatedAt.getTime() >= cutoff)
      .filter(t => states.includes(t.state))
      .filter(t => cats.includes(t.cat))
      .filter(t => activeCat === 'all' || t.cat === activeCat)
      .sort((a, b) => a.updatedAgoMin - b.updatedAgoMin);
  }, [cutoff, states.join(','), cats.join(','), activeCat, tick]);

  const counts = useMemoP(() => {
    const c = { all: 0 };
    window.TRIAGE_CATEGORIES.forEach(x => c[x.id] = 0);
    window.TRIAGE_TICKETS
      .filter(t => t.updatedAt.getTime() >= cutoff)
      .filter(t => states.includes(t.state))
      .filter(t => cats.includes(t.cat))
      .forEach(t => { c.all++; c[t.cat]++; });
    return c;
  }, [cutoff, states.join(','), cats.join(','), tick]);

  const tabs = [{ id: 'all', label: 'All', swatch: null }]
    .concat(window.TRIAGE_CATEGORIES.filter(c => cats.includes(c.id)));

  const dueCount = Object.values(followups).filter(f => f.dueAt <= Date.now()).length;

  return (
    <div style={{
      width: '100%', height: '100%', background: T.bg, color: T.ink,
      display: 'flex', flexDirection: 'column', fontFamily: fontStack, overflow: 'hidden',
    }}>
      {/* due banner */}
      {dueCount > 0 && (
        <div style={{
          padding: '7px 12px',
          background: T.dark ? 'rgba(255,77,46,.14)' : 'rgba(255,77,46,.08)',
          borderBottom: '0.5px solid ' + T.accent,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: 6, background: T.accent,
            animation: 'triagePulse 1.4s ease-in-out infinite',
          }} />
          <Mono style={{ color: T.accent, fontWeight: 600 }}>
            {dueCount} follow-up{dueCount > 1 ? 's' : ''} due
          </Mono>
          <Mono style={{ color: T.ink3, marginLeft: 'auto', fontSize: 9.5 }}>open webapp ↗</Mono>
        </div>
      )}
      {/* header */}
      <div style={{
        padding: '12px 14px 10px', borderBottom: '0.5px solid ' + T.line,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <div style={{ width: 7, height: 7, background: T.accent }} />
        <span style={{
          fontFamily: monoStack, fontSize: 11, letterSpacing: '.14em',
          textTransform: 'uppercase', color: T.ink, fontWeight: 600,
        }}>Triage</span>
        <Mono style={{ color: T.ink3, marginLeft: 4 }}>
          last {recency.value}{recency.unit[0]} · {counts.all}
        </Mono>
        <button title="Open full app" onClick={() => {}} style={{
          marginLeft: 'auto', border: '0.5px solid ' + T.line, background: 'transparent',
          color: T.ink, fontFamily: monoStack, fontSize: 9.5, letterSpacing: '.04em',
          textTransform: 'uppercase', padding: '4px 7px', borderRadius: 3, cursor: 'pointer',
        }}>Open ↗</button>
      </div>

      {/* tabs */}
      <div style={{
        display: 'flex', overflowX: 'auto', borderBottom: '0.5px solid ' + T.line,
        padding: '0 8px', gap: 0,
      }}>
        {tabs.map(t => {
          const isActive = activeCat === t.id;
          const count = counts[t.id] || 0;
          return (
            <button key={t.id} onClick={() => setActiveCat(t.id)} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '9px 10px',
              border: 0, background: 'transparent', cursor: 'pointer',
              borderBottom: '1.5px solid ' + (isActive ? T.ink : 'transparent'),
              color: isActive ? T.ink : T.ink3, fontFamily: fontStack, fontSize: 12,
              fontWeight: isActive ? 500 : 400, whiteSpace: 'nowrap', flex: '0 0 auto',
              marginBottom: -0.5,
            }}>
              {t.swatch && <span style={{ width: 6, height: 6, borderRadius: 1, background: t.swatch }} />}
              {t.label}
              <span style={{ fontFamily: monoStack, fontSize: 9.5, color: T.ink3 }}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px 6px' }}>
        {filtered.length === 0 ? (
          <div style={{
            padding: '40px 20px', textAlign: 'center', color: T.ink3,
            fontFamily: monoStack, fontSize: 10.5, letterSpacing: '.04em', textTransform: 'uppercase',
          }}>No tickets in this window</div>
        ) : filtered.map(tk => {
          const cat = window.TRIAGE_CAT_BY_ID[tk.cat];
          const fu = followups[tk.id];
          const nt = notes[tk.id];
          const due = fu && (fu.dueAt - Date.now()) <= 0;
          return (
            <div key={tk.id} style={{
              padding: '10px 8px',
              borderBottom: '0.5px solid ' + T.lineSoft,
              borderLeft: due ? '2px solid ' + T.accent : '2px solid transparent',
              cursor: 'pointer', display: 'flex', gap: 9, alignItems: 'flex-start',
              background: due ? (T.dark ? 'rgba(255,77,46,.05)' : 'rgba(255,77,46,.03)') : 'transparent',
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = T.hover}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
            >
              <div style={{ paddingTop: 4 }}>
                <CatDot catId={tk.cat} size={8} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 6, marginBottom: 3 }}>
                  <span style={{
                    fontFamily: fontStack, fontSize: 12.5, color: T.ink, fontWeight: 500,
                    letterSpacing: '-0.005em', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    flex: 1, minWidth: 0,
                  }}>{tk.title}</span>
                  <Mono style={{ color: T.ink3, fontSize: 9.5, flex: '0 0 auto' }}>
                    {window.formatAgo(tk.updatedAgoMin)}
                  </Mono>
                </div>

                {tweaks.showSummary && (
                  <div style={{
                    fontFamily: fontStack, fontSize: 11.5, lineHeight: 1.4, color: T.ink2,
                    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                    marginBottom: 5,
                  }}>{tk.summary}</div>
                )}

                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <Mono style={{ color: T.ink3, fontSize: 9.5 }}>{cat.label}</Mono>
                  <Mono style={{ color: T.ink3, fontSize: 9.5 }}>·</Mono>
                  <span style={{ fontFamily: fontStack, fontSize: 10.5, color: T.ink2,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 110 }}>
                    {tk.customer}
                  </span>
                  {fu && (
                    <Mono style={{
                      color: due ? T.accent : T.ink2, fontSize: 9.5,
                      animation: due ? 'triagePulse 1.4s ease-in-out infinite' : 'none',
                    }}>· {window.formatCountdown(fu.dueAt - Date.now())}</Mono>
                  )}
                  {nt && (
                    <Mono style={{ color: T.ink3, fontSize: 9.5 }}>· notes</Mono>
                  )}
                  {tweaks.showConfidence && (
                    <Mono style={{
                      color: tk.conf < 0.5 ? '#c34a2b' : T.ink3, fontSize: 9.5, marginLeft: 'auto',
                    }}>{Math.round(tk.conf * 100)}%</Mono>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* footer */}
      <div style={{
        padding: '8px 12px', borderTop: '0.5px solid ' + T.line, background: T.bg,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <Mono style={{ color: T.ink3 }}>shared with webapp</Mono>
        <Mono style={{ color: T.ink3 }}>●&nbsp;synced</Mono>
      </div>
    </div>
  );
}

window.TriagePopup = TriagePopup;
