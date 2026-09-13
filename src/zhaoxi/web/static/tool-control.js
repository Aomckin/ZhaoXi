/* All tool state comes from the Core manifest; no browser-owned tool list. */
(() => {
  const panel = document.getElementById('toolDebugPanel');
  if (!panel) return;
  const root = document.getElementById('toolInventory');
  const status = document.getElementById('toolControlStatus');
  let updating = false;
  const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
  function button(text, action) { const node = element('button', text); node.type = 'button'; node.onclick = action; return node; }
  function render(data) {
    const opened = new Set([...root.querySelectorAll('details[open]')].map(node => node.dataset.group));
    root.replaceChildren();
    const s = data.summary;
    status.textContent = `已注册 ${s.registered_tools} · 启用 ${s.enabled_tools} · 依赖可用 ${s.available_tools} · 当前携带 ${s.currently_exposed}`;
    for (const group of data.groups) {
      const section = element('details'); section.dataset.group = group.group; section.open = opened.has(group.group);
      section.append(element('summary', `${group.summary} · ${group.group} (${group.registered})`));
      const scope = {scope: 'group', target: group.group};
      section.append(button('启用整组', () => change({...scope, enabled: true})), button('停用整组', () => change({...scope, enabled: false})), button('组恢复默认', () => change({...scope, reset: true})));
      for (const tool of data.tools.filter(t => t.group === group.group)) {
        const row = element('div'); row.className = 'notice';
        row.append(element('strong', tool.name), element('p', tool.summary));
        row.append(element('p', `来源 ${tool.source} · 分组 ${tool.group} · 注册 ${tool.registered ? '是' : '否'} · 启用 ${tool.enabled ? '是' : '否'} · 依赖可用 ${tool.available ? '是' : '否'} · 常驻 ${tool.persistent ? '是' : '否'} · 当前携带 ${tool.exposed ? '是' : '否'}`));
        for (const [key, title] of [['enabled', '启用'], ['force_expose', 'Force Expose · 每轮携带']]) {
          const label = element('label'); const input = element('input'); input.type = 'checkbox'; input.checked = tool[key];
          input.setAttribute('aria-label', `${tool.name} ${title}`);
          input.onchange = () => change({scope: 'tool', target: tool.name, [key]: input.checked});
          label.append(input, document.createTextNode(title + ' ')); row.append(label);
        }
        row.append(button('恢复默认', () => change({scope: 'tool', target: tool.name, reset: true})));
        section.append(row);
      }
      root.append(section);
    }
  }
  async function refresh() {
    if (updating) return;
    updating = true;
    try { render(await request('/api/debug/tools')); }
    catch (e) { status.textContent = `读取失败：${e.message}`; }
    finally { updating = false; }
  }
  async function change(body) {
    if (updating) return;
    updating = true;
    panel.querySelectorAll('#toolControls button, #toolControls input').forEach(node => node.disabled = true);
    try { render(await request('/api/debug/tools/control', {method: 'POST', body: JSON.stringify(body)})); }
    catch (e) {
      const error = e.message;
      try { render(await request('/api/debug/tools')); } catch {}
      status.textContent = `修改失败：${error}`;
    } finally {
      updating = false;
      panel.querySelectorAll('#toolControls button, #toolControls input').forEach(node => node.disabled = false);
    }
  }
  panel.addEventListener('toggle', () => { if (panel.open) void refresh(); });
  document.getElementById('refreshTools').onclick = refresh;
  document.getElementById('resetTools').onclick = () => change({scope: 'all', reset: true});
  setInterval(() => { if (panel.open && !document.hidden) void refresh(); }, 5000);
})();
