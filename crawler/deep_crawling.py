import asyncio
import json

# import redis.asyncio as redis
from crawl4ai import AsyncWebCrawler

from crawler.crawl_config import (
	lxml_scraping_strategy, undetected_adapter, base_browser_config, base_crawler_run_config, base_llm_strategy,
	load_proxies_from_env, get_crawling_filter_chain, get_bfs_crawl_strategy, get_playwright_crawl_strategy,
	get_http_crawl_strategy, external_fetch, get_memory_adaptive_dispatcher, prepare_crawl_result
)


async def run_crawler_to_scrape_markup(urls, browser_config=None, run_config=None, crawler_strategy=None, dispatcher=None):

	try:
		if not isinstance(urls, list) and not urls:
			raise Exception("Bad Input")
		
		coroutines_size = 4

		payload = {}

		sem = asyncio.Semaphore(coroutines_size) # concurrency limit
		# limit how many coroutines can run at a time
		# only 4 requests can enter once
		# if 4 are already running, 5th waits until one finishes

		async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or base_browser_config) as crawler:
			
			async def crawl(url):
				async with sem:
					# avoids hammering the target site
					# lower chances of 429/403
					# makes crawler polite
					await asyncio.sleep(3) # small delay between requests
					return url, await crawler.arun(
						url,
						config=run_config or base_crawler_run_config,
						dispatcher=dispatcher or get_memory_adaptive_dispatcher())
			
			tasks = [crawl(url) for url in urls]


			# fan out several arun() calls with asyncio.gather()
			# 'await' and 'asyncio.gather()' let us start multiple async tasks at the same time
			# and wait for all of them to finish 
			results = await asyncio.gather(*tasks)
			

			for url, result in results:
				
				if result.success:
					print(f"{url} success; [status_code={result.status_code}]")

				else:
					print(f"{url} failed; [status_code={result.status_code}]")

				if url not in payload:
					payload[url] = prepare_crawl_result(result)
				else:
					print(f"Duplicated URL: {url}")

			return payload
	except Exception as e:
		error = {
			"error": str(e),
			"exception": True
		}
		return error

def process_streamed_crawl_result(pages_by_depth, result):
	print(f"url={result.url}, success={result.success}, code={result.status_code}")

	depth = result.metadata.get("depth", 0)
	if depth not in pages_by_depth:
		pages_by_depth[depth] = []

	pages_by_depth[depth].append(prepare_crawl_result(result))
	return pages_by_depth

def process_crawl_result(results):
	pages_by_depth = {}

	for result in results:
		depth = result.metadata.get("depth", 0)
		if depth not in pages_by_depth:
			pages_by_depth[depth] = []

		pages_by_depth[depth].append(prepare_crawl_result(result))
	return pages_by_depth

async def run_crawler_to_extract_links(url, browser_config=None, run_config=None, crawler_strategy=None):
	# create an instance of AsyncWebCrawler
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or base_browser_config) as crawler:
		try:
			# run the crawler on a URL with Stream Mode
			if run_config and run_config.stream:

				pages_by_depth = {}

				async for result in await crawler.arun(
					url,
					config=run_config or base_crawler_run_config
				):
					pages_by_depth = process_streamed_crawl_result(pages_by_depth, result)

				return pages_by_depth
			else:
				# run the crawler on a URL without Stream Mode
				results = await crawler.arun(
					url,
					config=run_config or base_crawler_run_config,
					dispatcher=get_memory_adaptive_dispatcher()
				)
				# Wait for ALL results to be collected before returning
				return process_crawl_result(results)
		except Exception as e:
			print("EXCEPTION")
			print(f"{e}")


async def get_links_using_bfs(url, max_depth, max_pages):
	
	load_proxies_from_env()

	# using undetected stealth mode

	bfs_run_config = base_crawler_run_config.clone(
		deep_crawl_strategy=get_bfs_crawl_strategy(
			max_depth=max_depth,
			max_pages=max_pages,
			filter_chain=get_crawling_filter_chain(url),
		),
		magic=True,
		scraping_strategy=lxml_scraping_strategy,
    	delay_before_return_html=5.0,  # Additional delay
		stream=True,
		max_retries=0
	)

	bfs_browser_config = base_browser_config.clone(
		enable_stealth=True,
		# headless=False,
	)


	bfs_crawler_strategy = get_playwright_crawl_strategy(
		browser_config=bfs_browser_config,
		browser_adapter=undetected_adapter
	)

	return await run_crawler_to_extract_links(
		url,
		browser_config=bfs_browser_config,
		run_config=bfs_run_config,
		crawler_strategy=bfs_crawler_strategy
	)
	


async def scrape_markup(urls):

	_urls = None

	# load_proxies_from_env()
	if isinstance(urls, str):
		_urls = [urls]


	browser_config = base_browser_config.clone(
		enable_stealth=True,
	)

	run_config = base_crawler_run_config.clone(
		magic=True,
		delay_before_return_html=5.0,  # Additional delay
		proxy_config=None,
		proxy_rotation_strategy=None
	)

	undetected_crawler_strategy = get_playwright_crawl_strategy(
		browser_config=browser_config,
		browser_adapter=undetected_adapter
	)

	base_memory_dispatcher = get_memory_adaptive_dispatcher()

	return await run_crawler_to_scrape_markup(
		_urls or urls,
		crawler_strategy=undetected_crawler_strategy,
		run_config=run_config,
		browser_config=browser_config,
		dispatcher=base_memory_dispatcher
	)


if __name__ == "__main__":
	print("Running...")
	url = "https://roter-recycling.com/it/"

	links = [
		"https://www.apple.com/in/",
		"https://www.apple.com/in/iphone/",
		"https://www.apple.com/in/iphone-17e/",
		"https://www.apple.com/in/watch/",
		"https://www.apple.com/in/apple-watch-ultra-3/"
	]
	
	result = asyncio.run(get_links_using_bfs(url, max_depth=5, max_pages=20))

	# result = asyncio.run(get_links_using_bfs(url,  max_depth=2, max_pages=15))
	print(result)
	