import asyncio

from crawl4ai import AsyncWebCrawler, UndetectedAdapter, RoundRobinProxyStrategy

from crawl_config import *


async def run_crawler_batch(urls, browser_config=None, run_config=None, crawler_strategy=None, dispatcher=None):

	response_dict = {}
	# Create crawler instance
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or base_browser_config) as crawler:

		for url in urls:
			try:
				result = await crawler.arun(
					url=url['url_address'],
					config=run_config or base_crawler_run_config,
				)
				response_dict[url['url_id']] = {
					"url_id": url['url_id'],
					"url_address": url['url_address'],
					"redirected_status_code": result.redirected_status_code,
					"final_crawled_url": result.url,
					"status_code": result.status_code,
					"html": len(result.cleaned_html) if result.success else None,
					"crawling_error_message": result.error_message,
					"success": result.success,	
				}

				if result.status_code in (429, 202):
					print(f"Status code: {result.status_code}")
					print("Waiting for 5 seconds")
					await asyncio.sleep(5)
				
			except Exception as e:
				response_dict.clear()
				print(f"Exception: {str(e)}")

	return response_dict

async def try_stealth(urls):
	load_proxies_from_env()

	stealth_browser_config = base_browser_config.clone(
		enable_stealth=True,
	)
	
	stealth_run_config = base_crawler_run_config.clone(
		wait_until="load",
		magic=True,
    	delay_before_return_html=2.0,  # Additional delay
		max_retries=0,
		session_id="xx127"
	)

	crawler_strategy = get_playwright_crawl_strategy()

	return await run_crawler_batch(
		urls,
		run_config=stealth_run_config,
		crawler_strategy=crawler_strategy,
		browser_config=stealth_browser_config
	)

async def try_undetected_and_stealth(urls):

	undetected_browser_config = base_browser_config.clone(
		enable_stealth=True,
		viewport_width=1920,
		viewport_height=1080,
	)
	# create the crawler strategy with undetected adapter
	crawler_strategy = get_playwright_crawl_strategy(
		browser_config=undetected_browser_config,
	    browser_adapter=UndetectedAdapter()
	)

	undetected_run_config = base_crawler_run_config.clone(
		wait_until="networkidle",
		magic=True,
		simulate_user=True,
		override_navigator=True,
		session_id="xx124",
    	delay_before_return_html=4.0,  # Additional delay
		proxy_config=None,
		proxy_rotation_strategy=None
		# fallback_fetch_function=external_fetch
	)

	return await run_crawler_batch(
		urls,
		run_config=undetected_run_config,
		crawler_strategy=crawler_strategy,
		browser_config=undetected_browser_config
	)

async def scrape_html_bulk(urls):
	# urls <- list of dic
	# [
	#	{url_id: 12, url_address: 'https://google.com'},
	#	{url_id: 13, url_address: 'https://apple.com'},
	# ]

	print(f"Crawling {len(urls)} urls using STEALTH mode")

	response = await try_stealth(urls)
	
	retries = [{"url_id": url_id, "url_address": res['url_address']} for url_id, res in response.items() if not res['success']]

	print(f"{len(retries)} failed out of {len(urls)} total urls using STEALTH")

	print(f"Retrying {len(retries)} urls using UNDETECTED_STEATH")

	if retries:
		retry_response = await try_undetected_and_stealth(retries)

		failed = [{"url_id": url_id, "url_address": res['url_address']} for url_id, res in retry_response.items() if not res['success']]

		print(f"{len(failed)} failed out of {len(retry_response)} retryables urls using UNDETECTED_STEATH")

		if len(failed) < len(retry_response):
			for url_id, res in retry_response.items():
				if res['success']:
					response[url_id] = res
	
	return response
	# response <- dict of dicts
	# {
	#	12: { "url_address": 'https://google.com', .... },
	# 	13: { "url_address": 'https://apple.com', .... },
	# }

async def run_crawler_to_extract_product(url, browser_config=None, run_config=None):
	async with AsyncWebCrawler(config=browser_config or base_browser_config) as crawler:

		result = await crawler.arun(
			url,
			config=run_config
		)

		if result.success:

			data = json.loads(result.extracted_content)
			print("Extracted items:", data)

			base_llm_strategy.show_usage()

		else:
			print("Error:", result.error_message)

async def extract_product(url):

	llm_run_config = base_crawler_run_config.clone(
		extraction_strategy=base_llm_strategy
	)

	await run_crawler_to_extract_product(
		url,
		run_config=llm_run_config
	)


if __name__ == "__main__":
	print("Running...")
	urls = "https://mdcomputers.in/"
	
	asyncio.run(extract_product(urls))
