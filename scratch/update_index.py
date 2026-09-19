from pathlib import Path

src_path = Path('extracted_GridVision/package_windows/GridVision_OpenDSS_app.html')
dst_path = Path('static/index.html')

content = src_path.read_text(encoding='utf-8')

# Inject Download OpenDSS (.dss) button into top tabs bar
btn_html = '''
<div style="margin-left:auto; display:flex; align-items:center; gap:10px; padding-right:10px;">
  <button id="btnExportDSS" onclick="const kva = document.getElementById('transformerKvaSel') ? document.getElementById('transformerKvaSel').value : 250; window.location.href='/api/export/dss?transformer_kva=' + kva;" style="padding:6px 14px; background:linear-gradient(135deg,#0891b2,#6366f1); color:#fff; border-radius:8px; border:none; font-weight:700; font-size:12px; cursor:pointer; box-shadow:0 0 12px rgba(34,211,238,0.3);">
    📥 Download OpenDSS (.dss)
  </button>
</div>
'''

if 'id="tabs"' in content:
    content = content.replace('id="tabs">', 'id="tabs">' + btn_html, 1)
else:
    # Inject sticky top right button
    sticky_btn = '''
    <button id="btnExportDSS" onclick="window.location.href='/api/export/dss'" style="position:fixed; top:10px; right:180px; z-index:99999; padding:8px 16px; background:linear-gradient(135deg,#0891b2,#6366f1); color:#fff; border-radius:8px; font-weight:700; font-size:12px; cursor:pointer; border:none; box-shadow:0 0 16px rgba(34,211,238,0.4);">
      📥 Download OpenDSS (.dss)
    </button>
    '''
    content = content.replace('<body>', '<body>' + sticky_btn, 1)

dst_path.parent.mkdir(parents=True, exist_ok=True)
dst_path.write_text(content, encoding='utf-8')
print("Successfully generated static/index.html from full app template!")
