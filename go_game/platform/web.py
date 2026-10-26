"""Dependency-free browser research board served by the authenticated API."""
HTML_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1">
<title>Go Research Platform</title>
<style>
:root{color-scheme:light;font-family:system-ui,-apple-system,sans-serif;
background:#eef1eb;color:#1f3329}*{box-sizing:border-box}
body{margin:0}header{background:#163b30;color:#fff;padding:18px 5vw}
header h1{font-size:1.4rem;margin:0}header p{font-size:.85rem;opacity:.78}
main{max-width:1160px;margin:28px auto;padding:0 20px;
display:grid;grid-template-columns:minmax(290px,650px) minmax(240px,1fr);gap:24px}
section{background:white;padding:18px;border-radius:14px;
box-shadow:0 8px 28px #21402f0c}h2{margin:0 0 12px;font-size:1.07rem}
label{display:block;font-size:.83rem;margin:9px 0 4px}
input,select,button{font:inherit;padding:10px;border-radius:8px}
input,select{border:1px solid #bfcdc2;width:100%;background:#fff}
button{border:none;background:#1e5947;color:white;cursor:pointer}
button.secondary{background:#e6ebe8;color:#164632}
button:disabled{opacity:.5;cursor:default}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
#board{display:grid;background:#dcb77e;padding:15px;border-radius:10px;
aspect-ratio:1;gap:0;max-width:620px;width:100%;box-shadow:inset 0 0 12px #89602d33}
.cell{position:relative;border:0;border-radius:0;background:transparent;padding:0;
min-width:0;aspect-ratio:1}
.cell:before{content:"";position:absolute;inset:50% 0 auto 0;border-top:1px solid #826943}
.cell:after{content:"";position:absolute;inset:0 50% 0 auto;border-left:1px solid #826943}
.stone{position:absolute;inset:9%;border-radius:50%;z-index:2;pointer-events:none}
.stone.X{background:radial-gradient(circle at 28% 25%,#4b5651,#080d0b 70%)}
.stone.O{background:radial-gradient(circle at 25% 20%,#fff,#d4dbd4 80%);
box-shadow:0 1px 3px #3338}
.cell:hover:not(:disabled){background:#ffffff40}
.small{font-size:.84rem;color:#657969;overflow-wrap:anywhere}
#log{white-space:pre-wrap;max-height:220px;overflow:auto}
#analysis{font-family:monospace;white-space:pre-wrap;font-size:.8rem}
.status{padding:10px;background:#f1f5f0;border-radius:8px;margin:12px 0}
@media(max-width:790px){main{grid-template-columns:1fr}}
</style></head><body>
<header><h1>Go · Reinforcement Learning Platform</h1>
<p>权威落子 · 可恢复事件 · 模型分析 · 完整棋谱</p></header>
<main><section><h2>对弈棋盘</h2><div id="status" class="status">请先连接账户。</div>
<div id="board" aria-label="围棋棋盘"></div>
<div class="controls"><button id="pass">Pass</button>
<button id="analyze" class="secondary">MCTS 分析</button>
<button id="sgf" class="secondary">导出 SGF</button></div>
<div id="analysis" class="small"></div></section>
<section><h2>身份与会话</h2>
<label for="token">Bearer Token（仅当前页面内存）</label>
<input type="password" id="token" autocomplete="off" placeholder="服务端配置的访问令牌">
<div class="controls"><button id="login">验证身份</button></div>
<p class="small" id="identity"></p>
<label for="size">棋盘</label><select id="size"><option value="9">9×9</option>
<option value="5">5×5</option><option value="13">13×13</option>
<option value="19">19×19</option></select>
<label for="komi">贴目（半目整数）</label><input type="number" id="komi" value="11">
<label for="black">黑方 Actor ID</label><input id="black" placeholder="alice">
<label for="white">白方 Actor ID</label><input id="white" placeholder="bob">
<div class="controls"><button id="new">创建对局</button></div>
<label for="gid">Game ID</label><input id="gid" placeholder="粘贴已有对局 ID">
<div class="controls"><button class="secondary" id="open">打开对局</button></div>
<h2 style="margin-top:20px">权威事件</h2><div id="log" class="small"></div>
<p class="small">棋盘状态由服务端规则引擎维护。过期落子会收到 409 并重新同步；
分析结果必须绑定当前 seq 和 model_id。未提供自动死子裁决。</p>
</section></main>
<script>
let token="",identity=null,snapshot=null,streamCtl=null,pending=false;
const $=id=>document.getElementById(id);
function error(e){$('status').textContent=e.message||String(e)}
async function api(path,options={}){
 const response=await fetch(path,{...options,headers:{
  "Authorization":"Bearer "+token,...(options.body?{"Content-Type":"application/json"}:{}),
  ...(options.headers||{})}});
 if(!response.ok){let message=await response.text();
  try{const obj=JSON.parse(message);message=obj.error?.message||obj.detail||message}
  catch(_){}
  throw new Error(response.status+": "+message)}
 const type=response.headers.get("content-type")||"";
 return type.includes("json")?response.json():response.text();
}
function draw(){
 if(!snapshot)return;
 const n=snapshot.rules.board_size,board=$('board');
 board.replaceChildren();board.style.gridTemplateColumns=`repeat(${n},1fr)`;
 const actor=snapshot.to_play==="X"?snapshot.black_actor:snapshot.white_actor;
 $('status').textContent=`对局 ${snapshot.game_id.slice(0,9)} · Seq ${snapshot.seq} · `
  +(snapshot.terminated?`终局：${snapshot.score.winner}`:
    `${actor} (${snapshot.to_play}) 行棋 · passes ${snapshot.passes}`);
 for(let r=0;r<n;r++)for(let c=0;c<n;c++){
  const a=r*n+c,cell=document.createElement("button");
  cell.className="cell";cell.title=`(${r},${c})`;
  cell.disabled=pending||snapshot.terminated||!snapshot.legal_actions[a]||
    !identity||actor!==identity.subject;
  const stone=snapshot.board[r][c];
  if(stone!=="."){const child=document.createElement("span");
   child.className="stone "+stone;cell.appendChild(child)}
  cell.addEventListener("click",()=>move({kind:"place",row:r,col:c}));
  board.appendChild(cell);
 }
 $('pass').disabled=pending||snapshot.terminated||!identity||
  actor!==identity.subject;
 $('analyze').disabled=pending||snapshot.terminated;
}
async function refresh(){if(!snapshot)return;
 const next=await api("/v1/games/"+snapshot.game_id);
 if(next.state_hash!==snapshot.state_hash||next.seq!==snapshot.seq){
  snapshot=next;draw();
 }}
async function watch(){
 if(streamCtl)streamCtl.abort();
 if(!snapshot)return;
 const id=snapshot.game_id;streamCtl=new AbortController();
 let seq=snapshot.seq,buffer="";
 try{
  const response=await fetch("/v1/games/"+id+"/stream?after_seq="+seq,{
    headers:{"Authorization":"Bearer "+token},signal:streamCtl.signal});
  if(!response.ok)throw new Error("SSE "+response.status);
  const reader=response.body.getReader(),decoder=new TextDecoder();
  while(true){
   const {done,value}=await reader.read();if(done)break;
   buffer+=decoder.decode(value,{stream:true});
   let boundary;
   while((boundary=buffer.indexOf("\n\n"))>=0){
    const part=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);
    const data=part.split("\n").find(l=>l.startsWith("data: "));
    if(!data)continue;
    const item=JSON.parse(data.slice(6));
    if(item.seq!==seq+1){await refresh();seq=snapshot.seq;continue}
    seq=item.seq;
    $('log').textContent=`#${seq} · ${item.actor_id} · `
      +JSON.stringify(item.move)+"\n"+$('log').textContent;
    await refresh();
   }
  }
 }catch(e){if(e.name!=="AbortError")error(e)}
}
async function move(action){
 if(pending||!snapshot)return;
 pending=true;draw();
 try{const next=await api("/v1/games/"+snapshot.game_id+"/commands",{
  method:"POST",body:JSON.stringify({
   command_id:crypto.randomUUID(),expected_seq:snapshot.seq,
   actor_id:identity.subject,action})});
  snapshot=next;$('analysis').textContent="";draw()
 }catch(e){error(e);await refresh()}finally{pending=false;draw()}
}
$('login').onclick=async()=>{token=$('token').value.trim();
 try{identity=await api("/v1/me");$('identity').textContent=
  identity.subject+" · "+identity.role;$('black').value=identity.subject;draw()}
 catch(e){identity=null;error(e)}};
$('new').onclick=async()=>{try{
 const size=Number($('size').value),komi=Number($('komi').value);
 const response=await api("/v1/games",{method:"POST",body:JSON.stringify({
  rules:{rule_id:"research-psk-v1",board_size:size,komi_half_points:komi,
   handicap:0,schema:"rules-v1",ko_rule:"positional_superko",
   suicide:"forbidden",scoring:"area_simple",
   end_protocol:"two_pass_no_adjudication"},
  black_actor:$('black').value.trim(),white_actor:$('white').value.trim()})});
 snapshot=response;$('gid').value=response.game_id;$('log').textContent="";
 draw();watch();
 }catch(e){error(e)}};
$('open').onclick=async()=>{try{
 snapshot=await api("/v1/games/"+encodeURIComponent($('gid').value.trim()));
 $('log').textContent="";draw();watch()
 }catch(e){error(e)}};
$('pass').onclick=()=>move({kind:"pass"});
$('analyze').onclick=async()=>{if(!snapshot)return;
 try{const result=await api("/v1/games/"+snapshot.game_id+"/analysis",{
  method:"POST",body:JSON.stringify({expected_seq:snapshot.seq,simulations:8})});
  if(result.state_hash!==snapshot.state_hash){await refresh();return}
  $('analysis').textContent="Model: "+result.model_id+"\nRoot V: "+
   result.root_value_current_to_play.toFixed(3)+
   "\n最佳动作: "+result.principal_action+"\nVisits: "+
   JSON.stringify(result.visits)
 }catch(e){error(e)}};
$('sgf').onclick=async()=>{if(!snapshot)return;
 try{const sgf=await api("/v1/games/"+snapshot.game_id+"/sgf");
  const link=document.createElement("a"),url=URL.createObjectURL(new Blob([sgf],
   {type:"application/x-go-sgf"}));link.href=url;
  link.download=snapshot.game_id+".sgf";link.click();URL.revokeObjectURL(url)}
 catch(e){error(e)}};
</script></body></html>'''
