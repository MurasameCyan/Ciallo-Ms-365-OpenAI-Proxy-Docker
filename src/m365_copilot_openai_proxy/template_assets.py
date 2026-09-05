from __future__ import annotations

_GLASS_SELECT_CSS = """select.glass-native{position:absolute!important;opacity:0!important;pointer-events:none!important;width:1px!important;height:1px!important;margin:0!important;padding:0!important}
.glass-select{position:relative;display:inline-block;min-width:120px;vertical-align:middle;z-index:20}
.glass-select.open{z-index:80}
.tone-select+.glass-select{min-width:180px}
.glass-select-trigger{width:100%;min-height:30px;margin:0!important;padding:.42rem 2rem .42rem .7rem!important;border-radius:12px!important;color:var(--strong)!important;text-align:left!important;background:linear-gradient(135deg,rgba(255,255,255,.13),rgba(96,242,255,.08),rgba(140,107,255,.08))!important;border:1px solid rgba(96,242,255,.28)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.2),0 8px 20px rgba(0,0,0,.12)!important;backdrop-filter:blur(14px);position:relative;overflow:hidden;transition:none!important}
.glass-select-trigger:after{content:"";position:absolute;right:.72rem;top:50%;width:.46rem;height:.46rem;border-right:2px solid var(--cyan);border-bottom:2px solid var(--cyan);transform:translateY(-65%) rotate(45deg);opacity:.9}
.glass-select.open .glass-select-trigger{border-color:rgba(96,242,255,.58)!important;box-shadow:0 0 0 2px rgba(96,242,255,.12),0 0 20px rgba(96,242,255,.18),inset 0 1px 0 rgba(255,255,255,.24)!important}
/* Near-opaque on purpose: the menu opens inside a `.card`, and a card carrying
   `backdrop-filter` is its own backdrop root, so the menu's own blur never
   samples the card content behind it. At .82 alpha the card text read straight
   through the option list. */
.glass-select-menu{position:absolute;left:0;right:auto;top:calc(100% + 6px);min-width:100%;width:max-content;max-width:min(460px,calc(100vw - 32px));overflow:visible;border-radius:14px;padding:.28rem;background:linear-gradient(180deg,rgba(13,19,45,.97),rgba(7,11,27,.96));border:1px solid rgba(96,242,255,.28);box-shadow:0 18px 44px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.12);backdrop-filter:blur(22px) saturate(145%);display:none}
.glass-select-scroll{max-height:min(60vh,420px);overflow-y:auto;border-radius:10px;scrollbar-width:none;-ms-overflow-style:none}
.glass-select-scroll::-webkit-scrollbar{width:0;height:0;display:none}
.tone-select+.glass-select .glass-select-menu{left:auto;right:0}
.glass-select.open .glass-select-menu{display:block}
.glass-select-menu:before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(90deg,var(--cyan),var(--violet),var(--pink),var(--gold),var(--cyan));background-size:260% 100%;animation:flowBorder 2.2s linear infinite;-webkit-mask:linear-gradient(#fff 0 0) content-box,linear-gradient(#fff 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;opacity:.75}
.glass-select-option{position:relative;width:100%;margin:0!important;padding:.48rem .62rem!important;border-radius:10px!important;background:transparent!important;color:var(--muted)!important;box-shadow:none!important;text-align:left!important;font-size:.82rem!important;line-height:1.2!important;white-space:nowrap!important;transition:none!important}
.glass-select-option:hover{background:linear-gradient(135deg,rgba(96,242,255,.18),rgba(140,107,255,.13))!important;color:var(--text)!important;transform:none!important}
.glass-select-option.active{color:var(--text)!important;background:linear-gradient(135deg,rgba(96,242,255,.24),rgba(255,94,219,.12))!important;box-shadow:inset 3px 0 0 rgba(96,242,255,.82)!important}
/* Tool-calling status on a mode option (see initGlassSelect's `mark`). The option
   button and trigger set `color` with !important, but a declaration on the span
   itself still beats an inherited one, so these need no !important of their own.
   Same three hues as the call log's states, and `font-variant-emoji:text` backs
   up the U+FE0E in the glyph -- a colour-emoji font would ignore `color`. */
.tc-mark{margin-left:.34rem;font-variant-emoji:text}
.tc-mark[data-tc="verified"]{color:#22c55e}
.tc-mark[data-tc="router"],.tc-mark[data-tc="flaky"]{color:#f59e0b}
.tc-mark[data-tc="unsupported"]{color:#ef4444}
body[data-theme="light"] .glass-select-trigger{color:#1c1c1e!important;background:linear-gradient(135deg,rgba(255,255,255,.88),rgba(0,122,255,.06))!important;border-color:rgba(60,60,67,.14)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.92),0 4px 12px rgba(0,0,0,.04)!important}
body[data-theme="light"] .glass-select-menu{background:linear-gradient(180deg,rgba(255,255,255,.98),rgba(242,243,247,.97));border-color:rgba(60,60,67,.12);box-shadow:0 16px 36px rgba(0,0,0,.1),inset 0 1px 0 rgba(255,255,255,.92)}
body[data-theme="light"] .glass-select-option{color:#6b6b70!important}
body[data-theme="light"] .glass-select-option:hover,body[data-theme="light"] .glass-select-option.active{color:#1c1c1e!important}"""

