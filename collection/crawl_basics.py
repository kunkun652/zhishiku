import crawl
from urllib.parse import urlparse
from scrapy.crawler import CrawlerProcess
crawl.SEEDS=[('FAA 飞机结构与部件基础 Aircraft Construction','https://www.faa.gov/sites/faa.gov/files/regulations_policies/handbooks_manuals/aviation/phak/05_phak_ch3.pdf'),('NASA 飞机部件功能图解 Parts of an Airplane','https://www.nasa.gov/wp-content/uploads/2015/04/parts_of_an_airplane_eng_span.pdf'),('NASA 飞机部件入门 Getting on an Airplane','https://www.nasa.gov/wp-content/uploads/2023/06/getting-on-an-airplane-k-2.pdf')]
crawl.HOSTS.update(urlparse(u).hostname for _,u in crawl.SEEDS)
process=CrawlerProcess();process.crawl(crawl.Collector);process.start()
