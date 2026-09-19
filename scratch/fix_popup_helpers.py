from pathlib import Path

html_path = Path('static/index.html')
content = html_path.read_text(encoding='utf-8')

helpers_js = '''
<script>
window.popupHtml = function(p) {
  if (!p) return "";
  const is_tf = p.is_tf ? " (Transformer)" : "";
  const load = (p.load_kw != null) ? p.load_kw + " kW" : "0 kW";
  const solar = (p.solar_kw != null) ? p.solar_kw + " kW" : "0 kW";
  const feeder = p.feeder || "—";
  return "<div style=\'font-family:DM Sans,sans-serif; color:#e2e8f0; font-size:12px; line-height:1.5;\'>"
    + "<div style=\'font-weight:700; font-size:14px; color:#22d3ee; margin-bottom:4px;\'>Pole " + p.id + is_tf + "</div>"
    + "<div><span style=\'color:#94a3b8;\'>Feeder:</span> <b>" + feeder + "</b></div>"
    + "<div><span style=\'color:#94a3b8;\'>Load:</span> <b>" + load + "</b></div>"
    + "<div><span style=\'color:#94a3b8;\'>Solar PV:</span> <b>" + solar + "</b></div>"
    + "</div>";
};

window.showPoleVoltagePanel = function(p) {
  if (!p) return;
  const panel = document.getElementById("polePhasePanel");
  if (panel) panel.style.display = "block";
  const title = document.getElementById("polePhaseTitle");
  if (title) title.textContent = "Pole " + p.id + (p.is_tf ? " (TF)" : "");
  const v = p.V_noon || p.V_peak || {Va: 230, Vb: 230, Vc: 230};
  if (document.getElementById("mVa")) document.getElementById("mVa").textContent = (v.Va || "—") + " V";
  if (document.getElementById("mVb")) document.getElementById("mVb").textContent = (v.Vb || "—") + " V";
  if (document.getElementById("mVc")) document.getElementById("mVc").textContent = (v.Vc || "—") + " V";
};
</script>
'''

if '</head>' in content:
    content = content.replace('</head>', helpers_js + '\n</head>', 1)

html_path.write_text(content, encoding='utf-8')
print("Successfully injected popupHtml & showPoleVoltagePanel helper functions into static/index.html!")