# Hide the browser-native up/down spinner on number inputs so they match the
# other text inputs / custom glass-selects. Shared by both the admin and user
# templates (concatenated after _GLASS_SELECT_CSS).
_NO_SPIN_CSS = """
input[type=number]{appearance:textfield;-moz-appearance:textfield}
input[type=number]::-webkit-outer-spin-button,input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}"""

# A field whose caveat is long enough to unbalance its row keeps it in a hover
# bubble instead of a paragraph under the input: two of these hints ran 3-5
# lines, so the column they sat in was taller than its neighbours and every row
# below them stopped lining up. The trigger is a circled "!" drawn in CSS (no
# per-row SVG to repeat), amber like the other warnings, and `tabindex` goes on
# the trigger so the text is reachable without a pointer. Shared by the admin and
# user templates -- both pages carry the same fields now, so the two must not be
# allowed to drift apart. The bubble spans its containing block, so whatever
# wraps the field needs `position:relative` (see .runtime-field-label /
# .user-config-field).
_FIELD_TIP_CSS = """
.field-row{display:flex;align-items:center;gap:.45rem;min-width:0;width:100%}
.field-tip{flex:none;margin-left:auto;display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;border-radius:50%;border:1.5px solid #fbbf24;color:#fbbf24;font-size:.7rem;font-weight:900;line-height:1;cursor:help}
.field-tip:before{content:"!"}
.field-tip:hover,.field-tip:focus,.field-tip:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(251,191,36,.18)}
/* Hidden with opacity alone, not `visibility`/`display`: at opacity 0 the text
   stays in the accessibility tree, so a screen reader still reads the caveat
   that sighted users get on hover. pointer-events:none keeps it click-through. */
.field-tip-bubble{position:absolute;top:calc(100% + 8px);left:0;right:0;z-index:140;padding:.55rem .65rem;border-radius:10px;font-size:.75rem;font-weight:600;line-height:1.6;white-space:normal;text-align:left;color:var(--text);background:linear-gradient(180deg,rgba(13,19,45,.98),rgba(7,11,27,.97));border:1px solid rgba(251,191,36,.32);box-shadow:0 16px 38px rgba(0,0,0,.42);opacity:0;pointer-events:none;transition:opacity .14s ease}
.field-tip:hover .field-tip-bubble,.field-tip:focus .field-tip-bubble,.field-tip:focus-within .field-tip-bubble{opacity:1}
/* For a field sitting on the last row of its card, opening downwards would leave
   the card -- that one flips above the field. */
.field-tip.tip-up .field-tip-bubble{top:auto;bottom:calc(100% + 8px)}
/* A bubble that lists several options gets one block per option: run together as
   one paragraph they were a wall of text at this width. The bold term is the very
   key the <option> uses, so the two can never disagree. */
.field-tip-bubble .tip-line{display:block}
.field-tip-bubble .tip-line+.tip-line{margin-top:.42rem}
.field-tip-bubble .tip-line b{color:#fbbf24;font-weight:800}
.field-tip-bubble .tip-line b:after{content:"："}
body[data-lang="en"] .field-tip-bubble .tip-line b:after{content:": "}
body[data-theme="light"] .field-tip-bubble .tip-line b{color:#b45309}
/* `.card` clips to its rounded corners, which would cut the bubble off at the
   card edge -- same escape hatch the open glass-select menu uses. */
.card:has(.field-tip:hover),.card:has(.field-tip:focus),.card:has(.field-tip:focus-within){overflow:visible!important;z-index:2100}
body[data-theme="light"] .field-tip-bubble{color:#1c1c1e;background:linear-gradient(180deg,rgba(255,255,255,.99),rgba(242,243,247,.98));border-color:rgba(180,83,9,.28);box-shadow:0 14px 30px rgba(0,0,0,.12)}
body[data-theme="light"] .field-tip{border-color:#b45309;color:#b45309}"""

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

