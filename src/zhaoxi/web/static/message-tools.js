// Local message interactions: no second session, upload, or model request.
(function () {
  const viewer = document.createElement('dialog');
  viewer.id = 'imageViewer';
  viewer.setAttribute('aria-label', '图片查看器');
  viewer.innerHTML = `<div class="viewer-toolbar"><button data-view="out" aria-label="缩小">−</button><button data-view="in" aria-label="放大">＋</button><button data-view="fit">适应窗口</button><button data-view="actual">原始大小</button><span class="viewer-scale" aria-live="polite"></span><button data-view="close" aria-label="关闭图片查看器">×</button></div><div class="viewer-stage"><img alt="放大查看的图片" draggable="false"></div><p class="viewer-help">滚轮缩放 · 拖动查看 · Esc 关闭</p>`;
  document.body.append(viewer);
  const stage = viewer.querySelector('.viewer-stage'), picture = stage.querySelector('img');
  let zoom = 1, x = 0, y = 0, dragging = null, lastFocus = null;
  function paint() {
    picture.style.width = `${picture.naturalWidth * zoom}px`;
    picture.style.height = `${picture.naturalHeight * zoom}px`;
    picture.style.transform = `translate(calc(-50% + ${x}px),calc(-50% + ${y}px))`;
    viewer.querySelector('.viewer-scale').textContent = `${Math.round(zoom * 100)}%`;
  }
  function fit() {
    zoom = Math.min(1, stage.clientWidth / (picture.naturalWidth || 1), stage.clientHeight / (picture.naturalHeight || 1));
    x = y = 0; paint();
  }
  function scale(factor) { zoom = Math.max(.05, Math.min(10, zoom * factor)); paint(); }
  function close() { viewer.close(); }
  picture.onload = fit;
  picture.onerror = () => { close(); showActivityHint('图片读取失败'); };
  viewer.addEventListener('close', () => { picture.removeAttribute('src'); dragging = null; stage.classList.remove('dragging'); lastFocus?.focus(); lastFocus = null; });
  viewer.addEventListener('click', event => {
    const action = event.target.closest('[data-view]')?.dataset.view;
    if (action === 'close' || event.target === viewer) close();
    if (action === 'in') scale(1.25);
    if (action === 'out') scale(.8);
    if (action === 'fit') fit();
    if (action === 'actual') { zoom = 1; x = y = 0; paint(); }
  });
  stage.addEventListener('wheel', event => { event.preventDefault(); scale(event.deltaY < 0 ? 1.15 : 1 / 1.15); }, {passive: false});
  stage.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    dragging = {id: event.pointerId, px: event.clientX, py: event.clientY, x, y};
    stage.setPointerCapture(event.pointerId); stage.classList.add('dragging'); event.preventDefault();
  });
  stage.addEventListener('pointermove', event => {
    if (!dragging || dragging.id !== event.pointerId) return;
    x = dragging.x + event.clientX - dragging.px; y = dragging.y + event.clientY - dragging.py; paint();
  });
  const stopDrag = () => { dragging = null; stage.classList.remove('dragging'); };
  stage.addEventListener('pointerup', stopDrag); stage.addEventListener('pointercancel', stopDrag);
  window.addEventListener('resize', () => { if (viewer.open) fit(); });

  const menu = document.createElement('div');
  menu.id = 'messageMenu'; menu.hidden = true; menu.setAttribute('role', 'menu');
  document.body.append(menu);
  let target = null;
  function hideMenu(restore = false) { if (menu.hidden) return; menu.hidden = true; const row = target?.row; target = null; if (restore) row?.focus(); }
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const previous = document.activeElement, selection = previous?.selectionStart;
      const helper = document.createElement('textarea'); helper.value = text;
      helper.style.cssText = 'position:fixed;opacity:0;pointer-events:none'; document.body.append(helper);
      helper.select(); const copied = document.execCommand('copy'); helper.remove(); previous?.focus();
      if (selection != null) previous.setSelectionRange(selection, selection);
      if (!copied) throw new Error('clipboard unavailable');
    }
  }
  async function copyImage(src) {
    if (!navigator.clipboard?.write || !window.ClipboardItem) throw new Error('clipboard unavailable');
    // Start the clipboard write within the click; PNG conversion may finish later.
    const blob = (async () => {
      const image = new Image(); image.src = src; await image.decode();
      const canvas = document.createElement('canvas'); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
      canvas.getContext('2d').drawImage(image, 0, 0);
      const result = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      if (!result) throw new Error('image conversion failed');
      return result;
    })();
    await navigator.clipboard.write([new ClipboardItem({'image/png': blob})]);
  }
  let activeReference = null;
  const draftReference = document.createElement('div'); draftReference.id = 'draftReference'; draftReference.hidden = true;
  document.querySelector('#imagePreview')?.before(draftReference);
  function referenceCard(reference, cancel) {
    const box = document.createElement('div'); box.className = 'message-reference';
    const link = document.createElement('button'); link.type = 'button'; link.className = 'reference-link';
    const name = document.createElement('strong'), preview = document.createElement('span');
    name.textContent = (reference.role === 'user' ? '我' : '朝汐') + (reference.timestamp ? ' · ' + formatTime(reference.timestamp) : '') + ' ↗';
    preview.textContent = reference.text || (reference.image_count ? `[图片 · ${reference.image_count}张]` : '原消息');
    link.append(name,preview); link.setAttribute('aria-label','查看引用的原消息');
    link.onclick = async () => {
      if (document.documentElement.dataset.windowMode === 'companion') {
        try { await window.pywebview.api.command('mode','main'); }
        catch { showActivityHint('请展开主窗口查看原消息'); return; }
      }
      await openReply(reference.message_id, reference.part_index);
      const rows = [...document.querySelectorAll('#messages [data-message-id]')];
      const row = rows.find(item => item.dataset.messageId === reference.message_id &&
        (reference.part_index == null || Number(item.dataset.messagePartIndex) === reference.part_index));
      if (row) { row.scrollIntoView({block:'center',behavior:'smooth'}); row.classList.add('reference-highlight'); setTimeout(()=>row.classList.remove('reference-highlight'),1800); }
    };
    box.append(link);
    if (cancel) { const button = document.createElement('button'); button.type='button';button.className='reference-cancel';button.textContent='×';button.setAttribute('aria-label','取消引用');button.onclick=()=>setReference(null);box.append(button); }
    return box;
  }
  function setReference(value) {
    activeReference = value; draftReference.replaceChildren(); draftReference.hidden = !value;
    if (value) draftReference.append(referenceCard(value,true));
  }
  function quote(info) {
    if (info.quoteTarget) info = {...info.quoteTarget.messageInfo, row:info.quoteTarget,
      images:[...info.quoteTarget.querySelectorAll('img.attachment')]};
    const messageId = info.row.dataset.messageId;
    if (!messageId || info.row.dataset.pending === 'true') { showActivityHint('这条消息发送完成后才能引用'); return; }
    setReference({message_id:messageId,
      part_index:info.row.dataset.messagePartIndex == null ? null : Number(info.row.dataset.messagePartIndex),
      role:info.role,text:info.text.slice(0,500),image_count:info.images.length,timestamp:info.timestamp});
    input.focus();
  }
  menu.addEventListener('click', async event => {
    const action = event.target.closest('button')?.dataset.action, info = target;
    if (!action || !info) return;
    hideMenu();
    if (action === 'quote') { quote(info); return; }
    try {
      if (action === 'copy') await copyText(info.text);
      if (action === 'image') await copyImage(info.image || info.images[0]);
      showActivityHint(action === 'image' ? '图片已复制' : '文字已复制');
    } catch { showActivityHint('复制失败，请使用系统复制或稍后重试'); }
  });
  menu.addEventListener('keydown', event => {
    const buttons = [...menu.querySelectorAll('button')], index = buttons.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); hideMenu(true); }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault(); buttons[(index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus();
    }
  });
  document.addEventListener('pointerdown', event => { if (!menu.contains(event.target)) hideMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hideMenu(true); });
  document.addEventListener('scroll', () => hideMenu(), true);
  window.addEventListener('blur', () => hideMenu());
  window.MessageTools = {
    takeReference() { const value=activeReference;setReference(null);return value; },
    clearReference() { setReference(null); },
    attachReference(row, reference) {
      if (!reference) return;
      row.querySelector('.bubble,.image-only')?.prepend(referenceCard(reference,false));
    },
    open(src, focus) { hideMenu(); lastFocus = focus || document.activeElement; viewer.showModal(); picture.src = src; },
    bind(row, info) {
      row.messageInfo = info;
      row.tabIndex = 0;
      const images = [...row.querySelectorAll('img.attachment')];
      const openMenu = (clientX, clientY, image) => {
        target = {...info, row, images: images.map(item => item.getAttribute('src')), image};
        menu.replaceChildren();
        const options = [['quote', '引用消息']];
        if (String(info.text || '').trim()) options.push(['copy', '复制文字']);
        if (images.length) options.push(['image', '复制图片']);
        for (const [action, label] of options) {
          const button = document.createElement('button'); button.textContent = label; button.dataset.action = action; button.setAttribute('role', 'menuitem'); menu.append(button);
        }
        menu.hidden = false;
        menu.style.left = `${Math.max(8, Math.min(clientX, innerWidth - menu.offsetWidth - 8))}px`;
        menu.style.top = `${Math.max(8, Math.min(clientY, innerHeight - menu.offsetHeight - 8))}px`;
        menu.querySelector('button').focus();
      };
      row.addEventListener('contextmenu', event => { event.preventDefault(); openMenu(event.clientX, event.clientY, event.target.closest('img.attachment')?.getAttribute('src')); });
      row.addEventListener('keydown', event => {
        if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
          event.preventDefault(); const rect = row.getBoundingClientRect(); openMenu(rect.left + 16, rect.top + 16);
        }
      });
      for (const image of images) {
        image.tabIndex = 0; image.setAttribute('role', 'button'); image.setAttribute('aria-label', image.alt + '，点击放大查看');
        image.onclick = () => window.MessageTools.open(image.getAttribute('src'), image);
        image.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); image.click(); } };
      }
    },
  };
})();
