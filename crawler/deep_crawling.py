import asyncio
import json

# import redis.asyncio as redis
from crawl4ai import AsyncWebCrawler

from crawler.crawl_config import (
	lxml_scraping_strategy, undetected_adapter, base_browser_config, base_crawler_run_config, base_llm_strategy, load_proxies_from_env, get_crawling_filter_chain, get_bfs_crawl_strategy, get_playwright_crawl_strategy, get_http_crawl_strategy, external_fetch 
)

async def run_crawler_to_extract_links(url, browser_config=None, run_config=None, crawler_strategy=None):
	# create an instance of AsyncWebCrawler
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or base_browser_config) as crawler:
		try:
			# run the crawler on a URL with Stream Mode
			if run_config and run_config.stream:
				async for result in await crawler.arun(
					url,
					config=run_config or base_crawler_run_config
				):
					print(f"Found {len(result.links['internal'])} internal links")
					return []
			else:
				# run the crawler on a URL without Stream Mode
				results = await crawler.arun(
					url,
					config=run_config or base_crawler_run_config
				)
				# Wait for ALL results to be collected before returning
				return results
		except Exception as e:
			print("EXCEPTION")
			print(f"{e}")
		return []

def process_crawl_result(results):
	
	pages_by_depth = {}

	for result in results:


		depth = result.metadata.get("depth", 0)
		if depth not in pages_by_depth:
			pages_by_depth[depth] = []

		pages_by_depth[depth].append({
			"url": result.url, # The final crawled URL
			"page_title": result.metadata.get("title"),
			"page_description": result.metadata.get("description"),
			"error_message": result.error_message,
			"status_code": result.status_code,
			"success": result.success, # first response
			"redirected_status_code": result.redirected_status_code, # final redirect destination
			"number_of_images": len(result.media.get("images", [])),
			"number_of_internal_links": len(result.links.get("internal", [])),
			"keyword_relevance_score": result.metadata.get('score', None)
		})

	return pages_by_depth

async def get_links_using_bfs(url, max_depth, max_pages):
	
	load_proxies_from_env()


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
		stream=False,
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

	results = await run_crawler_to_extract_links(
		url,
		browser_config=bfs_browser_config,
		run_config=bfs_run_config,
		crawler_strategy=bfs_crawler_strategy
	)
	
	return process_crawl_result(results)

async def get_links_using_prefetch_mode(url):
	prefetch_run_config = base_crawler_run_config.clone(
		prefetch=True,
		enable_stealth=True,
		proxy_config=None,
		proxy_rotation_strategy=None,
	)
	async with AsyncWebCrawler(config=base_browser_config) as crawler:
		result = await crawler.arun(url, config=prefetch_run_config)
	
	return {
		"links": result.links['internal'] if result.success else None,
		"final_url": result.url,
		"status_code": result.status_code,
		"success": result.success,
		"error_message": result.error_message,
		"redirected_status_code": result.redirected_status_code
	}

async def run_crawler_to_scrape(url, browser_config=None, run_config=None, crawler_strategy=None):
	try:
		async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config) as crawler:
			result = await crawler.arun(
				url,
				config=run_config
			)
			return result
	except Exception as e:
		error = {
			"error": str(e),
			"exception": True
		}
		return error

async def scrape_content(url):
	# 1st pass try HTTP crawler strategy
	http_crawler_config = get_http_crawl_strategy()

	result = await run_crawler_to_scrape(url, crawler_strategy=http_crawler_config)

	load_proxies_from_env()

	# 2nd pass try using stealth mode
	if not result.success:
		stealth_browser_config = base_browser_config.clone(
			enable_stealth=True,
		)

		stealth_run_config = base_crawler_run_config.clone(
			magic=True,
			override_navigator=True,
			simulate_user=True,
			delay_before_return_html=3.0,  # Additional delay
			max_retries=0,
		)

		stealth_crawler_strategy = get_playwright_crawl_strategy(browser_config=stealth_browser_config)

		result = await run_crawler_to_scrape(url, crawler_strategy=stealth_crawler_strategy, run_config=stealth_run_config, browser_config=stealth_browser_config)
		
		# 3rd pass try using undetected stealth mode
		if not result.success:
			undetected_browser_config = base_browser_config.clone(
				enable_stealth=True,
			)

			undetected_run_config = base_crawler_run_config.clone(
				magic=True,
				override_navigator=True,
				simulate_user=True,
				delay_before_return_html=5.0,  # Additional delay
				proxy_config=None,
				proxy_rotation_strategy=None,
				fallback_fetch_function=external_fetch # fallback function (firecrawl)
			)

			undetected_crawler_strategy = get_playwright_crawl_strategy(
				browser_config=undetected_browser_config,
				browser_adapter=undetected_adapter
			)

			result = await run_crawler_to_scrape(
				url,
				crawler_strategy=undetected_crawler_strategy,
				run_config=undetected_run_config,
				browser_config=undetected_browser_config
			)

	if result.success:
		return {
			"html": result.cleaned_html if result.success else None,
			"status_code": result.status_code,
			"final_crawled_url": result.url,
			"redirected_status_code": result.redirected_status_code,
			"crawling_error_message": result.error_message,
			"success": result.success
		}
	
	return result

async def extract_product(url):

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

	result = await run_crawler_to_scrape(
		url,
		browser_config=llm_browser_config,
		run_config=llm_run_config,
		crawler_strategy=undetected_crawler_strategy
	)

	
	if isinstance(result, dict) and result.get('exception', False):
			return None
	
	return {
		"success": result.success,
		"url": url,
		"redirected_status_code": result.redirected_status_code,
		"final_crawled_url": result.url,
		"status_code": result.status_code,
		"result": json.loads(result.extracted_content) if result.success else None,
		"error_message": result.error_message
	}



if __name__ == "__main__":
	print("Running...")
	url = "https://mdcomputers.in/product/corsair-ram-vengeance-lpx-cmk8gx4m1z3600c18"
	
	# result = asyncio.run(scrape_content(url))

	result = asyncio.run(extract_product(url))
	
	
	print(result)
	
    