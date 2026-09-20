"""Download pinned model/runtime files with checked HTTP range parts."""
import concurrent.futures,subprocess,hashlib
from pathlib import Path

ROOT=Path(r'D:\zhishiku\runtime')
def download(name,url,size,sha=None):
 dest=ROOT/name;parts=ROOT/(name+'.parts');parts.mkdir(parents=True,exist_ok=True)
 def part(i):
  start=i*64*1024*1024;end=min(size,start+64*1024*1024)-1;p=parts/str(i)
  if p.exists() and p.stat().st_size==end-start+1:return p
  subprocess.run(['curl.exe','-sS','-L','--fail','--retry','3','--connect-timeout','20','--max-time','600','-r',f'{start}-{end}','-o',str(p),url+('&' if '?' in url else '?')+'part='+str(i)],check=True)
  assert p.stat().st_size==end-start+1,(i,p.stat().st_size)
  print(name,i,'done',flush=True);return p
 count=(size+64*1024*1024-1)//(64*1024*1024)
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:chunks=list(pool.map(part,range(count)))
 with dest.open('wb') as out:
  for p in chunks:
   with p.open('rb') as src:
    while data:=src.read(8*1024*1024):out.write(data)
 actual=hashlib.file_digest(dest.open('rb'),'sha256').hexdigest()
 if sha:assert actual==sha,(actual,sha)
 print(name,'SHA256',actual,flush=True)
 return dest
if __name__=='__main__':
 download('bge-m3-pytorch_model.bin','https://huggingface.co/BAAI/bge-m3/resolve/5617a9f61b028005a4858fdac845db406aefb181/pytorch_model.bin?download=true',2271145830,'b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38')
 download('torch-2.6.0+cu124-cp311-cp311-win_amd64.whl','https://download.pytorch.org/whl/cu124/torch-2.6.0%2Bcu124-cp311-cp311-win_amd64.whl',2532350702)
