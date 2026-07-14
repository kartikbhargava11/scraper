import asyncio
import json

# import redis.asyncio as redis
from crawl4ai import AsyncWebCrawler

from crawler.crawl_config import (
	lxml_scraping_strategy, undetected_adapter, base_browser_config, base_crawler_run_config, base_llm_strategy,
	load_proxies_from_env, get_crawling_filter_chain, get_bfs_crawl_strategy, get_playwright_crawl_strategy,
	get_http_crawl_strategy, external_fetch, get_memory_adaptive_dispatcher
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
					await asyncio.sleep(2) # small delay between requests
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
				print(type(result.extracted_content))
				if result.success:
					print(f"{url} success; [status_code={result.status_code}]")

				else:
					print(f"{url} failed; [status_code={result.status_code}]")

				if url not in payload:
					payload[url] = {
						"url": result.url, # The final crawled URL
						"page_title": result.metadata.get("title") or result.metadata.get("og:title"),
						"page_description": result.metadata.get("description") or result.metadata.get("og:description"),
						"error_message": result.error_message,
						"status_code": result.status_code,
						"redirected_status_code": result.redirected_status_code, # final redirect destination
						"number_of_images": len(result.media.get("images", [])),
						"number_of_internal_links": len(result.links.get("internal", [])),
						"extracted_content": json.loads(result.extracted_content) if result.success and isinstance(result.extracted_content, list) else None,
						"markdown": result.markdown.raw_markdown[:200] if result.success and result.markdown else None,
					}
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

	pages_by_depth[depth].append({
		"url": result.url, # The final crawled URL
		"page_title": result.metadata.get("title") or result.metadata.get("og:title"),
		"page_description": result.metadata.get("description") or result.metadata.get("og:description"),
		"error_message": result.error_message,
		"status_code": result.status_code,
		"redirected_status_code": result.redirected_status_code, # final redirect destination
		"number_of_images": len(result.media.get("images", [])),
		"number_of_internal_links": len(result.links.get("internal", [])),
		"markdown": result.markdown.raw_markdown[:200] if result.success and result.markdown else None
	})
	return pages_by_depth

def process_crawl_result(results):
	pages_by_depth = {}

	for result in results:
		depth = result.metadata.get("depth", 0)
		if depth not in pages_by_depth:
			pages_by_depth[depth] = []

		pages_by_depth[depth].append({
			"url": result.url, # The final crawled URL
			"page_title": result.metadata.get("title") or result.metadata.get("og:title"),
			"page_description": result.metadata.get("description") or result.metadata.get("og:description"),
			"error_message": result.error_message,
			"status_code": result.status_code,
			"redirected_status_code": result.redirected_status_code, # final redirect destination
			"number_of_images": len(result.media.get("images", [])),
			"number_of_internal_links": len(result.links.get("internal", [])),
			"markdown": result.markdown.raw_markdown[:200] if result.success and result.markdown else None
		})
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
					config=run_config or base_crawler_run_config,
					dispatcher=get_memory_adaptive_dispatcher()
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
		wait_until="load",
		scan_full_page=False,
    	delay_before_return_html=5.0,  # Additional delay
		stream=True,
		max_retries=0
	)

	bfs_browser_config = base_browser_config.clone(
		enable_stealth=True,
		# headless=False,
		viewport_width=1280,
    	viewport_height=950
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



async def extract_product(url):

	urls = list(url)

	llm_browser_config = base_browser_config.clone(
		enable_stealth=True
	)

	llm_run_config = base_crawler_run_config.clone(
		magic=True,
		override_navigator=True,
		simulate_user=True,
		delay_before_return_html=8.0,  # Additional delay
		extraction_strategy=base_llm_strategy,
		proxy_config=None,
		proxy_rotation_strategy=None
	)

	undetected_crawler_strategy = get_playwright_crawl_strategy(
		browser_config=llm_browser_config,
		browser_adapter=undetected_adapter
	)

	base_memory_dispatcher = get_memory_adaptive_dispatcher()

	result = await run_crawler_to_scrape_markup(
		urls,
		browser_config=llm_browser_config,
		run_config=llm_run_config,
		crawler_strategy=undetected_crawler_strategy,
		dispatcher=base_memory_dispatcher
	)

	if isinstance(result, dict) and result.get('exception', False):
		return None
	
	return result


async def scrape_markup(urls):


	# load_proxies_from_env()

	browser_config = base_browser_config.clone(
		enable_stealth=True
	)

	run_config = base_crawler_run_config.clone(
		magic=True,
		override_navigator=True,
		simulate_user=True,
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
		urls,
		crawler_strategy=undetected_crawler_strategy,
		run_config=run_config,
		browser_config=browser_config,
		dispatcher=base_memory_dispatcher
	)


if __name__ == "__main__":
	print("Running...")
	url = "https://www.apple.com/in/"

	links = [
		"https://www.apple.com/in/",
		"https://www.apple.com/in/iphone/",
		"https://www.apple.com/in/iphone-17e/",
		"https://www.apple.com/in/watch/",
		"https://www.apple.com/in/apple-watch-ultra-3/"
	]
	
	result = asyncio.run(scrape_markup(links))

	# result = asyncio.run(get_links_using_bfs(url,  max_depth=2, max_pages=15))
	print(result)
	