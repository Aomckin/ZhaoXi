(() => {
  const panel = document.querySelector('#emojiCabinetPanel');
  if (!panel) return;
  const grid = document.querySelector('#emojiGrid');
  const pendingGrid = document.querySelector('#emojiPendingGrid');
  const status = document.querySelector('#emojiCabinetStatus');
  const editor = document.querySelector('#emojiEditor');
  let items = [], pending = [], showAll = false, editing = null, editingDataUrl = null;

  const metadata = () => ({
    description: document.querySelector('#emojiDescription').value.trim(),
    tags: document.querySelector('#emojiTags').value.split(/[,，]/).map(value => value.trim()).filter(Boolean),
    emotion: document.querySelector('#emojiEmotion').value.trim() || null,
    intensity: Number(document.querySelector('#emojiIntensity').value),
    enabled: document.querySelector('#emojiEnabled').checked,
  });
  const fill = value => {
    document.querySelector('#emojiDescription').value = value.description || '';
    document.querySelector('#emojiTags').value = (value.tags || []).join('，');
    document.querySelector('#emojiEmotion').value = value.emotion || '';
    document.querySelector('#emojiIntensity').value = value.intensity ?? .5;
    document.querySelector('#emojiIntensityValue').textContent = value.intensity ?? .5;
    document.querySelector('#emojiEnabled').checked = value.enabled !== false;
  };
  const fileDataUrl = file => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file);
  });
  const urlDataUrl = async url => fileDataUrl(await (await fetch(url)).blob());

  function render() {
    const visible = showAll ? items : items.slice(0, 6);
    grid.replaceChildren(...visible.map(item => {
      const button = document.createElement('button'); button.type = 'button';
      button.className = `emoji-card${item.enabled ? '' : ' disabled'}`;
      button.innerHTML = `<img src="${item.url}" alt=""><small>${escapeHtml(item.emotion || item.tags[0] || item.id)}</small><small>${escapeHtml(item.tags.join(' · '))}</small>`;
      button.onclick = () => openEditor({kind: 'emoji', item}); return button;
    }));
    pendingGrid.replaceChildren(...pending.map(item => {
      const card = document.createElement('div'); card.className = 'emoji-card';
      card.innerHTML = `<img src="${item.url}" alt="待整理表情"><small>${escapeHtml(item.suggestion ? item.suggestion.tags.join(' · ') : item.pending_id)}</small><button type="button">${item.suggestion ? '确认' : '整理'}</button> <button type="button" class="deny">丢弃</button>`;
      card.querySelector('button').onclick = () => openEditor({kind: 'pending', item});
      card.querySelector('.deny').onclick = async () => { await request(`/api/emoji/pending/${item.pending_id}`, {method: 'DELETE'}); await load(); };
      return card;
    }));
    document.querySelector('#emojiCount').textContent = `${items.length} 张`;
    document.querySelector('#emojiPendingCount').textContent = String(pending.length);
    document.querySelector('#emojiViewAll').textContent = showAll ? '只看最近' : '查看全部';
  }
  async function load() {
    try {
      const query = encodeURIComponent(document.querySelector('#emojiSearch').value.trim());
      const [library, inbox] = await Promise.all([request(`/api/emoji?q=${query}`), request('/api/emoji/pending')]);
      items = library.items; pending = inbox.items;
      status.textContent = `已收藏 ${library.count} 张，待整理 ${inbox.count} 张。`; render();
    } catch (error) { status.textContent = error.message; }
  }
  async function openEditor(target) {
    editing = target; editingDataUrl = null;
    const item = target.item, isPending = target.kind === 'pending';
    document.querySelector('#emojiEditorImage').src = item.url;
    document.querySelector('#emojiEditorId').textContent = isPending ? `待整理 · ${item.pending_id}` : item.id;
    fill(isPending ? (item.suggestion || {intensity: .5, enabled: true}) : item);
    document.querySelector('#emojiDelete').textContent = isPending ? '丢弃' : '删除表情';
    document.querySelector('#emojiEditorStatus').textContent = '';
    editor.showModal();
  }
  async function analyze(target = editing) {
    if (!target) return null;
    document.querySelector('#emojiEditorStatus').textContent = '朝汐正在看看这张图……';
    try {
      editingDataUrl = target === editing && editingDataUrl ? editingDataUrl : await urlDataUrl(target.item.url);
      const result = await request('/api/emoji/analyze', {method: 'POST', body: JSON.stringify({data_url: editingDataUrl, hint: ''})});
      if (target === editing) fill({...result, enabled: true});
      document.querySelector('#emojiEditorStatus').textContent = '识别结果已填好，确认后再保存。';
      return result;
    } catch (error) { document.querySelector('#emojiEditorStatus').textContent = error.message; return null; }
  }

  panel.addEventListener('toggle', () => { if (panel.open) void load(); });
  document.querySelector('#emojiRefresh').onclick = load;
  document.querySelector('#emojiSearch').oninput = load;
  document.querySelector('#emojiViewAll').onclick = () => { showAll = !showAll; render(); };
  document.querySelector('#emojiAdd').onclick = () => document.querySelector('#emojiFiles').click();
  async function importFiles(files) {
    status.textContent = '正在放入待整理区……';
    for (const file of files) {
      try { await request('/api/emoji/pending', {method: 'POST', body: JSON.stringify({data_url: await fileDataUrl(file)})}); }
      catch (error) { status.textContent = error.message; }
    }
    await load();
  }
  document.querySelector('#emojiFiles').onchange = async event => {
    await importFiles(event.target.files); event.target.value = '';
  };
  panel.addEventListener('dragover', event => { event.preventDefault(); });
  panel.addEventListener('drop', event => { event.preventDefault(); void importFiles(event.dataTransfer.files); });
  document.querySelector('#emojiIntensity').oninput = event => document.querySelector('#emojiIntensityValue').textContent = event.target.value;
  document.querySelector('#emojiAnalyze').onclick = () => analyze();
  document.querySelector('#emojiSave').onclick = async () => {
    if (!editing) return;
    const body = metadata();
    if (!body.description || !body.tags.length) { document.querySelector('#emojiEditorStatus').textContent = '请填写描述和至少一个标签。'; return; }
    try {
      if (editing.kind === 'pending') await request(`/api/emoji/pending/${editing.item.pending_id}/commit`, {method: 'POST', body: JSON.stringify(body)});
      else await request(`/api/emoji/${editing.item.id}`, {method: 'PATCH', body: JSON.stringify(body)});
      editor.close(); await load();
    } catch (error) { document.querySelector('#emojiEditorStatus').textContent = error.message; }
  };
  document.querySelector('#emojiDelete').onclick = async () => {
    if (!editing || !confirm(editing.kind === 'pending' ? '丢弃这张待整理图片吗？' : '确定从朝汐的表情柜里删除这张表情吗？')) return;
    const url = editing.kind === 'pending' ? `/api/emoji/pending/${editing.item.pending_id}` : `/api/emoji/${editing.item.id}`;
    await request(url, {method: 'DELETE'}); editor.close(); await load();
  };
  document.querySelector('#emojiOrganizeAll').onclick = async () => {
    const suggestions = [];
    for (const item of pending) {
      const result = await analyze({kind: 'pending', item});
      if (!result) break;
      item.suggestion = result; suggestions.push({item, result}); render();
    }
    status.textContent = `已识别 ${suggestions.length} 张；结果尚未入库，请逐张打开确认。`;
  };
})();
