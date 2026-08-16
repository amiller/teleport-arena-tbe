#!/usr/bin/env python3
"""A live view of the playtest loop. Run it, leave the tab open, watch agents play.

    python3 dashboard.py [port]        # default 8765

It binds the overlay address, so the page is watchable from the phone and from zed but not
from the LAN — it can start and stop agents, which is more than the LAN should be offered.

Three things update on their own:
  - one LIVE pane per player, a screenshot of that player's running simulation refreshed
    every second (run-attempt.sh drops one into its own out/live.png as it goes; the zed
    agents' frames are carried across by sync-agents.sh)
  - the attempt log, appended by `tbe.py solve` as each verdict comes back
  - the console's agent, whose status is polled from paseo on zed

The console runs one zai agent at a time, in its own worktree on zed, and stops it.
"""
import calendar
import html
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
ZLOGS = HERE / "zlogs"
AGENT = OUT / "agent.json"
# Only if it looks like a port. This is read at import time, so any other module that
# imports the dashboard for its prompt or its attempt parsing used to crash on whatever
# flags that module happened to be passed -- which is how the overnight loop died on
# startup with "invalid literal for int(): --levels".
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8765
BIND = os.environ.get("BIND", "127.0.0.1")
ZED = os.environ.get("REMOTE", "")            # ssh host running the agents, or "" for none
REPO_ON_ZED = os.environ.get("REMOTE_REPO", "~/teleport-arena-tbe")
FRESH = 20                            # a frame older than this is not a live one
AWAKE_MINUTES = 10                    # the recorder stops this long after you stop watching

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Teleport Arena — playtest</title>
<style>
:root{--ground:#E3E9DE;--card:#fff;--ink:#1A212B;--rule:#CBD6C6;--dim:#5D6B62;
      --win:#0E9C90;--bad:#D2492A;--live:#EFB01F}
@media(prefers-color-scheme:dark){:root{--ground:#14181A;--card:#1D2326;--ink:#E9EFE7;
      --rule:#2E3739;--dim:#A7B4AE;--win:#1FBFB0;--bad:#F0674A;--live:#F5C542}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
     font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:26px 18px 60px;display:flex;flex-direction:column;gap:22px}
h1{font-size:26px;letter-spacing:-.025em;margin:0;font-weight:800}
.eyebrow{font:600 10.5px/1 ui-monospace,Menlo,monospace;letter-spacing:.17em;
         text-transform:uppercase;color:var(--dim)}
.grid{display:grid;grid-template-columns:1.35fr 1fr;gap:18px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.players{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px}
.player figcaption{padding:9px 2px 0;display:flex;flex-direction:column;gap:3px}
.player .cardname{display:flex;gap:7px;align-items:baseline}
.player .who{margin-left:0;white-space:nowrap}
/* Everything arriving here is already cropped to the 602x406 playfield by run-attempt.sh,
   so the frame and the clip are the game and nothing else -- no menu bar, no toolbox
   column, no fps counter. Clips recorded before that change are wider and simply letterbox.
*/
.shot{overflow:hidden;aspect-ratio:602/406;border:1.5px solid var(--rule);border-radius:3px;
      background:#000;display:flex;align-items:center}
.shot img.live,.shot video,.shot img.thumb{width:100%;display:block;border:none;
  border-radius:0;position:static}
.shot img.thumb{aspect-ratio:602/406;object-fit:cover}
.player.stale img.live{opacity:.4;filter:grayscale(1)}
.age{font:11px ui-monospace,Menlo,monospace;color:var(--dim)}
.age.on{color:var(--live)}
.console{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
.console select{flex:1;min-width:210px;padding:7px 8px;border:1.5px solid var(--rule);
  border-radius:3px;background:var(--ground);color:var(--ink);font:13px ui-monospace,Menlo,monospace}
#playbtn{background:var(--win);border-color:var(--win);color:#fff}
.console button{padding:8px 15px;border:1.5px solid var(--ink);border-radius:3px;
  background:var(--ink);color:var(--ground);font:700 12px ui-monospace,Menlo,monospace;cursor:pointer}
.console button.ghost{background:transparent;color:var(--ink)}
.console button[disabled]{opacity:.4;cursor:default}
#agent{margin-top:11px;font:12.5px ui-monospace,Menlo,monospace;color:var(--dim)}
#agent .err{color:var(--bad);white-space:pre-wrap}
.clipinfo{display:none}
.dl{display:grid;grid-template-columns:110px 1fr;gap:12px;padding:9px 0;
  border-bottom:1px solid var(--rule);font-size:13.5px;align-items:baseline}
.dl:last-child{border-bottom:none}
.dl>span:first-child{font:600 10.5px/1.7 ui-monospace,Menlo,monospace;letter-spacing:.12em;
  text-transform:uppercase;color:var(--dim)}
.dl code{word-break:break-all}
#rec{margin-top:5px;font:12.5px ui-monospace,Menlo,monospace;color:var(--dim)}
.rec{color:var(--live)}
.rec.off{color:var(--dim)}
.panel{background:var(--card);border:1.5px solid var(--rule);border-radius:3px;padding:15px}
.panel h2{font:600 10.5px/1 ui-monospace,Menlo,monospace;letter-spacing:.16em;
          text-transform:uppercase;color:var(--dim);margin:0 0 11px}
img.live{width:100%;height:auto;border:1.5px solid var(--rule);border-radius:3px;display:block;background:#000}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--live);
     margin-right:7px;animation:p 1.1s ease-in-out infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
.att{border-bottom:1px solid var(--rule);padding:11px 0;display:flex;flex-direction:column;gap:4px}
.att:last-child{border-bottom:none}
.att .top{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.att .lvl{font-weight:700;font-size:14px}
.att .t{font:11px ui-monospace,Menlo,monospace;color:var(--dim)}
.att .pl{font:12.5px ui-monospace,Menlo,monospace;color:var(--dim)}
.v{font:700 11px/1.7 ui-monospace,Menlo,monospace;padding:1px 8px;border-radius:2px;letter-spacing:.04em}
.v.ok{background:var(--win);color:#fff}.v.no{background:var(--bad);color:#fff}
.v.run{background:var(--live);color:#1A212B}
.v.copied{background:#8A6A1F;color:#fff}
.v.crash{background:#5D6B62;color:#fff}
.v.author{background:transparent;color:var(--dim);border:1.5px solid var(--rule)}
.gallery .cardname{display:flex;gap:7px;align-items:baseline;justify-content:space-between}
.gallery video{cursor:pointer}
.empty{color:var(--dim);font-size:13.5px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:15px}
.gallery .card{margin:0;padding:0;border:1.5px solid var(--rule);border-radius:3px;overflow:hidden;background:var(--card)}
.gallery video{width:100%;display:block;border:none;border-radius:0;border-bottom:1.5px solid var(--rule)}
.gallery .norec{aspect-ratio:19/12;display:flex;align-items:center;justify-content:center;
     color:var(--dim);font:12px ui-monospace,Menlo,monospace;background:var(--ground);
     border-bottom:1.5px solid var(--rule)}
.gallery figcaption{padding:10px 12px;display:flex;flex-direction:column;gap:3px}
.cardname{font-weight:700;font-size:13.5px;letter-spacing:-.01em}
.cardpl{font:11.5px ui-monospace,Menlo,monospace;color:var(--dim);word-break:break-all}
.gallery .who{align-self:flex-start;margin-left:0}
.now{border-left:4px solid var(--live)}
.nowlvl{font-weight:700;font-size:16px;letter-spacing:-.01em}
.steps{margin:9px 0 0;padding-left:19px;font:12.5px ui-monospace,Menlo,monospace;color:var(--dim)}
.steps li{padding:1px 0}
.steps li:last-child{color:var(--ink);font-weight:700}
.who{font:600 9.5px/1.7 ui-monospace,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;
     margin-left:8px;padding:1px 6px;border-radius:2px;border:1.5px solid var(--rule);color:var(--dim)}
.pills{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:11px}
.pill{font:600 11.5px/1 ui-monospace,Menlo,monospace;padding:6px 10px;border-radius:2px;
      border:1.5px solid var(--rule);color:var(--dim);text-decoration:none;
      background:transparent;cursor:pointer}
.pill.on{background:var(--ink);color:var(--ground);border-color:var(--ink)}
video{width:100%;border:1.5px solid var(--rule);border-radius:3px;display:block}
.stat{display:flex;gap:22px;flex-wrap:wrap;margin-bottom:4px}
.stat .v2{font:800 24px/1 ui-monospace,Menlo,monospace}
.stat .k{font-size:11.5px;color:var(--dim)}
.statusbar{font:12.5px ui-monospace,Menlo,monospace;color:var(--dim);
  border:1.5px solid var(--rule);border-left:4px solid var(--rule);border-radius:3px;
  padding:9px 13px;background:var(--card)}
.statusbar .hot{color:var(--live);font-weight:700}
.statusbar .bad{color:var(--bad);font-weight:700}
.statusbar .dim{color:var(--dim)}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;flex-wrap:wrap}
/* The player is the point of the page, so it is the first thing under the title and it is
   big. Everything below it is a way of choosing what goes in it. */
.stage h2{display:flex;align-items:center;gap:10px;justify-content:space-between}
.stage img.live,.stage video{width:100%;display:block;border:1.5px solid var(--rule);
  border-radius:3px;background:#000}
.live-pill{display:none}
.live-pill.show{display:inline-block}
details.panel summary{font:600 10.5px/1 ui-monospace,Menlo,monospace;letter-spacing:.16em;
  text-transform:uppercase;color:var(--dim);cursor:pointer}
details.panel[open] summary{margin-bottom:12px}
/* The verdict goes ON the thumbnail. Underneath the card it may as well not be there --
   you cannot tell what you are about to watch without reading a caption for every tile. */
.card{position:relative}
.card .v{position:absolute;top:7px;right:7px;z-index:2;box-shadow:0 1px 4px rgba(0,0,0,.35)}
.card.on{outline:3px solid var(--live);outline-offset:-1px}
.card .hit{position:absolute;inset:0;z-index:1;cursor:pointer}
.v.new{background:var(--live);color:#1A212B;position:absolute;top:7px;left:7px;right:auto}
details.more{margin-top:18px}
details.more summary{font:600 11.5px/1 ui-monospace,Menlo,monospace;color:var(--dim);
  cursor:pointer;padding:9px 0}
details.more[open] summary{margin-bottom:13px}
.race{display:grid;grid-template-columns:1fr;gap:10px}
.race:has(.racer+.racer){grid-template-columns:1fr 1fr}
.racer{margin:0}
.racer figcaption{padding:7px 2px 0;display:flex;flex-direction:column;gap:2px}
.stagegrid{display:grid;grid-template-columns:1.6fr 1fr;gap:16px;align-items:start}
@media(max-width:900px){.stagegrid{grid-template-columns:1fr}}
.side h2{margin-top:0}
.think{max-height:430px;overflow-y:auto;display:flex;flex-direction:column-reverse;gap:9px}
.think>div{border-left:3px solid var(--rule);padding:2px 0 2px 9px;
  font:12.5px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;word-break:break-word}
.think .th{border-left-color:var(--live)}
.think .tc{color:var(--dim)}
.think .t{display:block;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--dim);margin-bottom:2px}
.spark{width:100%;height:48px;display:block;margin:9px 0 6px}
.spark polyline{fill:none;stroke:var(--live);stroke-width:1.5;vector-effect:non-scaling-stroke}
.bar{height:8px;background:var(--ground);border:1.5px solid var(--rule);border-radius:2px;
  overflow:hidden}
.bar span{display:block;height:100%;background:var(--ink)}
.bar+.k{display:block;margin-top:6px;font-size:11.5px;color:var(--dim)}
</style></head><body><div class="wrap">
<div class="head"><div><span class="eyebrow">Teleport Arena &middot; playtest</span>
<h1>Agents playing The Butterfly Effect</h1></div>
<div class="stat">%STATS%</div></div>
<div class="statusbar" id="status">&hellip;</div>

<div class="panel stage">
  <h2><span id="stagetitle">%STAGETITLE%</span>
      <button id="tolive" class="pill live-pill" onclick="showLive()">watch live</button></h2>
  <div id="clipinfo" class="clipinfo"></div>
  <div class="stagegrid">
    <div>
      <div class="race" id="race">%RACE%</div>
      <div class="shot stagevid"><video id="replay" src="%STAGESRC%" autoplay muted playsinline></video></div>
    </div>
    <div class="side">
      <h2>What the agent is thinking</h2>
      <div id="thinking">&hellip;</div>
    </div>
  </div>
</div>

<div class="panel"><h2>Token spend &mdash; zai agents, last 7 days</h2>
  <div id="spend">&hellip;</div>
</div>

<div class="panel" id="evidence" style="display:none">
  <h2>What produced this clip</h2><div id="clipdetail"></div></div>
<div class="panel"><h2>Highlights &mdash; every level an agent has solved</h2>%HIGHLIGHTS%</div>
<div class="panel"><h2>Everything else &mdash; click one to play it above</h2>%GALLERY%</div>

<div class="panel"><h2>Console</h2>
  <div class="console">
    <button id="playbtn" onclick="play()" title="picks an unsolved level and works on it for ten minutes">
      &#9654;&nbsp; Play a round</button>
    <select id="lvl">%LEVELS%</select>
    <select id="prov"><option value="zai">zai / glm-5.2 (blind)</option>
      <option value="claude">claude (can see)</option></select>
    <button id="go" onclick="start()">Start</button>
    <button id="halt" class="ghost" onclick="stop()">Stop</button>
    <button class="ghost" onclick="jog()">Keep recording</button>
  </div>
  <div id="agent">&hellip;</div>
  <div id="rec">&hellip;</div>

</div>

<details class="panel"><summary>Every player &mdash; who is running, who is idle</summary>
%LIVE%</details>
<details class="panel"><summary>Attempt log</summary>%ATTEMPTS%</details>
<div class="panel now" id="banner" style="display:none"></div>
</div>
<script>
// Refresh every player's frame. Double-buffered: assigning straight to i.src blanks the
// element while the new PNG loads, and once a second that reads as the whole page blinking.
// Load into a detached Image first and only swap when it is ready.
function refreshFrame(i){
  if(i.__busy) return;
  i.__busy = true;
  const im = new Image();
  im.onload = () => { i.src = im.src; i.__busy = false; };
  im.onerror = () => { i.__busy = false; };
  im.src = i.dataset.src + '?' + Date.now();
}
setInterval(()=>{
  if(document.hidden) return;
  document.querySelectorAll('img.live').forEach(i=>{
    if(i.id==='live' && window.__watchingClip) return;   // watching a clip, not the frame
    if(!i.offsetParent) return;                          // hidden, or in a closed details
    refreshFrame(i);});}, 1000);
setInterval(()=>fetch('/live').then(r=>r.text()).then(h=>{
  const p=document.getElementById('players'); if(p && p.parentNode) p.outerHTML=h;}), 4000);
// Whether there is anything live to go back to, so "watch live" is only offered when it is.
function liveNow(){
  return fetch('/livenow').then(r=>r.text()).then(t=>{
    const b=document.getElementById('tolive'); if(!b) return;
    window.__liveName = t.trim();
    b.classList.toggle('show', !!t.trim());});
}
setInterval(liveNow, 4000); liveNow();
// A playlist, so an open tab keeps showing you things: when a clip ends, advance to the
// next card. A live run takes the stage back on its own.
const stageVid = document.getElementById('replay');
if(stageVid) stageVid.addEventListener('ended', ()=>{
  if(window.__watchingClip) return;              // you chose this one; stay on it
  const cards=[...document.querySelectorAll('.gallery > .card')];
  if(!cards.length) return;
  window.__reel = ((window.__reel||0)+1) % cards.length;
  cards[window.__reel].click();
  window.__watchingClip = false;                 // still autoplaying, not a manual pick
});
function post(u,b){return fetch(u,{method:'POST',body:b}).then(r=>r.text()).then(t=>{
  document.getElementById('agent').innerHTML=t;});}
function start(){const s=document.getElementById('lvl');
  document.getElementById('agent').textContent='starting '+s.value+' on zed…';
  post('/start','level='+encodeURIComponent(s.value)
    +'&provider='+encodeURIComponent(document.getElementById('prov').value));}
function stop(){document.getElementById('agent').textContent='stopping…';post('/stop','');}
function play(){document.getElementById('agent').textContent='picking a puzzle…';
  post('/play','minutes=10');}
// Keep the recorder alive only while somebody is actually at the page: a visible tab plus
// real input. A tab left open on another desktop should let it wind down.
let jogged = 0;
function jog(){ jogged = Date.now();
  fetch('/jog',{method:'POST'}).then(r=>r.text()).then(t=>rec.innerHTML=t); }
const rec = document.getElementById('rec');
['mousemove','keydown','click','scroll','touchstart'].forEach(e =>
  addEventListener(e, () => { if(!document.hidden && Date.now()-jogged > 60000) jog(); },
                   {passive:true}));
setInterval(()=>fetch('/rec').then(r=>r.text()).then(t=>{if(rec) rec.innerHTML=t;}), 5000);
fetch('/rec').then(r=>r.text()).then(t=>{if(rec) rec.innerHTML=t;});
// The agent's own reasoning, off its pi transcript. This is the only realtime signal of
// what it is doing between attempts -- the frame only moves while a simulation is running,
// and the agent spends most of its time thinking rather than running one.
const load = (u,id,ms) => { const go = () => fetch(u).then(r=>r.text()).then(t=>{
  const e=document.getElementById(id); if(e && e.innerHTML!==t) e.innerHTML=t; }); go();
  setInterval(go, ms); };
load('/thinking','thinking',5000);
load('/status','status',3000);
// Re-render the racers so a player joining or dropping out appears without a reload.
setInterval(()=>fetch('/race').then(r=>r.text()).then(h=>{
  const e=document.getElementById('race');
  if(e && !window.__watchingClip && e.innerHTML!==h) e.innerHTML=h;}), 4000);
load('/spend','spend',60000);
setInterval(()=>fetch('/agent').then(r=>r.text()).then(t=>{
  const a=document.getElementById('agent');
  if(a && !a.textContent.endsWith('…')) a.innerHTML=t;}), 5000);
fetch('/agent').then(r=>r.text()).then(t=>document.getElementById('agent').innerHTML=t);
setInterval(()=>fetch('/banner').then(r=>r.text()).then(h=>{
  const b=document.getElementById('banner');
  if(!b) return;
  b.style.display = h.trim() ? 'block' : 'none';
  if(h.trim() && b.innerHTML!==h) b.innerHTML=h;
}), 2000);
// Put a clip in the stage at the top of the page. The stage holds both the live frame and
// the video; picking a clip swaps to the video, "watch live" swaps back.
function pick(card, src, name){
  const v=document.getElementById('replay'), i=document.getElementById('live');
  if(!v) return;
  v.src=src; v.load(); v.play();
  v.style.display='block'; if(i) i.style.display='none';
  document.getElementById('stagetitle').textContent=name;
  document.querySelectorAll('.card').forEach(c=>c.classList.remove('on'));
  if(card) card.classList.add('on');
  window.__watchingClip = true;
  // The clip is the visible half of an attempt; this is the rest of it.
  const file = src.replace(/^\//,'');
  fetch('/clip?f='+encodeURIComponent(file)).then(r=>r.text()).then(h=>{
    document.getElementById('clipdetail').innerHTML = h;
    document.getElementById('evidence').style.display = 'block';
  });
  if(v.getBoundingClientRect().top < 0) v.scrollIntoView({block:'start'});
}
function loadThinking(f){
  const el=document.getElementById('clipthink');
  el.innerHTML='<p class="empty">reading the transcript on the agent host&hellip;</p>';
  fetch('/clipthink?f='+encodeURIComponent(f)).then(r=>r.text()).then(h=>el.innerHTML=h);
}
function showLive(){
  const v=document.getElementById('replay'), i=document.getElementById('live');
  if(v) v.style.display='none';
  if(i){ i.style.display='block'; i.src=i.dataset.src+'?'+Date.now(); }
  document.getElementById('stagetitle').textContent = window.__liveName || 'live';
  document.querySelectorAll('.card').forEach(c=>c.classList.remove('on'));
  window.__watchingClip = false;
  document.querySelector('.stage').scrollIntoView({block:'start'});
}
// An attempt landing must not scroll the page out from under whoever is reading it.
addEventListener('beforeunload',()=>sessionStorage.setItem('y',scrollY));
addEventListener('load',()=>{const y=sessionStorage.getItem('y');
  // Clamped: a position saved against a longer layout would otherwise drop you into blank
  // space below the end of the page.
  if(y!==null) scrollTo(0, Math.min(+y, document.body.scrollHeight - innerHeight));});
// Reload when an attempt lands -- but never out from under someone who is watching a clip
// or reading, and never while the tab is in the background.
setInterval(()=>fetch('/n').then(r=>r.text()).then(n=>{
  if(n===window.__n) return;
  const first = window.__n===undefined;
  window.__n=n;
  if(first || window.__watchingClip || document.hidden) return;
  location.reload();}), 3000);
</script></body></html>"""


def _won(stem):
    for d in (OUT, ZLOGS):
        f = d / f"{stem}_claude.log"
        if f.exists() and "AUTOMATED TESTING, slot_Won" in f.read_text(errors="replace"):
            return True
    return False


def _copied(level, places):
    """A win that lands on the author's own placements is a transcription, not a solve."""
    import tbe
    return bool(places) and tbe._matches_author_key(level, places)


def attempts():
    """Local attempts plus any agent logs synced in as attempts-<who>.jsonl."""
    rows = []
    for f in [OUT / "attempts.jsonl"] + sorted(OUT.glob("attempts-*.jsonl")):
        if not f.exists():
            continue
        who = "claude" if f.name == "attempts.jsonl" else f.stem.split("-", 1)[1]
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            r["who"] = r.get("who", who)
            # Never trust the verdict field. The only evidence a level was won is
            # slot_Won in the game's own log; the state-name lines are printed on
            # entry and appear whether or not anything was won. The agent logs are
            # also re-synced from zed continuously, which would clobber any fix-up.
            if str(r.get("verdict", "")).startswith("SOLVED"):
                r["verdict"] = "SOLVED" if _won(pathlib.Path(r.get("level", "")).stem) \
                                        else "UNPROVEN"
            # Re-check copies here too, for the same reason: these rows were written
            # before the check existed, and the agent logs are re-synced from zed.
            if r.get("verdict") == "SOLVED" and _copied(r.get("level", ""), r.get("places") or []):
                r["verdict"] = "COPIED"
            rows.append(r)
    # Date first. Sorting on the time of day alone put a 22:52 attempt from two days ago
    # after a 17:00 one from today, so "the last attempt" was routinely the wrong row --
    # the status line was reporting a two-day-old bouncing_balls solve as the latest news.
    # Rows written before the date field existed sort to the back, which is where they go.
    rows.sort(key=lambda r: (r.get("date", "0000-00-00"), r.get("time", "")))
    return rows



def _ago(s):
    if s < 60:
        return f"{int(s)}s ago"
    if s < 3600:
        return f"{int(s // 60)}m ago"
    return f"{int(s // 3600)}h ago"


def live_html():
    """One pane per player. The local run writes live.png; sync-agents.sh carries each zed
    worktree's frame across as live-<worktree>.png, mtime preserved, which is the only way
    to tell a frame from a simulation running now from one left behind hours ago."""
    now = time.time()
    frames = []
    if (OUT / "live.png").exists():
        frames.append(("claude", "live.png", now - (OUT / "live.png").stat().st_mtime))
    for p in sorted(OUT.glob("live-*.png")):
        frames.append((p.name[5:-4], p.name, now - p.stat().st_mtime))
    if not frames:
        return ('<div class="players" id="players"><p class="empty">'
                'No frames yet. Start an agent and its simulation will appear here.</p></div>')

    last = {}
    for r in attempts():
        last[r["who"]] = r
    cards = []
    for who, name, age in sorted(frames, key=lambda f: f[2]):
        r = last.get(who) or last.get(who.split("-")[0]) or {}
        live = age < FRESH
        cards.append(
            f'<figure class="player{"" if live else " stale"}">'
            f'<div class="shot"><img class="live" src="/{name}" data-src="/{name}" '
            f'alt="{html.escape(who)}"></div>'
            f'<figcaption><span class="cardname">{html.escape(who)}'
            f'<span class="who">{html.escape(r.get("verdict","idle"))}</span></span>'
            f'<span class="cardpl">{html.escape(pathlib.Path(r.get("level","")).stem)}</span>'
            f'<span class="age{" on" if live else ""}">'
            + ('<span class="dot"></span>live' if live else f"last frame {_ago(age)}")
            + "</span></figcaption></figure>")
    return f'<div class="players" id="players">{"".join(cards)}</div>'


def race_html():
    """Everyone simulating right now, side by side.

    When two players are on the same level at once -- the blind one and the one that can
    see -- this is the whole point of the page: the same puzzle, two machines, at the same
    moment. One player fills the stage; two or more share it."""
    now = time.time()
    live = [(p, now - p.stat().st_mtime) for p in
            [OUT / "live.png", *sorted(OUT.glob("live-*.png"))] if p.exists()]
    live = sorted([(p, a) for p, a in live if a < FRESH], key=lambda t: t[1])
    if not live:
        return ('<img class="live" id="live" src="/live.png" data-src="/live.png" '
                'alt="the last frame">')
    last = {r["who"]: r for r in attempts()}
    cells = []
    for p, _age in live[:4]:
        who = "claude" if p.name == "live.png" else p.name[5:-4]
        r = last.get(who, {})
        cells.append(
            f'<figure class="racer"><div class="shot">'
            f'<img class="live" src="/{p.name}" data-src="/{p.name}" alt="{html.escape(who)}">'
            f'</div><figcaption><span class="cardname">{html.escape(who)}</span>'
            f'<span class="cardpl">{html.escape(pathlib.Path(r.get("level","")).stem)}'
            f' &middot; {html.escape(" ".join(r.get("places", [])))}</span>'
            f'</figcaption></figure>')
    return "".join(cells)


def live_now():
    """The level being simulated right now, or "" if nothing is. A frame is live if it was
    written in the last FRESH seconds; the run writes one a second while it goes."""
    now = time.time()
    fresh = [(now - p.stat().st_mtime, p) for p in
             [OUT / "live.png", *OUT.glob("live-*.png")] if p.exists()]
    fresh = [(a, p) for a, p in fresh if a < FRESH]
    if not fresh:
        return ""
    _, p = min(fresh)
    if p.name != "live.png":
        who = p.name[5:-4]
        last = {r["who"]: r for r in attempts()}.get(who, {})
        lvl = pathlib.Path(last.get("level", "")).stem
        return f"{who} playing {lvl}" if lvl else f"{who} playing"
    # An unsuffixed frame comes from a container started on THIS machine -- a health sweep,
    # or a solve run by hand -- not from an agent. Calling it "claude playing" put a name on
    # the page that was not playing. The level is whichever log is being written right now.
    logs = [(q.stat().st_mtime, q.stem) for q in OUT.glob("*.log")]
    return f"a local run on {max(logs)[1]}" if logs else "a local run"


def levels_html():
    """Every level nobody has solved yet, as the console's menu."""
    d = HERE.parent / "tbe-src" / "levels" / "finished"
    solved = {pathlib.Path(r["level"]).stem for r in attempts() if r.get("verdict") == "SOLVED"}
    opts = [f'<option value="finished/{p.name}">{html.escape(p.stem)}</option>'
            for p in sorted(d.glob("*.xml")) if p.stem not in solved]
    return "".join(opts) or '<option value="">no unsolved levels found</option>'


PROMPT = """You are playing The Butterfly Effect, the level {level}, in this worktree.

Read playtest/harness/PLAYBOOK.md first. It is short, and it is what the engine actually
does: goal semantics, the physical properties of every part, and the two ways to get a
verdict that is not a solve. It exists because the agents before you spent a third of their
commands reading the game's C++ to rediscover what is in it.

    python3 playtest/harness/tbe.py setup            # once: fetch the levels
    python3 playtest/harness/tbe.py brief {level}    # the scene, the toolbox, the goals
    python3 playtest/harness/parts.py                # every part, mass and bounciness
    python3 playtest/harness/tbe.py solve {level} Part@X,Y [Part@X,Y,angle ...]
    python3 playtest/harness/tbe.py where {level} <object>   # its path, moment by moment
    python3 playtest/harness/tbe.py trace {level}    # what every object did, summarised

Win it with the fewest parts you can. Each solve runs the game's own regression referee: it
plays the level empty (which must fail) and then with your parts (which must win). Only
"SOLVED (slot_Won fired)" counts as a win.

{vision}
- Every "must hold" goal has to be true in the same instant. They do not latch.
- Do not copy the author's answer key. A placement matching it is recorded as COPIED.
- Do not place a part overlapping a body already in the scene. Box2D ejects it violently and
  the referee cannot tell that explosion from a mechanism.
- After each failure run `where` on the object the goal is about, and read what it did.
- Stop at 8 attempts if it has not gone in. Do not commit or push.
{tried}"""

# The two halves of the experiment. Everything else about the run is identical, so the only
# variable is whether the player can look at the thing it is playing.
BLIND = """- You cannot see. This model has no vision. Do not extract video frames and try to read
  them -- agents before you did exactly that, were told the model does not support images,
  and lost the time. `where` gives you the object's real path out of the simulation, which
  is better than anything a picture could tell you."""

SIGHTED = """- You CAN see, and you should. `tbe.py frame {level} 0.75` pulls a still out of your last
  attempt (a fraction of the clip, or "12s" for a moment); read the PNG it prints. Look at
  what actually happened before you reason about why. `where` gives you the same scene as
  numbers -- use both."""

PROVIDERS = {                      # label -> (paseo provider, model, prompt half)
    "zai": ("pi", "zai/glm-5.2", BLIND),
    "claude": ("claude", "", SIGHTED),
}


def zed(*args, timeout=120):
    """Run a paseo command on zed. The daemon password stays on zed, in ~/.paseo/cli-host."""
    # --host is a per-subcommand option, not a global one, so it goes after args[0].
    cmd = ('export NVM_DIR=$HOME/.nvm; . $NVM_DIR/nvm.sh; paseo '
           + shlex.quote(args[0]) + ' --host "$(cat ~/.paseo/cli-host)" '
           + " ".join(shlex.quote(a) for a in args[1:]))
    return subprocess.run(["ssh", "-o", "BatchMode=yes", ZED, cmd],
                          capture_output=True, text=True, timeout=timeout)


PI_SESSIONS = "~/.pi/agent/sessions"


def zed_py(script, timeout=90):
    """Run a snippet on zed and parse the JSON it prints. The pi agent writes a transcript
    per session -- every thinking block, every tool call, and the token usage of each
    request -- and that file is the only place any of it exists."""
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", ZED, "python3 -"],
                       input=script, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout).strip()[:400]}
    return json.loads(r.stdout or "{}")   # callers pass scripts printing an object or a list


THINKING_PY = """
import glob, json, os, sys
wt = %r
# Both transcript formats, because the two players write different ones: pi keeps its own
# sessions, and a paseo claude agent writes a Claude Code session under ~/.claude/projects.
# Reading only pi's meant the sighted player's panel said "no transcript yet" the whole
# time it was solving the level.
fs = [(os.path.getmtime(f), f, "pi") for f in
      glob.glob(os.path.expanduser("~/.pi/agent/sessions") + "/*" + wt + "*/*.jsonl")]
fs += [(os.path.getmtime(f), f, "claude") for f in
       glob.glob(os.path.expanduser("~/.claude/projects") + "/*" + wt + "*/*.jsonl")]
out = []
if fs:
    _, path, kind = max(fs)
    for line in open(path):
        try:
            d = json.loads(line)
        except Exception:
            continue
        m = d.get("message") or {}
        if m.get("role") != "assistant":
            continue
        content = m.get("content") or []
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for c in content:
            if not isinstance(c, dict):
                continue
            t, ts = c.get("type"), d.get("timestamp", "")
            if t == "thinking" and c.get("thinking"):
                out.append({"t": ts, "kind": "thinking", "text": c["thinking"]})
            elif t == "text" and c.get("text"):
                out.append({"t": ts, "kind": "says", "text": c["text"]})
            elif t == "toolCall":
                a = c.get("arguments") or {}
                out.append({"t": ts, "kind": c.get("name", "tool"),
                            "text": str(a.get("command") or a.get("path") or "")[:300]})
            elif t == "tool_use":                       # Claude Code's shape
                a = c.get("input") or {}
                out.append({"t": ts, "kind": c.get("name", "tool"),
                            "text": str(a.get("command") or a.get("file_path") or "")[:300]})
    fs = [max(fs)]
print(json.dumps({"items": out[-14:], "file": os.path.basename(fs[-1][1]) if fs else "",
                  "kind": fs[-1][2] if fs else ""}))
"""


TOKENS_PY = """
import glob, json, os
rows = []
for f in glob.glob(os.path.expanduser(%r) + "/*/*.jsonl"):
    for line in open(f):
        try:
            d = json.loads(line)
        except Exception:
            continue
        u = ((d.get("message") or {}).get("usage")) or {}
        if u.get("totalTokens"):
            rows.append([d.get("timestamp", ""), u["totalTokens"],
                         (u.get("cost") or {}).get("total", 0)])
rows.sort()
print(json.dumps({"rows": [r for r in rows if r[0] >= %r]}))
""" % (PI_SESSIONS, "%s")


def thinking():
    a = json.loads(AGENT.read_text()) if AGENT.exists() else None
    if not a:
        return {"items": [], "file": ""}
    return zed_py(THINKING_PY % a["worktree"])


def token_series():
    """Cached: this walks every session transcript on zed, which is not a 5-second job."""
    if time.time() - token_series.at > 90:
        since = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.gmtime(time.time() - 7 * 86400))
        token_series.at = time.time()
        token_series.v = zed_py(TOKENS_PY % since, timeout=240)
    return token_series.v


token_series.at, token_series.v = 0.0, {"rows": []}

WEEKLY_TOKENS = OUT / "weekly-token-allowance.txt"
ZAI_TOKEN = OUT / "zai-token"          # you put it here; gitignored; nothing else reads it
ZAI_QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"


def zai_quota():
    """What Z.ai says is left of the plan, rather than what local logs can infer.

    Endpoint and auth shape are from ~/projects/oauth3/tasks/zai-token-grab.js. The token
    is read from out/zai-token and used here; put a coding-plan key or a website session
    token in that file and this panel switches from "week elapsed" to the real quota.
    Errors are shown, not swallowed -- an expired token should say so."""
    if not ZAI_TOKEN.exists():
        return None
    if time.time() - zai_quota.at > 300:
        zai_quota.at = time.time()
        req = urllib.request.Request(
            ZAI_QUOTA_URL, headers={"Authorization": "Bearer " + ZAI_TOKEN.read_text().strip()})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                zai_quota.v = json.load(r)
        except Exception as e:
            zai_quota.v = {"error": f"{type(e).__name__}: {e}"}
    return zai_quota.v


zai_quota.at, zai_quota.v = 0.0, None


def quota_html():
    """Render whatever Z.ai returns. The field names are read off the payload rather than
    assumed, because no successful response has been seen from here yet -- the credential
    was not reachable. The moment one comes back, this shows its real numbers."""
    q = zai_quota()
    if q is None:
        return ""
    if isinstance(q, dict) and q.get("error"):
        return (f'<div class="err">z.ai quota: {html.escape(str(q["error"]))}</div>')
    flat = {}

    def walk(o, pre=""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{pre}{k}.")
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            flat[pre[:-1]] = o
    walk(q)
    if not flat:
        return f'<div class="k">z.ai returned no numbers: {html.escape(json.dumps(q)[:200])}</div>'
    cells = "".join(f'<div><span class="v2">{v:,}</span><br>'
                    f'<span class="k">{html.escape(k)}</span></div>'
                    for k, v in list(flat.items())[:6])
    return f'<h2>From z.ai</h2><div class="stat">{cells}</div>'


def spend_html():
    """Tokens the zai agents have spent, hour by hour, over the last seven days.

    Everything here is read off the pi transcripts, which record the usage of every request.
    What is NOT here is the plan's allowance: this is a ZAI Coding Plan, the recorded cost
    of every call is 0, and nothing local knows what the weekly cap is. So the bar below is
    the week elapsing, not the quota burning -- until a number is put in
    out/weekly-token-allowance.txt, in which case it is measured against that."""
    s = token_series()
    if s.get("error"):
        return f'<div class="err">{html.escape(s["error"])}</div>'
    rows = s.get("rows", [])
    now = time.time()
    buckets = [0] * 168                                   # one per hour of the last week
    for ts, tok, _cost in rows:
        try:
            age = now - calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        i = 167 - int(age // 3600)
        if 0 <= i < 168:
            buckets[i] += tok
    total = sum(buckets)
    peak = max(buckets) or 1
    pts = " ".join(f"{i * 640 / 167:.1f},{46 - 44 * v / peak:.1f}"
                   for i, v in enumerate(buckets))
    spark = (f'<svg class="spark" viewBox="0 0 640 48" preserveAspectRatio="none">'
             f'<polyline points="{pts}"/></svg>')

    # How far through the week we are. The plan's reset day is not known here, so this is
    # the calendar week, stated as such rather than dressed up as a quota.
    lt = time.localtime()
    frac = ((lt.tm_wday * 86400 + lt.tm_hour * 3600 + lt.tm_min * 60) / (7 * 86400))
    cap = int(WEEKLY_TOKENS.read_text().strip()) if WEEKLY_TOKENS.exists() else None
    if cap:
        used = total / cap
        bar = (f'<div class="bar"><span style="width:{min(100, used * 100):.1f}%"></span></div>'
               f'<div class="k">{used * 100:.0f}% of the {cap / 1e6:.0f}M weekly allowance '
               f'&middot; {(1 - frac) * 100:.0f}% of the week left</div>')
    else:
        bar = (f'<div class="bar"><span style="width:{frac * 100:.1f}%"></span></div>'
               f'<div class="k">{(1 - frac) * 100:.0f}% of the calendar week left. '
               f'The plan allowance is not readable from here &mdash; put a token number in '
               f'<code>out/weekly-token-allowance.txt</code> and this becomes % of quota.</div>')
    return (quota_html() + f'<div class="stat"><div><span class="v2">{total / 1e6:.1f}M</span><br>'
            f'<span class="k">tokens, last 7 days</span></div>'
            f'<div><span class="v2">{len(rows)}</span><br><span class="k">requests</span></div>'
            f'<div><span class="v2">{peak / 1e3:.0f}k</span><br>'
            f'<span class="k">busiest hour</span></div></div>{spark}{bar}')


def thinking_html():
    t = thinking()
    if t.get("error"):
        return f'<div class="err">{html.escape(t["error"])}</div>'
    items = t.get("items") or []
    if not items:
        return '<p class="empty">No agent transcript yet.</p>'
    out = []
    for i in items:
        when = i["t"][11:19] if len(i["t"]) > 19 else ""
        cls = "th" if i["kind"] == "thinking" else "tc"
        out.append(f'<div class="{cls}"><span class="t">{html.escape(when)} '
                   f'{html.escape(i["kind"])}</span>{html.escape(i["text"][:600])}</div>')
    return f'<div class="think">{"".join(out)}</div>'


def already_tried(level, limit=60):
    """What has been attempted on this level already, for the prompt.

    Restarting a level reuses its worktree, so the previous run's attempts.jsonl is sitting
    right there on disk -- but the agent is a new session with no memory of it and nothing
    telling it to look. One run made 102 distinct placements with no dedup, and restarting it
    began again from nothing. The files were cumulative; the player was not."""
    stem = pathlib.Path(level).stem
    seen = {}
    for r in attempts():
        if pathlib.Path(r.get("level", "")).stem != stem or not r.get("places"):
            continue
        seen[" ".join(r["places"])] = r.get("verdict", "?")
    if not seen:
        return ""
    rows = [f"  {p:<44} {v}" for p, v in list(seen.items())[-limit:]]
    more = f"\n  ... and {len(seen) - limit} earlier ones" if len(seen) > limit else ""
    return (f"\nALREADY TRIED on this level -- {len(seen)} distinct placements, none of which "
            f"you need to repeat:\n" + "\n".join(rows) + more +
            "\n\nRead that before your first attempt. Anything listed has already been run, so "
            "trying it again spends 20 seconds to learn nothing. A long list is evidence that "
            "the obvious family of placements is exhausted and the mechanism needs rethinking "
            "rather than nudging.\n")


def playable_unsolved():
    """Levels worth handing out: the health sweep says playable, and nobody has solved them."""
    hf = HERE / "level-health.json"
    health = json.loads(hf.read_text()) if hf.exists() else {}
    done = {pathlib.Path(r["level"]).stem for r in attempts()
            if r.get("verdict") in ("SOLVED", "COPIED")}
    return [lv for lv, h in sorted(health.items())
            if h.get("verdict") == "SOLVED" and pathlib.Path(lv).stem not in done]


def play_round(minutes=10, provider="claude"):
    """Spend a bounded amount of time on one unsolved puzzle, then stop.

    The console used to offer "start an agent", which runs until it decides to stop -- and one
    of them made 118 attempts over 42 minutes. This is the middle setting: one click, one
    level chosen for you from the ones known playable, and a hard stop. Watching should not
    require deciding what to watch, and it should not cost an open-ended amount."""
    todo = playable_unsolved()
    if not todo:
        return {"error": "nothing playable left unsolved -- re-run the health sweep"}
    a = start_agent(todo[0], provider)
    if "error" in a:
        return a
    play_round.until = time.time() + minutes * 60
    play_round.level = pathlib.Path(todo[0]).stem
    threading.Thread(target=_stop_after, args=(a["id"], play_round.until), daemon=True).start()
    return a


play_round.until, play_round.level = 0.0, ""


def _stop_after(agent_id, until):
    while time.time() < until:
        time.sleep(15)
        if not AGENT.exists() or json.loads(AGENT.read_text()).get("id") != agent_id:
            return                                   # superseded by another run
    zed("stop", agent_id)
    play_round.until = 0.0


def start_agent(level, provider="zai"):
    stem = pathlib.Path(level).stem
    prov, model, vision = PROVIDERS[provider]
    # The worktree name is what labels the player's pane, so it names the player and level.
    wt = f"{provider}-" + re.sub(r"[^a-z0-9]+", "-", stem.lower())[:26]
    # zed's checkout can be behind the harness this page is running, and a fresh worktree
    # never has tbe-src (gitignored) -- the agent's first command is tbe.py setup.
    pull = subprocess.run(["ssh", "-o", "BatchMode=yes", ZED,
                           f"cd {REPO_ON_ZED} && git pull -q --ff-only"],
                          capture_output=True, text=True, timeout=120)
    if pull.returncode != 0:
        return {"error": f"git pull on zed failed: {pull.stderr.strip()}"}
    args = ["run", "--detach", "--json", "--provider", prov]
    if model:
        args += ["--model", model]
    if prov == "claude":
        args += ["--mode", "bypassPermissions"]     # detached runs stall on approvals
    prompt = PROMPT.format(level=level, vision=vision.format(level=level),
                           tried=already_tried(level))
    r = zed(*args, "--cwd", REPO_ON_ZED, "--worktree", wt,
            "--title", f"arena {provider}: {stem}", prompt)
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout).strip()}
    agent_id = json.loads(r.stdout)["agentId"]
    # Stamp the conditions now, while they are known. Reconstructing afterwards is what
    # issue #10 is about: today alone the prompt, the referee and the placement grammar all
    # changed, and nothing in a trajectory recorded which it ran against.
    import manifest
    run = manifest.write(level=level, provider=provider, model=model,
                         vision=(provider != "zai"), prompt=prompt,
                         worktree=wt, agent_id=agent_id)
    a = {"id": agent_id, "level": level, "worktree": wt, "run": run["run"],
         "provider": provider, "started": time.strftime("%H:%M:%S")}
    AGENT.write_text(json.dumps(a))
    return a


def tell_agent(agent_id, text):
    """Say something to the agent that is running, right now, mid-level.

    This is the half of watching that was missing. You could see an agent placing a ball
    inside the floor and have no way to tell it so -- the observation had to be carried by
    hand into the playbook and would only reach the NEXT agent. paseo's send continues an
    existing session with its context intact, so this arrives as a message in the run it is
    about."""
    # Fire and forget. `paseo send` blocks until the agent has finished responding, which
    # for a working agent is minutes -- the browser waited 120s and got a timeout instead of
    # an acknowledgement. The message is delivered either way, so hand it off and say so.
    cmd = ('export NVM_DIR=$HOME/.nvm; . $NVM_DIR/nvm.sh; nohup paseo send '
           '--host "$(cat ~/.paseo/cli-host)" ' + shlex.quote(agent_id) + " "
           + shlex.quote(text) + " >/dev/null 2>&1 &")
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", ZED, cmd],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return f'<span class="err">{html.escape((r.stderr or r.stdout).strip()[:200])}</span>'
    tell_agent.log.append((time.time(), text))
    return f"sent &rarr; {html.escape(text[:110])}"


tell_agent.log = []


def agent_status():
    """The console's agent as paseo currently sees it. Each call is an ssh, so it is cached
    for a few seconds -- the page polls this every 5s and the frames every 1s."""
    if not AGENT.exists():
        return None
    a = json.loads(AGENT.read_text())
    if time.time() - agent_status.at > 4:
        r = zed("ls", "--json", timeout=45)
        agent_status.at = time.time()
        agent_status.err = None if r.returncode == 0 else (r.stderr or r.stdout).strip()
        agent_status.by_id = {x["id"]: x for x in json.loads(r.stdout)} if r.returncode == 0 else {}
    a["status"] = (agent_status.by_id.get(a["id"]) or {}).get("status", "archived/gone")
    a["error"] = agent_status.err
    return a


agent_status.at, agent_status.by_id, agent_status.err = 0.0, {}, None


def agent_html():
    a = agent_status()
    if a is None:
        return "No agent started from here yet."
    err = f'<div class="err">{html.escape(a["error"])}</div>' if a.get("error") else ""
    return (f'<b>{html.escape(pathlib.Path(a["level"]).stem)}</b> &middot; '
            f'{html.escape(a["status"])} &middot; worktree {html.escape(a["worktree"])} '
            f'&middot; started {html.escape(a["started"])} &middot; {html.escape(a["id"][:7])}'
            + (f' &middot; <b>{int((play_round.until - time.time()) // 60) + 1}m left in this '
               f'round</b>' if play_round.until > time.time() else "") + err)


def black_fraction(path):
    """How much of a clip is a black screen.

    The game dies partway through some levels -- goal_maker got 0.85s in -- and what gets
    recorded is one frame of the level and then twenty seconds of nothing. Every dead clip
    measured bottoms out at YAVG 16.02, pure black; no live one goes below 118. Shipping
    these to the page is worse than having no clip for that level."""
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-vf",
         "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    ys = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", r.stderr)]
    if not ys:
        return 1.0
    return sum(1 for y in ys if y < 30) / len(ys)


def syncer():
    """Pull the agents' work off zed, in-process.

    This used to be sync-agents.sh, a separate loop somebody had to remember to start. It
    died during a restart and nothing noticed: the page went on serving hours-old data with
    no way to tell, which reads exactly like the agents having stopped working. Meanwhile
    the sighted player had solved its level. One process, and its health is on the page."""
    while True:
        slow = ["--slow"] if syncer.n % 8 == 0 else []
        syncer.n += 1
        try:
            subprocess.run(["bash", str(HERE / "sync-agents.sh"), "--once"] + slow,
                           capture_output=True, text=True, timeout=300)
            syncer.at, syncer.err = time.time(), None
        except Exception as e:
            syncer.err = f"{type(e).__name__}: {e}"
        time.sleep(3)


syncer.at, syncer.err, syncer.n = 0.0, "not started", 0


def ago(seconds):
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def status_html():
    """The one line that answers "is anything happening right now", plus whether what you
    are looking at is current. Without this the page cannot distinguish a quiet moment from
    a broken pipe, and neither can you."""
    now = time.time()
    live = live_now()
    rows = attempts()
    last = rows[-1] if rows else {}
    # Trust the epoch, never the clock string: it was written on whichever machine ran the
    # attempt, and zed is an hour behind this one. Rows from before the epoch field say so
    # rather than pretending to a precision they do not have.
    lastwhen = ago(now - last["epoch"]) if last.get("epoch") else (
        f'at {last.get("time", "?")} (before timestamps were reliable)' if last else "")
    sync_age = now - syncer.at if syncer.at else None
    if syncer.err or sync_age is None or sync_age > 60:
        sync = (f'<span class="bad">data from zed is stale &mdash; '
                f'{html.escape(syncer.err or "sync has not run")}</span>')
    else:
        sync = f'<span class="dim">zed data {ago(sync_age)}</span>'
    if live:
        head = f'<span class="hot"><span class="dot"></span>LIVE &middot; {html.escape(live)}</span>'
    else:
        head = ('<span class="dim">nothing simulating right now &middot; last attempt '
                f'{html.escape(lastwhen or "never")}</span>')
    verdict = last.get("verdict", "")
    tail = (f' &middot; last: <b>{html.escape(pathlib.Path(last.get("level","")).stem)}</b> '
            f'{html.escape(verdict)} by {html.escape(last.get("who","claude"))}') if last else ""
    return f'{head} &middot; {sync}{tail}'


def to_record():
    """Levels with an author solution and no footage. There are 74 answer keys, so this is
    a long queue of contraptions nobody has watched run. `.dead` marks the ones whose
    recording came back black, so the queue does not sit on them forever."""
    import tbe
    keys = json.loads(tbe.KEYS.read_text())
    have = {re.sub(r"_(placed|claude|author)$", "", p.stem) for p in OUT.glob("*.mp4")}
    have |= {p.stem for p in OUT.glob("*.dead")}
    return [lv for lv in sorted(keys) if pathlib.Path(lv).stem not in have and keys[lv]]


def jog(minutes=AWAKE_MINUTES):
    """Anything you do -- opening the page, moving the mouse on it, starting an agent --
    keeps the recorder alive this much longer. Nothing you do, and it stops on its own."""
    recorder.awake_until = max(recorder.awake_until, time.time() + minutes * 60)


def recorder():
    """Record one contraption at a time, but only while somebody is watching.

    Deliberately not a daemon: it holds a deadline rather than a flag, so it winds down by
    itself when the page is closed and comes straight back when it is opened again."""
    import tbe
    while True:
        if time.time() >= recorder.awake_until:
            recorder.doing = None
            time.sleep(5)
            continue
        todo = to_record()
        if not todo:
            recorder.doing = None
            time.sleep(20)
            continue
        lv = todo[0]
        keys = json.loads(tbe.KEYS.read_text())
        places = tbe.key_to_places(keys[lv])
        stem = recorder.doing = pathlib.Path(lv).stem
        vid = OUT / f"{stem}_author.mp4"
        try:
            # Through the regression driver, not record-run.sh. record-run.sh dismisses the
            # briefing with synthetic keystrokes and on about half the levels the game's
            # window vanished afterwards -- the process lived, the simulation stopped at
            # t=0.00, and the clip was 93% black. The regression driver never touches the
            # keyboard, and its recordings come back clean.
            cand = tbe._write_candidate(lv, places, "author")
            r = tbe._docker(["bash", "/run.sh", f"/solve/{cand.name}"],
                            {"DUR": "90", "RECORD": "1"})
            if "Segmentation fault" in (r.stdout + r.stderr):
                # Some levels crash this build outright -- the_pit and goal_maker do, on the
                # unpatched build too, so it is the game and not the speedup. Nothing to
                # record, and no point coming back to it.
                recorder.failed[lv] = "the game segfaults on this level"
        except Exception as e:
            recorder.failed[lv] = str(e)
        # Publish it only if there is something on it. Either way leave a .dead marker
        # when there is not, so the queue moves on instead of retrying forever.
        if vid.exists() and black_fraction(vid) > 0.3:
            recorder.failed.setdefault(lv, "recorded black: the game died during the run")
            vid.unlink()
        if not vid.exists():
            (OUT / f"{stem}.dead").write_text(recorder.failed.get(lv, "no video produced"))


recorder.awake_until, recorder.doing, recorder.failed = 0.0, None, {}


def recorder_html():
    left = recorder.awake_until - time.time()
    if left <= 0:
        return ('<span class="rec off">recorder asleep</span> '
                f'&middot; {len(to_record())} contraptions unrecorded')
    doing = (f'recording <b>{html.escape(recorder.doing)}</b>' if recorder.doing
             else "waiting for something to record")
    return (f'<span class="rec"><span class="dot"></span>{doing}</span> '
            f'&middot; sleeps in {int(left // 60)}m &middot; '
            f'{len(to_record())} left')


def level_stems():
    d = HERE.parent / "tbe-src" / "levels"
    return {p.stem for p in d.rglob("*.xml")} if d.is_dir() else set()


THUMBS = OUT / "thumbs"


def thumb_for(clip):
    """A small still per clip, made once, so the grid is images and not media players.

    The grid used to render a <video preload="metadata"> per clip. At 192 clips that is 192
    media elements fetching headers at once, which crashes the tab. One 320px JPEG each is a
    few kB and the browser can lazy-load it like any other image."""
    THUMBS.mkdir(exist_ok=True)
    src = OUT / clip
    dst = THUMBS / (pathlib.Path(clip).stem + ".jpg")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst.name
    try:
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(src)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        at = max(0.0, float(dur) * 0.75) if dur else 1.0
        subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", str(src),
                        "-frames:v", "1", "-vf", "scale=320:-1", "-q:v", "6", "-y", str(dst)],
                       capture_output=True, timeout=90)
    except Exception:
        return ""
    return dst.name if dst.exists() else ""


def footage():
    """Every clip that belongs to a level, newest first, and what it actually is.

    The picker used to be a row of bare filenames with no way to tell a solve from a
    failure from a scratch recording, and it had junk in it -- mech.mp4, reference.mp4 --
    that is not footage of anything. A clip is worth listing only if it is of a level, and
    only worth clicking if you can see what you are about to watch."""
    levels = level_stems()
    whos = [f.stem.split("-", 1)[1] for f in sorted(OUT.glob("attempts-*.jsonl"))]
    by_key = {}
    for r in attempts():                       # last word on each (who, level)
        by_key[(r["who"], pathlib.Path(r["level"]).stem)] = r

    # Every attempt's own clip, kept under archive/ so a later attempt at the same level
    # cannot overwrite it. The row that produced it names it, so the verdict is exact
    # rather than guessed from the level name.
    by_clip = {r["clip"]: r for r in attempts() if r.get("clip")}

    clips = []
    for p in sorted(list(OUT.glob("*.mp4")) + list((OUT / "archive").glob("*.mp4")),
                    key=lambda q: -q.stat().st_mtime):
        rel = f"archive/{p.name}" if p.parent.name == "archive" else p.name
        if rel in by_clip:
            r = by_clip[rel]
            stem = pathlib.Path(r["level"]).stem
            if stem in levels:
                clips.append({
                    "file": rel, "stem": p.stem, "title": stem, "who": r.get("who", "claude"),
                    "kind": "attempt", "badge": r.get("verdict", "?"),
                    "quiet": p.stat().st_size < 70_000,
                    "when": ago(time.time() - p.stat().st_mtime),
                    "age": time.time() - p.stat().st_mtime,
                    "places": " ".join(r.get("places", [])),
                    "thumb": thumb_for(rel),
                })
            continue
        size = p.stat().st_size
        if size < 2048:
            continue                # ffmpeg was killed before it wrote a playable file
        name, who, kind = p.stem, None, "replay"
        for w in sorted(whos, key=len, reverse=True):
            if name.startswith(f"{w}-"):       # synced from a zed worktree
                who, name = w, name[len(w) + 1:]
                break
        for suffix, k in (("_claude", "attempt"), ("_placed", "replay"),
                          ("_author", "author's own"), ("_win", "replay"),
                          ("_fail", "attempt")):
            if name.endswith(suffix):
                name, kind = name[: -len(suffix)], k
                break
        if name not in levels:
            continue                # not footage of a level: scratch clips, references
        # A clip with no worktree in its name could belong to any player who tried that
        # level. Credit the best outcome anyone got, not whichever row happens to be first
        # -- brother-plays-soccer was reading NOT SOLVED off an abandoned worktree while
        # the run that actually won it sat two rows down.
        rank = {"SOLVED": 3, "COPIED": 2, "UNPROVEN": 1}
        cands = [v for (w, s), v in by_key.items() if s == name]
        r = by_key.get((who, name)) or (
            max(cands, key=lambda v: (rank.get(v.get("verdict"), 0), v.get("time", "")))
            if cands else None)
        if kind == "author's own":
            # This is the level author's solution, recorded so there is something to watch.
            # It is not anybody's solve and must never borrow an agent's verdict.
            badge, owner = "AUTHOR", "level author"
        elif r:
            badge, owner = r.get("verdict", "?"), r.get("who", "claude")
        else:
            # Nobody attempted it: this is the level author's own solution, recorded so
            # there is something to watch. Not a solve, and must not read like one.
            badge, owner = "AUTHOR", "level author"
        clips.append({
            "file": p.name, "stem": p.stem, "title": name, "who": owner, "kind": kind,
            "badge": badge, "quiet": size < 70_000,   # a 20s clip this small barely moves
            "when": ago(time.time() - p.stat().st_mtime),
            "age": time.time() - p.stat().st_mtime, "places": "",
            "thumb": thumb_for(rel),
        })
    return clips


def clip_detail(clipfile):
    """Everything we know about one attempt, assembled at the moment you click it.

    All of this was already being kept and none of it was reachable from the video: the
    attempt row has the placements and the verdict, the archived log has what the referee
    actually saw, the run manifest has the conditions, and the agent's own reasoning is in a
    transcript on the machine that ran it. This is the join, made visible."""
    row = next((r for r in attempts() if r.get("clip") == clipfile), None)
    if not row:
        return ('<p class="empty">No attempt record for this clip &mdash; it is an author '
                'contraption or predates the archive.</p>')
    out = [f'<div class="dl"><span>placed</span><code>'
           f'{html.escape(" ".join(row.get("places", []))) or "&mdash;"}</code></div>',
           f'<div class="dl"><span>verdict</span><b>{html.escape(row.get("verdict","?"))}</b>'
           f' &middot; {html.escape(row.get("who","claude"))}'
           f' &middot; {html.escape(row.get("date",""))} {html.escape(row.get("time",""))}</div>']

    # the conditions this run was produced under
    runs = {r["run"]: r for r in _manifests()}
    m = runs.get(row.get("run", ""))
    if m:
        out.append(f'<div class="dl"><span>conditions</span>harness <code>'
                   f'{html.escape(m.get("harness_commit",""))}</code>'
                   + (" (dirty)" if m.get("harness_dirty") else "")
                   + f' &middot; {html.escape(m.get("provider",""))}/'
                   f'{html.escape(m.get("model") or "-")}'
                   f' &middot; vision {"yes" if m.get("vision") else "no"}'
                   f' &middot; image <code>{html.escape((m.get("image") or "")[7:19])}</code></div>')
    elif row.get("run"):
        out.append(f'<div class="dl"><span>run</span><code>{html.escape(row["run"])}</code> '
                   f'(manifest not synced)</div>')
    else:
        out.append('<div class="dl"><span>conditions</span><i>not recorded &mdash; this attempt '
                   'predates run manifests</i></div>')

    # what the referee saw, out of the archived log
    log = OUT / row["log"] if row.get("log") else None
    if log and log.exists():
        import gzip
        try:
            text = gzip.open(log, "rt", errors="replace").read()
        except OSError:
            text = ""
        goals, seen = [], set()
        for line in text.splitlines():
            m2 = re.search(r"GOALCHK obj=(\S+) type=(\d+) now=\(([-\d.]+),([-\d.]+)\) "
                           r"limit=([-\d.]+)", line)
            if m2 and m2.group(1) not in seen:
                seen.add(m2.group(1))
                goals.append(f'{m2.group(1)} at ({m2.group(3)},{m2.group(4)}) '
                             f'against limit {m2.group(5)}')
        won = text.count("AUTOMATED TESTING, slot_Won")
        traces = text.count("TRACE t=")
        out.append(f'<div class="dl"><span>referee</span>{"won" if won else "no win"} '
                   f'&middot; {traces} state samples &middot; '
                   f'{html.escape("; ".join(goals[:4])) or "no goal checks logged"}</div>')
        out.append(f'<div class="dl"><span>full log</span>'
                   f'<a href="/{html.escape(row["log"])}" download>'
                   f'{html.escape(pathlib.Path(row["log"]).name)}</a> '
                   f'({log.stat().st_size // 1024} kB gzipped)</div>')

    # what else had been tried on this level by then
    same = [r for r in attempts()
            if pathlib.Path(r.get("level", "")).stem == pathlib.Path(row["level"]).stem
            and r.get("epoch", 0) < row.get("epoch", 0)]
    out.append(f'<div class="dl"><span>context</span>attempt '
               f'{len(same) + 1} on this level; {len({tuple(r.get("places", [])) for r in same})}'
               f' distinct placements tried before it</div>')

    out.append(f'<div class="dl"><span>thinking</span>'
               f'<button class="pill" onclick="loadThinking(\'{html.escape(clipfile)}\')">'
               f'fetch the agent\'s reasoning around this attempt</button>'
               f'<div id="clipthink"></div></div>')
    return "".join(out)


THINKING_AT_PY = """
import glob, json, os, sys
wt, lo, hi = %r, %f, %f
out = []
pats = [os.path.expanduser("~/.pi/agent/sessions") + "/*" + wt + "*/*.jsonl",
        os.path.expanduser("~/.claude/projects") + "/*" + wt + "*/*.jsonl"]
for pat in pats:
    for f in glob.glob(pat):
        for line in open(f):
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get("timestamp", "")
            if len(ts) < 19:
                continue
            import calendar, time as _t
            try:
                e = calendar.timegm(_t.strptime(ts[:19], "%%Y-%%m-%%dT%%H:%%M:%%S"))
            except ValueError:
                continue
            if not (lo <= e <= hi):
                continue
            m = d.get("message") or {}
            if m.get("role") != "assistant":
                continue
            c = m.get("content")
            if isinstance(c, str):
                c = [{"type": "text", "text": c}]
            for x in (c or []):
                if not isinstance(x, dict):
                    continue
                t = x.get("type")
                if t == "thinking" and x.get("thinking"):
                    out.append(("thinking", x["thinking"]))
                elif t == "text" and x.get("text"):
                    out.append(("says", x["text"]))
                elif t in ("toolCall", "tool_use"):
                    a = x.get("arguments") or x.get("input") or {}
                    out.append((x.get("name", "tool"),
                                str(a.get("command") or a.get("file_path") or a.get("path") or "")))
print(json.dumps(out[:12]))
"""


def thinking_around(clipfile):
    """The agent's reasoning in the two minutes either side of one attempt.

    Fetched on click rather than kept, because it lives on the machine that ran the agent and
    there are 880 clips. This is the piece that turns a video into a trajectory: what it was
    thinking when it chose those coordinates."""
    row = next((r for r in attempts() if r.get("clip") == clipfile), None)
    if not row or not row.get("epoch"):
        return '<p class="empty">No timestamped attempt to align to.</p>'
    who = row.get("who", "")
    if not ZED:
        return '<p class="empty">No remote configured to read transcripts from.</p>'
    e = float(row["epoch"])
    got = zed_py(THINKING_AT_PY % (who, e - 150, e + 30), timeout=120)
    if isinstance(got, dict) and got.get("error"):
        return f'<div class="err">{html.escape(got["error"])}</div>'
    if not got:
        return '<p class="empty">Nothing in the transcript for that window.</p>'
    rows = []
    for kind, text in got:
        cls = "th" if kind == "thinking" else "tc"
        rows.append(f'<div class="{cls}"><span class="t">{html.escape(kind)}</span>'
                    f'{html.escape(str(text)[:700])}</div>')
    return f'<div class="think" style="max-height:340px">{"".join(rows)}</div>'


def _manifests():
    f = OUT / "runs.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def highlights_html(clips=None):
    """The wins, one per level, newest first.

    The point of keeping every attempt is that failures are evidence. The point of a
    highlights row is that you should not have to scroll 880 failures to find the eight
    things that worked."""
    clips = footage() if clips is None else clips
    best = {}
    for c in clips:
        if c["badge"] == "SOLVED" and c["title"] not in best:
            best[c["title"]] = c
    if not best:
        return '<p class="empty">Nothing solved yet.</p>'
    return _cards(list(best.values()))


def footage_html(clips=None):
    """An agent's attempts first, the author contraptions folded away underneath.

    Mixed together, seventy near-identical AUTHOR thumbnails buried the handful of clips
    where an agent actually did something, and nothing in the labels said which was which.
    What an agent tried is the point of this page; the author's own solution is scenery."""
    clips = footage() if clips is None else clips
    if not clips:
        return '<p class="empty">No footage yet.</p>'
    agent = [c for c in clips if c["badge"] != "AUTHOR"]
    author = [c for c in clips if c["badge"] == "AUTHOR"]
    # 881 clips is a wall, not a gallery. Show the newest and fold the rest into a details;
    # a closed details never fetches the lazy images inside it.
    head, rest = agent[:36], agent[36:]
    out = _cards(head) if head else '<p class="empty">No agent attempts recorded yet.</p>'
    if rest:
        out += (f'<details class="more"><summary>{len(rest)} older attempts</summary>'
                f'{_cards(rest)}</details>')
    if author:
        out += (f'<details class="more"><summary>and {len(author)} author contraptions '
                f'&mdash; the level designers\' own solutions, recorded so there is always '
                f'something to watch</summary>{_cards(author)}</details>')
    return out


def _cards(clips):
    cards = []
    for c in clips:
        cls = {"SOLVED": "ok", "COPIED": "copied", "AUTHOR": "author",
               "RUNNING": "run", "CRASHED": "crash", "STALLED": "crash"}.get(c["badge"], "no")
        fresh = '<span class="v new">NEW</span>' if c.get("age", 1e9) < 3600 else ""
        # The whole card is the click target, with an overlay so a click lands on the card
        # rather than on the video's own play button -- clicking most tiles used to do
        # nothing at all. Seeking off frame 0 because every clip opens on a menu bar.
        cards.append(
            f'<figure class="card" onclick="pick(this,\'/{c["file"]}\','
            f'\'{html.escape(c["title"])}\')">'
            f'<span class="v {cls}">{html.escape(c["badge"])}</span>{fresh}'
            f'<span class="hit"></span>'
            # A still, not a media element. At 881 clips a <video> per card is 881 players
            # fetching headers at once, which crashes the tab. These are lazy images the
            # browser skips entirely while their <details> is closed.
            + f'<div class="shot">'
            + (f'<img class="thumb" loading="lazy" decoding="async" '
               f'src="/thumbs/{c["thumb"]}" alt="{html.escape(c["title"])}">'
               if c.get("thumb") else '<div class="norec">no still</div>')
            + '</div>'
            f'<figcaption><span class="cardname">{html.escape(c["title"])}</span>'
            f'<span class="cardpl">{html.escape(c["who"])} &middot; {c["kind"]} '
            f'&middot; {c["when"]}'
            + (' &middot; barely moves' if c["quiet"] else "")
            + (f'<br>{html.escape(c["places"])}' if c.get("places") else "")
            + "</span></figcaption></figure>")
    return f'<div class="gallery">{"".join(cards)}</div>'


def banner_html():
    rows = attempts()
    live_row = next((r for r in reversed(rows) if r.get("verdict") == "RUNNING"), None)
    if not live_row:
        return ""
    stem = pathlib.Path(live_row.get("level", "")).stem
    order = []
    for lg in OUT.glob(f"{stem}_claude.log"):
        for line in lg.read_text(errors="replace").splitlines():
            m = re.search(r"STATE \d+ '([^']+)'", line)
            if m and (not order or order[-1] != m.group(1)):
                order.append(m.group(1))
    steps = "".join(f'<li>{html.escape(x)}</li>' for x in order[-6:]) or "<li>starting the game</li>"
    return (f'<h2><span class="dot"></span>Now running</h2>'
            f'<div class="nowlvl">{html.escape(stem)}</div>'
            f'<div class="pl">{html.escape(" ".join(live_row.get("places", [])))}</div>'
            f'<ol class="steps">{steps}</ol>')


def render(pick=None):
    rows = attempts()
    live_row = next((r for r in reversed(rows) if r.get("verdict") == "RUNNING"), None)

    banner = ""
    if live_row:
        stem = pathlib.Path(live_row.get("level", "")).stem
        states = []
        for lg in OUT.glob(f"{stem}_claude.log"):
            for line in lg.read_text(errors="replace").splitlines():
                m = re.search(r"STATE \d+ '([^']+)'", line)
                if m:
                    states.append(m.group(1))
        seen, order = set(), []
        for st in states:
            if st not in seen:
                seen.add(st); order.append(st)
        steps = "".join(f'<li>{html.escape(x)}</li>' for x in order[-6:]) or "<li>starting the game</li>"
        banner = (f'<div class="panel now"><h2><span class="dot"></span>Now running</h2>'
                  f'<div class="nowlvl">{html.escape(stem)}</div>'
                  f'<div class="pl">{html.escape(" ".join(live_row.get("places", [])))}</div>'
                  f'<ol class="steps">{steps}</ol></div>')

    body = []
    for r in reversed(rows):
        v = r.get("verdict", "?")
        cls = {"SOLVED": "ok", "RUNNING": "run", "COPIED": "copied"}.get(v, "no")
        body.append(
            f'<div class="att"><div class="top"><span class="lvl">'
            f'{html.escape(r.get("level","").split("/")[-1])}'
            f'<span class="who">{html.escape(r.get("who","claude"))}</span></span>'
            f'<span class="v {cls}">{html.escape(v)}</span></div>'
            f'<div class="pl">{html.escape(" ".join(r.get("places", [])))}</div>'
            f'<div class="t">{html.escape(r.get("time",""))}'
            + (f' &middot; empty level: {html.escape(r.get("empty",""))}' if r.get("empty") else "")
            + "</div></div>")
    att = "".join(body) or '<p class="empty">Nothing yet.</p>'

    solved = sum(1 for r in rows if r.get("verdict") == "SOLVED")
    done = sum(1 for r in rows if r.get("verdict") in ("SOLVED", "NOT SOLVED", "COPIED"))
    stats = (f'<div><span class="v2">{solved}/{done}</span><br><span class="k">solved</span></div>'
             f'<div><span class="v2">{len(rows)}</span><br><span class="k">attempts</span></div>')

    clips = footage()
    want = next((c for c in clips if c["stem"] == pick), None) or (clips[0] if clips else None)
    # The stage opens on whatever is live, because that is what somebody opening the page
    # came for; it falls back to the newest clip when nothing is running.
    live = live_now()
    src = f'/{want["file"]}' if want else ""
    title = live or (want["title"] if want else "nothing recorded yet")
    stage = ("video{display:none}" if live else "img#live{display:none}")

    return (PAGE.replace("%LIVE%", live_html()).replace("%LEVELS%", levels_html())
            .replace("%ATTEMPTS%", att).replace("%STATS%", stats)
            .replace("%STAGESRC%", src).replace("%RACE%", race_html()).replace("%STAGETITLE%", html.escape(title))
            .replace("</style>", f".stage {stage}</style>")
            .replace("%HIGHLIGHTS%", highlights_html(clips))
            .replace("%GALLERY%", footage_html(clips)))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0].lstrip("/")
        if path in ("", "index.html"):
            jog()                    # opening the page counts as watching
            pick = None
            if "?" in self.path and "v=" in self.path:
                pick = self.path.split("v=")[1].split("&")[0]
            return self._send(render(pick).encode(), "text/html; charset=utf-8")
        if path == "banner":
            return self._send(banner_html().encode(), "text/html; charset=utf-8")
        if path == "live":
            return self._send(live_html().encode(), "text/html; charset=utf-8")
        if path == "agent":
            return self._send(agent_html().encode(), "text/html; charset=utf-8")
        if path == "clip":
            f = urllib.parse.parse_qs(self.path.split("?", 1)[-1]).get("f", [""])[0]
            return self._send(clip_detail(f).encode(), "text/html; charset=utf-8")
        if path == "clipthink":
            f = urllib.parse.parse_qs(self.path.split("?", 1)[-1]).get("f", [""])[0]
            return self._send(thinking_around(f).encode(), "text/html; charset=utf-8")
        if path == "rec":
            return self._send(recorder_html().encode(), "text/html; charset=utf-8")
        if path == "status":
            return self._send(status_html().encode(), "text/html; charset=utf-8")
        if path == "race":
            return self._send(race_html().encode(), "text/html; charset=utf-8")
        if path == "livenow":
            return self._send(live_now().encode(), "text/plain; charset=utf-8")
        if path == "thinking":
            return self._send(thinking_html().encode(), "text/html; charset=utf-8")
        if path == "spend":
            return self._send(spend_html().encode(), "text/html; charset=utf-8")
        if path == "n":                      # cheap change-token so the page can self-reload
            f = OUT / "attempts.jsonl"
            tok = str(sum(g.stat().st_mtime for g in OUT.glob("attempts*.jsonl")))
            return self._send(tok.encode(), "text/plain")
        f = OUT / path
        if f.is_file() and f.parent in (OUT, OUT / "archive", THUMBS):
            mime = {"png": "image/png", "mp4": "video/mp4", "jpg": "image/jpeg"}.get(f.suffix.lstrip("."), "application/octet-stream")
            return self._send(f.read_bytes(), mime)
        self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0].lstrip("/")
        n = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        jog()                        # anything you do here counts as watching
        if path == "jog":
            return self._send(recorder_html().encode(), "text/html; charset=utf-8")
        if path == "play":
            a = play_round(minutes=int((form.get("minutes") or ["10"])[0]))
            body = (f'<div class="err">{html.escape(a["error"])}</div>' if "error" in a
                    else agent_html())
            return self._send(body.encode(), "text/html; charset=utf-8")
        if path == "start":
            level = (form.get("level") or [""])[0]
            if not level:
                return self._send(b"pick a level first", "text/html; charset=utf-8")
            a = start_agent(level, (form.get("provider") or ["zai"])[0])
            body = (f'<div class="err">{html.escape(a["error"])}</div>' if "error" in a
                    else agent_html())
            return self._send(body.encode(), "text/html; charset=utf-8")
        if path == "say":
            text = (form.get("text") or [""])[0].strip()
            if not text:
                return self._send(b"nothing to say", "text/html; charset=utf-8")
            if not AGENT.exists():
                return self._send(b"no agent running to tell", "text/html; charset=utf-8")
            a = json.loads(AGENT.read_text())
            body = tell_agent(a["id"], text)
            return self._send(body.encode(), "text/html; charset=utf-8")
        if path == "stop":
            if not AGENT.exists():
                return self._send(b"nothing to stop", "text/html; charset=utf-8")
            r = zed("stop", json.loads(AGENT.read_text())["id"])
            agent_status.at = 0.0            # re-read the status rather than the cached one
            body = (agent_html() if r.returncode == 0
                    else f'<div class="err">{html.escape((r.stderr or r.stdout).strip())}</div>')
            return self._send(body.encode(), "text/html; charset=utf-8")
        self.send_error(404)

    def _send(self, data, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    threading.Thread(target=recorder, daemon=True).start()
    threading.Thread(target=syncer, daemon=True).start()
    print(f"playtest dashboard: http://{BIND}:{PORT}")
    # Threaded: an ssh to zed takes a few hundred ms and must not stall the frame refresh.
    ThreadingHTTPServer((BIND, PORT), H).serve_forever()
