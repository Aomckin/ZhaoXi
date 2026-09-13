// This is a projection of the existing conversation, never a second session.
(function () {
  const root = document.documentElement;
  const chrome = document.createElement('header');
  chrome.id = 'windowChrome';
  chrome.innerHTML = '<span id="windowTitle">🌻 朝汐 ZhaoXi</span><button id="foldWindow" title="陪伴模式" aria-label="陪伴模式">◱</button><button id="windowMenu" aria-label="窗口菜单">⋯</button><button id="minWindow" aria-label="最小化">_</button><button id="maxWindow" aria-label="最大化或还原">□</button><button id="hideWindow" class="close" aria-label="隐藏朝汐">×</button>';
  document.body.append(chrome);
  const menu = document.createElement('div');
  menu.id = 'shellMenu'; menu.hidden = true;
  menu.innerHTML = '<label><input type="checkbox" id="windowTopmost"> 陪伴窗口置顶</label><button id="compactAttach">添加图片</button><button id="compactVoice" hidden>语音输入</button>';
  document.body.append(menu);
  const surface = document.createElement('section');
  surface.id = 'currentConversation'; surface.setAttribute('aria-label','当前对话');
  document.querySelector('.chat').prepend(surface);
  const footer = document.createElement('footer');
  footer.id = 'companionFooter';
  footer.innerHTML = '<button id="compactDesk">小桌边</button><button id="expandWindow">↗ 展开</button>';
  document.body.append(footer);
  const command = async (action, value) => {
    try { return await window.pywebview.api.command(action,value); }
    catch (error) { showActivityHint('窗口操作暂未完成，请重试'); }
  };
  let mainScroll = 0;
  window.desktopShellState = state => {
    const previous = root.dataset.windowMode;
    if (previous !== state.mode && state.mode === 'companion') {
      mainScroll = document.querySelector('#messages').scrollTop;
      toggleDesk(false);
    }
    root.dataset.desktop = 'true'; root.dataset.windowMode = state.mode;
    document.querySelector('#maxWindow').textContent = state.mode === 'companion' ? '↗' : '□';
    document.querySelector('#maxWindow').setAttribute('aria-label',state.mode === 'companion' ? '展开主界面' : '最大化或还原');
    document.querySelector('#foldWindow').hidden = state.mode === 'companion';
    document.querySelector('#windowTopmost').checked = state.topmost;
    document.querySelector('#windowTopmost').disabled = state.mode !== 'companion';
    if (previous !== state.mode) {
      menu.hidden = true;
      if (state.mode === 'main') document.querySelector('#messages').scrollTop = mainScroll;
      document.querySelector('#input').focus();
    }
    renderCurrent();
  };
  function renderCurrent() {
    if (root.dataset.windowMode !== 'companion') return;
    const rows = Array.from(document.querySelectorAll('#messages .row:not(.system)'));
    const latestUser = rows.findLastIndex(row => row.classList.contains('user'));
    const recent = latestUser < 0 ? rows.slice(-2) : rows.slice(latestUser);
    surface.replaceChildren();
    for (const role of ['user','assistant']) {
      let selected = recent.filter(row => row.classList.contains(role));
      if (role === 'assistant' && !selected.length) {
        const previous = rows.findLast(row => row.classList.contains('assistant'));
        if (previous) selected = [previous];
      }
      if (!selected.length) continue;
      const article = document.createElement('article'), name = document.createElement('strong'), text = document.createElement('p');
      article.dataset.role = role;
      name.textContent = role === 'user' ? '你' : '朝汐';
      text.textContent = selected.map(row => {
        const copy = row.querySelector('.bubble').cloneNode(true);
        copy.querySelectorAll('time,button').forEach(el => el.remove());
        copy.querySelectorAll('img').forEach(el => el.replaceWith(document.createTextNode('[图片]')));
        copy.querySelectorAll('br').forEach(el => el.replaceWith(document.createTextNode('\n')));
        return copy.textContent;
      }).join('\n').slice(0,1000);
      article.append(name,text); surface.append(article);
    }
    if (!surface.childElementCount) surface.textContent = '我在这里，慢慢说。';
    const expand = document.createElement('button');
    expand.textContent = document.querySelector('#messages .permission') ? '有待确认操作 · 展开主界面处理' : '展开主界面查看完整内容';
    expand.onclick = () => command('mode','main'); surface.append(expand);
    document.querySelector('#compactDesk').textContent = document.querySelector('#proactiveNotes .note-unread') ? '● 小桌边有新留言' : '小桌边';
  }
  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued || root.dataset.windowMode !== 'companion') return;
    queued = true; requestAnimationFrame(() => { queued = false; renderCurrent(); });
  });
  for (const id of ['messages','proactiveNotes','interactionBadge']) observer.observe(document.getElementById(id), {childList:true,subtree:true,characterData:true});
  document.querySelector('#foldWindow').onclick = () => command('mode','companion');
  document.querySelector('#expandWindow').onclick = () => command('mode','main');
  document.querySelector('#maxWindow').onclick = () => command('maximize');
  document.querySelector('#minWindow').onclick = () => command('minimize');
  document.querySelector('#hideWindow').onclick = () => command('hide');
  document.querySelector('#windowMenu').onclick = () => { menu.hidden = !menu.hidden; document.querySelector('#compactVoice').hidden = !voiceEnabled; };
  document.querySelector('#compactAttach').onclick = () => { menu.hidden = true; document.querySelector('#attachImage').click(); };
  document.querySelector('#compactVoice').onclick = () => { menu.hidden = true; document.querySelector('#mic').click(); };
  document.querySelector('#windowTopmost').onchange = event => command('topmost',event.target.checked);
  document.querySelector('#compactDesk').onclick = async () => { await command('mode','main'); toggleDesk(true); };
  window.desktopOpenSettings = () => { toggleDesk(true); document.querySelectorAll('.desk-tools>details')[1].open = true; };
  // Defer drag until movement so double clicks are handled by our mode rules.
  const title = document.querySelector('#windowTitle');
  let drag = null;
  title.onpointerdown = event => { if (event.button === 0) drag = [event.clientX,event.clientY]; };
  title.onpointermove = event => {
    if (drag && event.buttons === 1 && Math.abs(event.clientX-drag[0])+Math.abs(event.clientY-drag[1]) > 4) {
      drag = null; command('gesture','move');
    }
  };
  window.addEventListener('pointerup',() => { drag = null; });
  title.ondblclick = () => { drag = null; command('maximize'); };
  for (const edge of ['left','right','top','bottom','top-left','top-right','bottom-left','bottom-right']) {
    const zone = document.createElement('div'); zone.className = 'resize-zone'; zone.dataset.edge = edge;
    zone.onpointerdown = event => { if (event.button === 0) { event.preventDefault(); command('gesture',edge); } };
    document.body.append(zone);
  }
  document.addEventListener('keydown',event => {
    if (event.key === 'Escape' && root.dataset.windowMode === 'companion') { event.preventDefault(); command('hide'); }
  });
  window.addEventListener('pywebviewready',async () => { const state = await command('state'); if (state) window.desktopShellState(state); });
})();
