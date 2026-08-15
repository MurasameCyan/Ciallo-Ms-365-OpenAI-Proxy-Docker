from __future__ import annotations

_GLASS_SELECT_CSS = """select.glass-native{position:absolute!important;opacity:0!important;pointer-events:none!important;width:1px!important;height:1px!important;margin:0!important;padding:0!important}
.glass-select{position:relative;display:inline-block;min-width:120px;vertical-align:middle;z-index:20}
.glass-select.open{z-index:80}
.tone-select+.glass-select{min-width:180px}
.glass-select-trigger{width:100%;min-height:30px;margin:0!important;padding:.42rem 2rem .42rem .7rem!important;border-radius:12px!important;color:var(--strong)!important;text-align:left!important;background:linear-gradient(135deg,rgba(255,255,255,.13),rgba(96,242,255,.08),rgba(140,107,255,.08))!important;border:1px solid rgba(96,242,255,.28)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.2),0 8px 20px rgba(0,0,0,.12)!important;backdrop-filter:blur(14px);position:relative;overflow:hidden;transition:none!important}
.glass-select-trigger:after{content:"";position:absolute;right:.72rem;top:50%;width:.46rem;height:.46rem;border-right:2px solid var(--cyan);border-bottom:2px solid var(--cyan);transform:translateY(-65%) rotate(45deg);opacity:.9}
.glass-select.open .glass-select-trigger{border-color:rgba(96,242,255,.58)!important;box-shadow:0 0 0 2px rgba(96,242,255,.12),0 0 20px rgba(96,242,255,.18),inset 0 1px 0 rgba(255,255,255,.24)!important}
.glass-select-menu{position:absolute;left:0;right:auto;top:calc(100% + 6px);min-width:100%;width:max-content;max-width:min(460px,calc(100vw - 32px));overflow:visible;border-radius:14px;padding:.28rem;background:linear-gradient(180deg,rgba(13,19,45,.82),rgba(7,11,27,.78));border:1px solid rgba(96,242,255,.28);box-shadow:0 18px 44px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(145%);display:none}
.glass-select-scroll{max-height:min(60vh,420px);overflow-y:auto;border-radius:10px;scrollbar-width:none;-ms-overflow-style:none}
.glass-select-scroll::-webkit-scrollbar{width:0;height:0;display:none}
.tone-select+.glass-select .glass-select-menu{left:auto;right:0}
.glass-select.open .glass-select-menu{display:block}
.glass-select-menu:before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan));background-size:260% 100%;animation:flowBorder 2.2s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;opacity:.75}
.glass-select-option{position:relative;width:100%;margin:0!important;padding:.48rem .62rem!important;border-radius:10px!important;background:transparent!important;color:var(--muted)!important;box-shadow:none!important;text-align:left!important;font-size:.82rem!important;line-height:1.2!important;white-space:nowrap!important;transition:none!important}
.glass-select-option:hover{background:linear-gradient(135deg,rgba(96,242,255,.18),rgba(140,107,255,.13))!important;color:var(--text)!important;transform:none!important}
.glass-select-option.active{color:var(--text)!important;background:linear-gradient(135deg,rgba(96,242,255,.24),rgba(255,94,219,.12))!important;box-shadow:inset 3px 0 0 rgba(96,242,255,.82)!important}
body[data-theme="light"] .glass-select-trigger{color:#1c1c1e!important;background:linear-gradient(135deg,rgba(255,255,255,.88),rgba(0,122,255,.06))!important;border-color:rgba(60,60,67,.14)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.92),0 4px 12px rgba(0,0,0,.04)!important}
body[data-theme="light"] .glass-select-menu{background:linear-gradient(180deg,rgba(255,255,255,.94),rgba(242,243,247,.9));border-color:rgba(60,60,67,.12);box-shadow:0 16px 36px rgba(0,0,0,.1),inset 0 1px 0 rgba(255,255,255,.92)}
body[data-theme="light"] .glass-select-option{color:#6b6b70!important}
body[data-theme="light"] .glass-select-option:hover,body[data-theme="light"] .glass-select-option.active{color:#1c1c1e!important}"""

# Hide the browser-native up/down spinner on number inputs so they match the
# other text inputs / custom glass-selects. Shared by both the admin and user
# templates (concatenated after _GLASS_SELECT_CSS).
_NO_SPIN_CSS = """
input[type=number]{appearance:textfield;-moz-appearance:textfield}
input[type=number]::-webkit-outer-spin-button,input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}"""

