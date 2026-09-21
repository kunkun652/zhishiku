"""Isolated source preview for browser acceptance; synthetic data only."""
import json
import os
from pathlib import Path
import socket
import sys
import threading
import uvicorn

root=Path(__file__).resolve().parents[1]
os.environ['ZH_DATA_ROOT']=str(root/'evidence/trusted-preview-data')
sys.path.insert(0,str(root/'src'))
from app.service import app,pipeline
for title,text in [('机翼材料说明.txt','机翼材料试验。7075 铝合金。弹性模量、单位和适用温度应以原始试验为准。'),
                   ('结构分析方法.txt','结构静强度分析需要分别核对材料、几何、载荷和边界条件。')]:
    pipeline.import_bytes(text.encode(),title)
sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
url='http://127.0.0.1:'+str(sock.getsockname()[1])
(root/'evidence/trusted-preview.json').write_text(json.dumps({'url':url+'/#session='+app.state.access.bootstrap,'pid':os.getpid()}),'utf-8')
uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False)).run(sockets=[sock])
