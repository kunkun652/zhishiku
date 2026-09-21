"""Loopback FastAPI + pywebview lifecycle; includes the knowledge pipeline."""
import os,sys,socket,threading,time,json,urllib.request
from pathlib import Path

def main():
    base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    data=Path(os.environ.get('ZH_DATA_ROOT',str(base/'data'))).resolve(); data.mkdir(parents=True,exist_ok=True)
    os.environ['ZH_DATA_ROOT']=str(data)
    log=open(data/'desktop.log','a',encoding='utf-8',buffering=1); sys.stdout=log; sys.stderr=log
    import uvicorn
    from app.service import app
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(128)
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    url=f'http://127.0.0.1:{port}'
    for _ in range(100):
        try:
            with urllib.request.urlopen(url+'/api/health',timeout=1) as r:
                if r.status==200: break
        except OSError: time.sleep(.1)
    else: raise RuntimeError('知识库服务未能启动，请查看 desktop.log')
    (data/'runtime.json').write_text(json.dumps({'pid':os.getpid(),'url':url,'exe':sys.executable},ensure_ascii=False),encoding='utf-8')
    try:
        if '--server-only' in sys.argv: thread.join()
        else:
            import webview
            webview.create_window('知衡 · 仿真知识库',url,width=1440,height=940,min_size=(1050,700))
            webview.start()
    finally:
        server.should_exit=True;thread.join(timeout=5);sock.close()
if __name__=='__main__': main()