# The dashboard donut rings hold still: the shares are a static colour band and
# the only motion left is the blurred halo behind them breathing. Kept out of
# _STILL_DECOR_CSS on purpose -- this is the one piece of ambient motion that was
# asked for back after the freeze, so it is spelled out here with what it costs.
#
# What it replaces, in order: nine SMIL <animate> elements per ring sliding each
# arc's stroke-dashoffset (82% of a core in style recalculation), then one stepped
# CSS rotation of a wrapper <g> (9%), now nothing on the ring itself (0%) plus a
# stepped opacity breath on the halo group.
#
# The stepping carries over from the rotation unchanged, because an always-on
# animation here is priced per frame drawn, not per property changed. Measured on
# the live dashboard, idle, whole Chrome process tree:
#
#     linear (continuous, 60fps)   115-137%   of one CPU core
#     steps(60)  ~92ms per notch       9%
#     steps(36) ~153ms per notch       6%
#     steps(24) ~229ms per notch       3%
#     not animating at all             0%
#
# The cost is not the filters and not the compositor. Stripping every SVG
# filter still left 104%, `will-change`/`contain` made it worse (142%), and even
# with every `backdrop-filter` on the page disabled it was 97%. The donut sits
# in a stack of 37 backdrop-filter surfaces that cannot be composited, so each
# frame is a real repaint of that stack -- the only lever left is drawing fewer
# frames.
#
# steps() on a keyframe list runs per segment, so 14 steps across a 5.6s cycle
# that goes .62 -> 1 -> .62 is 28 notches of ~200ms each, which the table above
# prices between 3% and 6%. Only the halo group carries it: the coloured band is
# what a reader measures shares against, and opacity on an already-blurred layer
# never invalidates layout the way the old SMIL stroke-width breathing did.
#
# ponytail: 14 notches is read off the table above as the cheapest rate that
# still breathes rather than blinks, not derived. One notch is ~0.027 of opacity
# on a layer blurred by 4px, well under where stepping becomes visible. If the
# rings get larger or the cycle gets shorter, re-measure.
_DONUT_BREATHE_CSS = """
.donut-breathe{animation:donutBreath 5.6s steps(14,end) infinite}
@keyframes donutBreath{0%,100%{opacity:.62}50%{opacity:1}}"""

_GLASS_SELECT_JS = """function initGlassSelect(root){
  const scope=root||document;
  scope.querySelectorAll('select').forEach(sel=>{
    if(sel.dataset.glassReady==='1')return;
    sel.dataset.glassReady='1';sel.classList.add('glass-native');
    const wrap=document.createElement('span');wrap.className='glass-select';
    if(sel.classList.contains('page-select'))wrap.style.minWidth='76px';
    if(sel.classList.contains('tone-select'))wrap.style.minWidth='180px';
    // A select asking for width:100% is sized by its container, so the wrapper
    // that replaces it has to fill that container too -- otherwise the trigger
    // and its menu sit narrower than the box drawn around them (the sessions
    // user filter measured 180px inside a 200px .flow-box).
    if(sel.style.width==='100%')wrap.style.width='100%';
    const trigger=document.createElement('button');trigger.type='button';trigger.className='glass-select-trigger';
    const menu=document.createElement('div');menu.className='glass-select-menu';
    wrap.appendChild(trigger);wrap.appendChild(menu);sel.parentNode.insertBefore(wrap,sel.nextSibling);
    const close=()=>wrap.classList.remove('open');
    // An option may carry data-tc (a tool-calling status): render it as a coloured
    // wrench after the copied label. It cannot ride along inside textContent --
    // a colour needs its own element -- and it must not be colour ALONE, so the
    // option's title travels with it for anyone who cannot tell the hues apart.
    // U+FE0E asks for the monochrome glyph; without it a colour-emoji font paints
    // its own wrench and ignores `color` entirely.
    const mark=o=>{
      if(!o||!o.dataset.tc)return null;
      const s=document.createElement('span');s.className='tc-mark';s.dataset.tc=o.dataset.tc;s.textContent='\U0001F527︎';return s;
    };
    const paint=(el,o)=>{el.textContent=o?o.textContent:'';const m=mark(o);if(m)el.appendChild(m);el.title=(o&&o.title)||''};
    const render=()=>{
      const opt=sel.options[sel.selectedIndex];paint(trigger,opt);menu.innerHTML='';
      const scroll=document.createElement('div');scroll.className='glass-select-scroll';
      Array.from(sel.options).forEach(o=>{const b=document.createElement('button');b.type='button';b.className='glass-select-option'+(o.value===sel.value?' active':'');paint(b,o);b.onclick=e=>{e.stopPropagation();sel.value=o.value;sel.dispatchEvent(new Event('change',{bubbles:true}));render();close()};scroll.appendChild(b)});
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
