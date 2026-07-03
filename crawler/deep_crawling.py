import asyncio
# import redis.asyncio as redis
from crawl4ai import AsyncWebCrawler, UndetectedAdapter

# deep crawling can explore websites beyond a single page. 
# It has control over website's depth and filter content too
# The BFSDeepCrawlStrategy uses a breadth-first approach
# exploring all links at one depth before moving deeper:
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

# helps narrow down which pages to crawl. FilterChain combines multiple filters
from crawl4ai.deep_crawling.filters import FilterChain, URLPatternFilter, DomainFilter, ContentTypeFilter

# Added LXMLWebScrapingStrategy for faster HTML parsing using the lxml library. 
# This can significantly improve scraping performance, especially for large or complex pages.
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy

from crawl_config import *


async def run_crawler(url, browser_config=None, run_config=None, crawler_strategy=None):
	# create an instance of AsyncWebCrawler
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or base_browser_config) as crawler:
		try:
			# run the crawler on a URL with Stream Mode
			if run_config.stream:
				async for result in await crawler.arun(
					url=url,
					config=run_config or base_crawler_run_config,
				):
					print(f"Found {len(result.links['internal'])} internal links")
					return []
			else:
				# run the crawler on a URL without Stream Mode
				results = await crawler.arun(
					url=url,
					config=run_config or base_crawler_run_config
				)
				# Wait for ALL results to be collected before returning
				return results
		except Exception as e:
			print("EXCEPTION")
			print(f"{e}")

def process_crawl_result(results):
	urls = []
	print(f"Crawled {len(results)} pages in total")
	for result in results:
		print(f"Found {len(result.links['internal'])} in total")
		urls.append({
			"links": result.links['internal'] if result.success else None,
			"status_code": result.status_code,
			"success": result.success,
			"error_message": result.error_message,
			"redirected_status_code": result.redirected_status_code,
			"depth": result.metadata.get('depth', None),
		})
	return urls

async def get_links_using_bfs(url, max_depth=1, max_pages=1):
	
	load_proxies_from_env()

	bfs_browser_config = base_browser_config.clone(
		enable_stealth=True,
		viewport_width=1920,
    	viewport_height=1080,
	)

	filter_chain = FilterChain([
		# Only follow URLs not containing "logout" or "account" or "dashboard" or common media file extensions. This helps avoid crawling irrelevant or sensitive pages.
		URLPatternFilter(patterns=["*logout*", "*account*", "*dashboard*", r"^[^?]*$"], reverse=True),

		# only crawl specific domains
		DomainFilter(
			allowed_domains=[url.split("/")[2]], # only crawl the domain of the initial URL
			# blocked_domains=[""]
		),

		# only include specific content types
		ContentTypeFilter(allowed_types=["text/html"])
	])

	bfs_run_config = base_crawler_run_config.clone(
		deep_crawl_strategy=BFSDeepCrawlStrategy(
			max_depth=max_depth, # max number of levels to crawl - Crawl initial page + 2 levels deep
			max_pages=max_pages, # max limit of pages to crawl
			include_external=False, # do not follow links to other domains
			filter_chain=filter_chain,
		),
		magic=True,
		scraping_strategy=LXMLWebScrapingStrategy(),
		wait_until="load",
		wait_time=3.0,  # Wait 3 seconds after page load
    	delay_before_return_html=2.0,  # Additional delay
		stream=False,
		max_retries=0
	)

	bfs_crawler_strategy = get_playwright_crawl_strategy(browser_config=bfs_browser_config)

	results = await run_crawler(
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

async def run_crawler_to_scrape_html(url, browser_config=None, run_config=None, crawler_strategy=None):
	try:
		async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config) as crawler:
			result = await crawler.arun(
				url,
				config=run_config
			)
			return result
	except Exception as e:
		response = {
			"success": False,
			"error": str(e)
		}
		print(response)
		return response

async def scrape_content(url):
	# 1st pass try HTTP crawler strategy
	http_crawler_config = get_http_crawl_strategy()

	result = await run_crawler_to_scrape_html(url, crawler_strategy=http_crawler_config)

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

		result = await run_crawler_to_scrape_html(url, crawler_strategy=stealth_crawler_strategy, run_config=stealth_run_config, browser_config=stealth_browser_config)
		
		# 3rd pass try using undetected stealth mode
		if not result.success:
			undetected_browser_config = base_browser_config.clone(
				enable_stealth=True,
				viewport_width=1920,
				viewport_height=1080
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
				browser_adapter=UndetectedAdapter()
			)

			result = await run_crawler_to_scrape_html(url, crawler_strategy=undetected_crawler_strategy, run_config=undetected_run_config, browser_config=undetected_browser_config)

	return {
		"html": result.cleaned_html if result.success else None,
		"status_code": result.status_code,
		"final_crawled_url": result.url,
		"redirected_status_code": result.redirected_status_code,
		"crawling_error_message": result.error_message,
		"success": result.success
	}

if __name__ == "__main__":
	print("Running...")
	url = "https://robyns.be/nl"
	
	# result = asyncio.run(scrape_content(url))

	result = asyncio.run(get_links_using_prefetch_mode(url))
	
	print(result)
    