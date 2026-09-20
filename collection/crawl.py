"""Bounded public-source collection with Scrapy; downloaded content is data only."""
import hashlib, json, socket, ipaddress
from pathlib import Path
from urllib.parse import urlparse
import scrapy
from scrapy.crawler import CrawlerProcess
ROOT=Path(__file__).parent
SEEDS=[
 ('飞机机身 Fuselage','https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/fuselage/'),
 ('飞机机翼 Wing','https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/wing/'),
 ('飞机部件 Parts of an Airplane','https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/airplane-parts/'),
 ('SUPERCRUISER ARROW HS-8 高速民机概念设计','https://ntrs.nasa.gov/api/citations/19940021218/downloads/19940021218.pdf'),
 ('NASA TM102681 复合材料与金属结构碰撞载荷响应','https://ntrs.nasa.gov/api/citations/19900016052/downloads/19900016052.pdf'),
 ('机身结构与框载荷分析 NASA 19760021133','https://ntrs.nasa.gov/api/citations/19760021133/downloads/19760021133.pdf'),
 ('FAA Aircraft Construction','https://www.faa.gov/sites/faa.gov/files/2022-03/pilot_handbook.pdf'),
 ('NASA CRM 有限元模型下载入口','https://commonresearchmodel.larc.nasa.gov/fem-file/'),
 ('NASA CRM 几何模型下载入口','https://commonresearchmodel.larc.nasa.gov/geometry/'),
 ('NASA CRM 翼盒有限元模型与说明','https://commonresearchmodel.larc.nasa.gov/fem-file/wingbox-fem-files/'),
 ('NASA 复合材料航空结构发展','https://ntrs.nasa.gov/api/citations/20190002561/downloads/20190002561.pdf'),
]
HOSTS={urlparse(u).hostname for _,u in SEEDS}
class PublicBoundary:
 def process_request(self,request,spider=None):
  u=urlparse(request.url)
  if u.scheme!='https' or u.hostname not in HOSTS: raise scrapy.exceptions.IgnoreRequest('host outside registered source policy')
  for a in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
   if not ipaddress.ip_address(a[4][0]).is_global: raise scrapy.exceptions.IgnoreRequest('non-public address rejected')
class Collector(scrapy.Spider):
 name='aviation_public'
 custom_settings={'ROBOTSTXT_OBEY':True,'USER_AGENT':'ZhihengResearchBot/1.0 (local aviation reference collection)','CONCURRENT_REQUESTS':4,'CONCURRENT_REQUESTS_PER_DOMAIN':1,'DOWNLOAD_DELAY':2,'DOWNLOAD_TIMEOUT':90,'DOWNLOAD_MAXSIZE':100*1024*1024,'RETRY_TIMES':2,'CLOSESPIDER_PAGECOUNT':40,'LOG_FILE':str(ROOT/'crawl.log'),'LOG_LEVEL':'INFO','DOWNLOADER_MIDDLEWARES':{__name__+'.PublicBoundary':50},'HTTPCACHE_ENABLED':True,'HTTPCACHE_DIR':str(ROOT/'httpcache')}
 custom_settings.update(TELNETCONSOLE_ENABLED=False,REMOTE_CONTROL_ENABLED=False)
 async def start(self):
  for title,url in SEEDS: yield scrapy.Request(url,callback=self.parse,errback=self.failed,meta={'title':title,'seed':url})
 def parse(self,response):
  sha=hashlib.sha256(response.body).hexdigest(); suffix='.pdf' if response.body.startswith(b'%PDF') else Path(urlparse(response.url).path).suffix.lower()
  if suffix not in ('.pdf','.bdf','.nas','.step','.stp','.igs','.iges'):suffix='.html'
  p=ROOT/'public'/f'{sha}{suffix}'; p.parent.mkdir(exist_ok=True); p.write_bytes(response.body)
  title=response.meta['title']
  row={'url':response.url,'seed':response.meta['seed'],'title':title,'sha256':sha,'path':str(p),'http_status':response.status,'content_type':response.headers.get('Content-Type',b'').decode(),'tool':'Scrapy '+scrapy.__version__,'review':'candidate','training_permission':'unknown'}
  if suffix=='.html':
   main=response.css('main').get() or response.text
   selector=scrapy.Selector(text=main)
   text='\n'.join(t.strip() for t in selector.xpath('//text()[not(ancestor::script) and not(ancestor::style)]').getall() if t.strip())
   p.with_suffix('.txt').write_text(text,encoding='utf-8')
   if response.url.endswith('/wingbox-fem-files/'):
    for href in response.css('a::attr(href)').getall():
     url=response.urljoin(href)
     if urlparse(url).hostname in HOSTS and Path(urlparse(url).path).suffix.lower() in ('.pdf','.bdf','.nas'):
      yield scrapy.Request(url,callback=self.parse,errback=self.failed,meta={'title':'NASA CRM '+Path(urlparse(url).path).name,'seed':response.url})
  with (ROOT/'public-manifest.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 def failed(self,failure):
  with (ROOT/'crawl-failures.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'url':failure.request.url,'error':str(failure.value)},ensure_ascii=False)+'\n')
if __name__=='__main__':
 (ROOT/'source-policy.json').write_text(json.dumps({'hosts':sorted(HOSTS),'seeds':SEEDS,'robots':True,'max_pages':40,'max_file_bytes':104857600,'train':'unknown','tool_source':'https://github.com/scrapy/scrapy'},ensure_ascii=False,indent=2),encoding='utf-8')
 process=CrawlerProcess();process.crawl(Collector);process.start()

