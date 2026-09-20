"""Reversible retrieval eligibility; never modifies text or vector indexes."""
import hashlib,re

RULE='content-quality-v1'
def init(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS chunk_quality(chunk_id INTEGER PRIMARY KEY,status TEXT,reason TEXT,rule TEXT,text_hash TEXT,updated TEXT);
    CREATE TABLE IF NOT EXISTS chunk_quality_events(id INTEGER PRIMARY KEY,chunk_id INTEGER,status TEXT,reason TEXT,rule TEXT,text_hash TEXT,updated TEXT);''')

def classify(text):
    t=text.strip()
    if not t:return 'noise','空白正文'
    if re.fullmatch(r'(?:第\s*)?\d{1,5}\s*(?:页|/\s*\d{1,5})?',t):return 'suspect','可能为独立页码；需对照原页，数字参数不自动排除'
    if re.search(r'copyright|all rights reserved|版权所有|未经许可',t,re.I):return 'suspect','包含版权声明，需核实是否夹有正文'
    if len(re.findall(r'首页|登录|注册|联系我们|上一页|下一页|隐私政策',t))>=3:return 'suspect','可能为网页导航'
    if t.count('\ufffd')>max(3,len(t)//3):return 'suspect','明显解析替换字符'
    return 'body','未命中噪声规则；不按长度排除公式、单位或参数'

def get(c,cid,text):
    h=hashlib.sha256(text.encode()).hexdigest()
    row=c.execute('SELECT * FROM chunk_quality WHERE chunk_id=?',(cid,)).fetchone()
    if row and row['text_hash']==h:return dict(row)
    status,reason=classify(text)
    return {'status':status,'reason':reason,'rule':RULE,'text_hash':h,'updated':None}

def eligible(c,cid,text):return get(c,cid,text)['status']!='noise'

def filter_vectors(c,hits):
    result=[]
    for hit in hits:
        parent=str(hit.get('parent_id') or hit.get('key') or '')
        match=re.match(r'(?:v2:)?c:(\d+)',parent)
        if match:
            row=c.execute('SELECT id,text FROM chunks WHERE id=?',(int(match[1]),)).fetchone()
            if not row or not eligible(c,row['id'],row['text']):continue
        elif hit.get('file_id'):
            # Legacy hits may not carry a parent id. Compare the actual stored text.
            rows=c.execute('SELECT id,text FROM chunks WHERE file_id=? AND page=?',(hit['file_id'],hit.get('page'))).fetchall()
            matches=[r for r in rows if r['text']==hit.get('text')]
            if matches and not any(eligible(c,r['id'],r['text']) for r in matches):continue
        result.append(hit)
    return result