# Stop the always-on decoration from spinning, and let the OS opt out of the
# rest. Appended last by every page so it wins over the rules above.
#
# WHY: each page stacks blurred surfaces -- a fixed `filter:blur()` `.orb`
# behind cards carrying `backdrop-filter`. A blur only stays cheap while its
# source holds still; the moment anything in that stack moves, every blurred
# surface is re-derived per frame in the GPU process. Measured against a live
# deployment with Chrome, on a completely idle page: login view 49% of a CPU
# core, signed-in user view 69%, admin 85%. Freezing the animations took all
# three to ~2%.
#
# It is about what the animation touches, not which property moves: an
# opacity-only fade on the blurred orb still cost 52%, while a transform on an
# unblurred element cost 2%. So the ambient decor -- decoration that runs
# forever with no user interaction -- is frozen at a representative frame, and
# `.orb` keeps a static rotation so it does not sit at the keyframe origin.
#
# Interaction-driven motion is deliberately untouched: :hover / :focus / [open]
# / .loading animations only run while someone is actually interacting, which is
# brief, and that is where the motion carries meaning. Two things that look like
# interaction states but are not:
#
#   - `.nav-item.active::after`: `.active` marks the current page, so it is set
#     from load and never clears. The selected tab swept forever.
#   - the `autofocus` field on the login pages: its focus sweep starts on its own
#     the instant the page opens, with nobody interacting, and measured 43% of a
#     core on /admin. It animates `background-position`, which no compositor can
#     take over, so the sweep is dropped for the autofocused field only -- the
#     focus border and glow it shares with every other field still apply, and
#     clicking any field (including that one, once it is blurred and refocused)
#     still sweeps.
#
# ponytail: frozen rather than made cheap. Keeping the motion would mean
# dropping `backdrop-filter` off the cards and pre-blurring the orb into its own
# gradient -- a redesign of the glass look, not an optimisation. Revisit only if
# the ambient motion is wanted back.
_STILL_DECOR_CSS = """
.orb,.brand-mark:before,.brand-mark:after,.brand-mark::before,.brand-mark::after,
.account-side:before,.debug-gate:before,.data-globe:before,.data-globe:after,
.flow-box::after,.brand .tenant-pill:before,.tone-share-fill,.glass-select-menu:before,
.nav-item.active::after,.nav-item.active:after,
.card:has(details[open])::after,.debug-gate-card:has(.debug-gate.on)::after{animation:none!important}
.orb{transform:translate(-50%,-50%) rotate(150deg)!important}
.debug-gate.on .data-globe,.debug-gate.on .orbit,.debug-gate.on .gate-flow{animation:none!important}
[autofocus]:focus{animation:none!important}
@media(prefers-reduced-motion:reduce){
*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}
}"""

# The dashboard donut rings rotate. Kept out of _STILL_DECOR_CSS on purpose:
# this is the one piece of ambient motion that was asked for back after the
# freeze, so it is spelled out here with what it costs.
#
# Two changes make it affordable. First, one CSS rotation of a wrapper <g>
# replaces the nine SMIL <animate> elements that used to slide each arc's
# stroke-dashoffset. Same look -- every arc moving at the same speed through a
# full circumference IS a rotation -- but style recalculation goes to 0% of a
# core, from 82%.
#
# Second, and this is the part that actually matters: the rotation is stepped,
# not continuous. Measured on the live dashboard, idle, whole Chrome process
# tree:
#
#     linear (continuous, 60fps)   115-137%   of one CPU core
#     steps(60)  ~92ms per notch       9%
#     steps(36) ~153ms per notch       6%
#     steps(24) ~229ms per notch       3%
#     not rotating at all              0%
#
# The cost is not the filters and not the compositor. Stripping every SVG
# filter still left 104%, `will-change`/`contain` made it worse (142%), and even
# with every `backdrop-filter` on the page disabled it was 97%. The donut sits
# in a stack of 37 backdrop-filter surfaces that cannot be composited, so each
# frame is a real repaint of that stack -- the only lever left is drawing fewer
# frames. steps(60) advances every ~92ms, which reads as smooth rotation at this
# size while costing 13x less than continuous.
#
# ponytail: 60 notches is picked as the cheapest count that still looks
# continuous at 120px, not derived. Fewer notches keep helping until they become
# visible as stepping (steps(12) measured 11%, worse than 24 and 36 -- below
# ~24 the repaint per notch grows faster than the frame count falls). If the
# rings ever need to be larger, re-measure rather than assuming 60 still holds.
_DONUT_SPIN_CSS = """
.donut-spin{transform-origin:60px 60px;animation:donutSpin 5.5s steps(60,end) infinite}
@keyframes donutSpin{to{transform:rotate(360deg)}}"""

_GLASS_SELECT_JS = """function initGlassSelect(root){
  const scope=root||document;
  scope.querySelectorAll('select').forEach(sel=>{
    if(sel.dataset.glassReady==='1')return;
    sel.dataset.glassReady='1';sel.classList.add('glass-native');
    const wrap=document.createElement('span');wrap.className='glass-select';
    if(sel.classList.contains('page-select'))wrap.style.minWidth='76px';
    if(sel.classList.contains('tone-select'))wrap.style.minWidth='180px';
    if(sel.id==='rebind-select')wrap.style.width='100%';
    const trigger=document.createElement('button');trigger.type='button';trigger.className='glass-select-trigger';
    const menu=document.createElement('div');menu.className='glass-select-menu';
    wrap.appendChild(trigger);wrap.appendChild(menu);sel.parentNode.insertBefore(wrap,sel.nextSibling);
    const close=()=>wrap.classList.remove('open');
    const render=()=>{
      const opt=sel.options[sel.selectedIndex];trigger.textContent=opt?opt.textContent:'';menu.innerHTML='';
      const scroll=document.createElement('div');scroll.className='glass-select-scroll';
      Array.from(sel.options).forEach(o=>{const b=document.createElement('button');b.type='button';b.className='glass-select-option'+(o.value===sel.value?' active':'');b.textContent=o.textContent;b.onclick=e=>{e.stopPropagation();sel.value=o.value;sel.dispatchEvent(new Event('change',{bubbles:true}));render();close()};scroll.appendChild(b)});
      menu.appendChild(scroll);
    };
    sel._glassRender=render;
    trigger.onclick=e=>{e.stopPropagation();document.querySelectorAll('.glass-select.open').forEach(x=>{if(x!==wrap)x.classList.remove('open')});render();wrap.classList.toggle('open')};
    sel.addEventListener('change',render);render();
  });
}
function refreshGlassSelect(sel){
  if(!sel)return;
  if(sel.dataset.glassReady!=='1')initGlassSelect(sel.parentElement||document);
  if(typeof sel._glassRender==='function')sel._glassRender();
}
document.addEventListener('click',()=>document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open')));
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.glass-select.open').forEach(x=>x.classList.remove('open'))});"""
