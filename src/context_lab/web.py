import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from .store import Store
from . import topics

HTML = '''<!doctype html><meta charset="utf-8"><title>Context Lab</title>
<style>body{font:14px system-ui;margin:2rem;max-width:1100px;color:#202124}header{display:flex;justify-content:space-between;align-items:center}nav button{margin:.25rem;padding:.5rem .8rem}section{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}table{width:100%;border-collapse:collapse}td,th{padding:.45rem;border-bottom:1px solid #eee;text-align:left;vertical-align:top}code{white-space:pre-wrap}small{color:#666}.status{padding:.2rem .45rem;border-radius:4px;background:#eee}</style>
<header><h1>Context Lab</h1><small id=live>loading</small></header><nav><button onclick="load('topics')">议题</button><button onclick="load('sessions')">会话</button><button onclick="load('inbox')">变更</button><button onclick="load('status')">工作树</button></nav><main id=app></main>
<script>
const app=document.querySelector('#app'), live=document.querySelector('#live');
function esc(s){return String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function api(path){let r=await fetch('/api/'+path);return r.json()}
async function load(kind){let d=await api(kind);if(kind==='topics'){app.innerHTML='<section><h2>共享议题</h2><table><tr><th>Topic</th><th>状态</th><th>标题</th><th>需求</th><th>下一步</th><th>版本</th></tr>'+d.map(x=>`<tr><td><code>${esc(x.topic)}</code><br><small>${esc(x.actor)}</small></td><td><span class=status>${esc(x.body.status)}</span></td><td>${esc(x.body.title)}</td><td>${esc((x.body.requirements||[]).join('；'))}</td><td>${esc((x.body.next_steps||[]).join('；'))}</td><td>${x.revision}</td></tr>`).join('')+'</table></section>'}else if(kind==='sessions'){app.innerHTML='<section><h2>来源会话</h2><table><tr><th>标题</th><th>会话 ID</th><th>最后事件</th><th>记录</th></tr>'+d.map(x=>`<tr><td>${esc(x.title)}</td><td><code>${esc(x.id)}</code></td><td>${esc(x.last_event)}</td><td>${x.records}</td></tr>`).join('')+'</table></section>'}else if(kind==='inbox'){app.innerHTML=`<section><h2>议题变更</h2><p>consumer: <code>${esc(d.consumer)}</code> · cursor ${d.cursor} → ${d.through}</p>`+d.changes.map(x=>`<article><b>${esc(x.topic)}</b> r${x.revision} <small>${esc(x.actor)} · ${new Date(x.created_at*1000).toLocaleString()}</small><pre>${esc(JSON.stringify(x.body,null,2))}</pre></article>`).join('')+'</section>'}else{app.innerHTML='<section><h2>当前工作树</h2><pre>'+esc(JSON.stringify(d,null,2))+'</pre></section>';}}
api('status').then(x=>live.textContent=x.branch+' · '+x.head.slice(0,8));load('topics');
</script>'''

def serve(db, workspace, port):
    store = Store(db)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed=urlparse(self.path)
            try:
                if parsed.path=='/': body=HTML.encode(); typ='text/html; charset=utf-8'
                elif parsed.path=='/api/topics': body=json.dumps(topics.topics(store,workspace),ensure_ascii=False).encode();typ='application/json'
                elif parsed.path=='/api/sessions': body=json.dumps(store.sessions(workspace),ensure_ascii=False).encode();typ='application/json'
                elif parsed.path=='/api/inbox': body=json.dumps(topics.inbox(store,workspace,'gui'),ensure_ascii=False).encode();typ='application/json'
                elif parsed.path=='/api/status': body=json.dumps(store.live(workspace),ensure_ascii=False).encode();typ='application/json'
                else: self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except Exception as e:self.send_error(500,str(e))
        def log_message(self,*args): pass
    server=HTTPServer(('127.0.0.1',port),Handler)
    print(f'Context GUI: http://127.0.0.1:{port}',flush=True)
    try: server.serve_forever()
    finally: server.server_close();store.close()
