/* All tool state comes from Core; the browser only renders and submits controls. */
(() => {
  const panel = document.getElementById('toolCabinetPanel');
  if (!panel) return;
  const root = document.getElementById('toolInventory');
  const status = document.getElementById('toolControlStatus');
  let updating = false;
  const element = (tag, text) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function button(text, action) {
    const node = element('button', text);
    node.type = 'button';
    node.onclick = action;
    return node;
  }
  function stateText(tool) {
    if (!tool.enabled) return '已停用';
    if (!tool.available) return '依赖不可用';
    return tool.exposed ? '本轮已携带' : '可按需使用';
  }
  function filesystemAccess(data, kind) {
    const isWrite = kind === 'write';
    const field = isWrite ? 'write_directories' : 'read_directories';
    const box = element('div');
    box.className = 'notice filesystem-access';
    box.append(element('strong', isWrite ? '可修改目录' : '可读取目录'));
    box.append(element('p', isWrite
      ? '每行一个绝对路径；必须位于可读取目录内，建议只开放确实需要修改的最小子目录。'
      : '每行一个已存在的绝对路径。可修改目录必须包含在这些目录中。'));
    const input = element('textarea');
    input.rows = 4;
    input.value = (data.filesystem_access?.[field] || []).join('\n');
    input.placeholder = isWrite ? '例如：E:\\项目\\朝汐\\输出' : '例如：E:\\资料\nE:\\项目';
    input.setAttribute('aria-label', isWrite ? 'Filesystem 可修改目录' : 'Filesystem 可读取目录');
    const message = element('p', '保存后需要重启 Core 才会生效。');
    message.className = 'sub';
    box.append(input, button('保存目录', async () => {
      const directories = input.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
      if (!directories.length) { message.textContent = '请至少填写一个目录。'; return; }
      const body = {
        read_directories: data.filesystem_access.read_directories,
        write_directories: data.filesystem_access.write_directories,
      };
      body[field] = directories;
      try {
        const result = await request('/api/tools/filesystem-access', {
          method: 'PUT', body: JSON.stringify(body),
        });
        data.filesystem_access.read_directories = result.read_directories;
        data.filesystem_access.write_directories = result.write_directories;
        input.value = result[field].join('\n');
        message.textContent = result.message;
      } catch (error) { message.textContent = `保存失败：${error.message}`; }
    }), message);
    return box;
  }
  function render(data) {
    const opened = new Set([...root.querySelectorAll('details[open]')].map(node => node.dataset.group));
    root.replaceChildren();
    const s = data.summary;
    status.textContent = `${s.registered_tools} 把钥匙 · ${s.enabled_tools} 把启用 · ${s.available_tools} 把可用`;
    for (const group of data.groups) {
      const section = element('details');
      section.dataset.group = group.group;
      section.open = opened.has(group.group);
      section.append(element('summary', `${group.summary}（${group.registered}）`));
      const scope = {scope: 'group', target: group.group};
      section.append(
        button('启用本组', () => change({...scope, enabled: true})),
        button('停用本组', () => change({...scope, enabled: false})),
        button('恢复本组默认', () => change({...scope, reset: true})),
      );
      if (group.group === 'filesystem_read') {
        section.append(filesystemAccess(data, 'read'));
      } else if (group.group === 'filesystem_write') {
        section.append(filesystemAccess(data, 'write'));
      }
      for (const tool of data.tools.filter(item => item.group === group.group)) {
        const row = element('div');
        row.className = 'notice';
        row.append(element('strong', tool.display_name || tool.name));
        const identifier = element('small', tool.name);
        identifier.className = 'sub tool-identifier';
        row.append(identifier, element('p', tool.usage || tool.summary));
        row.append(element('p', `状态：${stateText(tool)}`));
        for (const [key, title] of [['enabled', '启用'], ['force_expose', '每轮携带']]) {
          const label = element('label');
          const input = element('input');
          input.type = 'checkbox';
          input.checked = tool[key];
          input.setAttribute('aria-label', `${tool.display_name || tool.name} ${title}`);
          input.onchange = () => change({scope: 'tool', target: tool.name, [key]: input.checked});
          label.append(input, document.createTextNode(`${title} `));
          row.append(label);
        }
        if (tool.write_capable) {
          const label = element('label');
          const input = element('input');
          input.type = 'checkbox';
          input.checked = tool.confirm_write;
          input.setAttribute('aria-label', `${tool.display_name || tool.name} 写入前确认`);
          input.onchange = () => change({scope: 'tool', target: tool.name, confirm_write: input.checked});
          label.append(input, document.createTextNode('写入前确认 '));
          row.append(label);
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
    catch (error) { status.textContent = `读取失败：${error.message}`; }
    finally { updating = false; }
  }
  async function change(body) {
    if (updating) return;
    updating = true;
    panel.querySelectorAll('#toolControls button, #toolControls input, #toolControls textarea')
      .forEach(node => { node.disabled = true; });
    try {
      render(await request('/api/debug/tools/control', {method: 'POST', body: JSON.stringify(body)}));
    } catch (error) {
      try { render(await request('/api/debug/tools')); } catch {}
      status.textContent = `修改失败：${error.message}`;
    } finally {
      updating = false;
      panel.querySelectorAll('#toolControls button, #toolControls input, #toolControls textarea')
        .forEach(node => { node.disabled = false; });
    }
  }
  panel.addEventListener('toggle', () => { if (panel.open) void refresh(); });
  document.getElementById('refreshTools').onclick = refresh;
  document.getElementById('resetTools').onclick = () => change({scope: 'all', reset: true});
  setInterval(() => { if (panel.open && !document.hidden) void refresh(); }, 5000);
})();
