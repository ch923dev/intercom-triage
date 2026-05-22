// Main app — wraps both surfaces in a DesignCanvas with a Tweaks panel.

const { useState: useStateA } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "dark": false,
  "accent": "#ff4d2e",
  "density": "balanced",
  "showSummary": true,
  "showConfidence": true,
  "columnLayout": "operator-pick"
}/*EDITMODE-END*/;

const ACCENT_OPTIONS = ['#ff4d2e', '#1a1a1a', '#4338ca', '#0e8a4c', '#b45309'];

// Browser-popup chrome — frames the chrome extension popup so it reads as a real popover
function PopupChrome({ tweaks }) {
  const T = window.triageTokens(tweaks.dark, tweaks.accent);
  return (
    <div style={{
      width: '100%', height: '100%', background: tweaks.dark ? '#1e1f23' : '#e8e6df',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      fontFamily: window.triageFontStack,
    }}>
      {/* fake browser chrome */}
      <div style={{
        flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px 8px',
        background: tweaks.dark ? '#26272c' : '#dad6cc', borderBottom: '0.5px solid rgba(0,0,0,.15)',
      }}>
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={{ width: 10, height: 10, borderRadius: 5, background: '#ff5f57' }} />
          <span style={{ width: 10, height: 10, borderRadius: 5, background: '#febc2e' }} />
          <span style={{ width: 10, height: 10, borderRadius: 5, background: '#28c840' }} />
        </div>
        <div style={{
          flex: 1, marginLeft: 12, padding: '4px 10px', borderRadius: 4,
          background: tweaks.dark ? '#16171b' : '#f4f1e9',
          border: '0.5px solid rgba(0,0,0,.1)',
          fontFamily: window.triageMonoStack, fontSize: 10,
          color: tweaks.dark ? '#a3a39d' : '#555', letterSpacing: '.02em',
        }}>app.intercom.com / inbox</div>
        {/* extensions icon — popup origin */}
        <div style={{
          width: 22, height: 22, borderRadius: 4,
          border: '1px solid ' + tweaks.accent,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: tweaks.dark ? '#1e1f23' : '#fff',
          position: 'relative',
        }}>
          <span style={{ width: 6, height: 6, background: tweaks.accent, display: 'block' }} />
        </div>
      </div>

      {/* popup positioned below the icon */}
      <div style={{ flex: 1, position: 'relative', padding: '6px 14px 14px' }}>
        {/* connector arrow */}
        <div style={{
          position: 'absolute', top: -1, right: 22, width: 10, height: 10,
          background: T.bg, border: '0.5px solid ' + T.line,
          borderBottom: 0, borderRight: 0, transform: 'rotate(45deg)',
          zIndex: 2,
        }} />
        <div style={{
          width: '100%', height: '100%',
          background: T.bg, border: '0.5px solid ' + T.line, borderRadius: 6,
          boxShadow: '0 8px 28px rgba(0,0,0,.18)',
          overflow: 'hidden', position: 'relative',
        }}>
          <window.TriagePopup tweaks={tweaks} />
        </div>
      </div>
    </div>
  );
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  // Inject Google fonts once
  React.useEffect(() => {
    if (!document.getElementById('triage-fonts')) {
      const link = document.createElement('link');
      link.id = 'triage-fonts';
      link.rel = 'stylesheet';
      link.href = 'https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap';
      document.head.appendChild(link);
    }
  }, []);

  return (
    <>
      <DesignCanvas initialZoom={0.55}>
        <DCSection id="surfaces" title="Triage" subtitle="Recency-windowed Kanban view of recent Intercom conversations · webapp + chrome extension popup">
          <DCArtboard id="webapp" label="Webapp · /triage" width={1440} height={900}>
            <window.TriageWebapp tweaks={t} />
          </DCArtboard>
          <DCArtboard id="popup" label="Chrome popup · 380×560" width={420} height={620}>
            <PopupChrome tweaks={t} />
          </DCArtboard>
        </DCSection>
      </DesignCanvas>

      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakToggle label="Dark mode" value={t.dark} onChange={(v) => setTweak('dark', v)} />
        <TweakColor label="Accent" value={t.accent} options={ACCENT_OPTIONS}
          onChange={(v) => setTweak('accent', v)} />

        <TweakSection label="Card density" />
        <TweakRadio value={t.density} options={['compact','balanced','comfy']}
          onChange={(v) => setTweak('density', v)} />

        <TweakSection label="Display" />
        <TweakToggle label="Show AI summary" value={t.showSummary}
          onChange={(v) => setTweak('showSummary', v)} />
        <TweakToggle label="Show AI confidence" value={t.showConfidence}
          onChange={(v) => setTweak('showConfidence', v)} />
      </TweaksPanel>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
