import os
from dotenv import load_dotenv
import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, RateLimiter, UndetectedAdapter, HTTPCrawlerConfig, GeolocationConfig, PlaywrightAdapter, JsonCssExtractionStrategy
from crawl4ai.async_configs import CacheMode, ProxyConfig
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy, AsyncHTTPCrawlerStrategy
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

load_dotenv()

HEADERS = { # browser identity
	'Accept-Language': 'en-US',
	'Content-Type': 'text/html'
}

human_behavior_script_one = """
	(async () => {
		// Wait random time between actions
		const randomWait = () => Math.random() * 2000 + 1000;
		
		// Simulate reading
		await new Promise(resolve => setTimeout(resolve, randomWait()));
		
		// Smooth scroll
		const smoothScroll = async () => {
			const totalHeight = document.body.scrollHeight;
			const viewHeight = window.innerHeight;
			let currentPosition = 0;
			
			while (currentPosition < totalHeight - viewHeight) {
				const scrollAmount = Math.random() * 300 + 100;
				window.scrollBy({
					top: scrollAmount,
					behavior: 'smooth'
				});
				currentPosition += scrollAmount;
				await new Promise(resolve => setTimeout(resolve, randomWait()));
			}
		};
		
		await smoothScroll();
		console.log('Human-like behavior simulation completed');
		return true;
	})()
"""
# Some sites check for specific behaviors
human_behavior_script_two = """
	(async () => {
		// Simulate human-like behavior
		const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
		
		// Random mouse movement
		const moveX = Math.random() * 100;
		const moveY = Math.random() * 100;
		
		// Simulate reading time
		await sleep(1000 + Math.random() * 2000);
		
		// Scroll slightly
		window.scrollBy(0, 100 + Math.random() * 200);
		
		console.log('Human behavior simulation complete');
		return true;
	})()
"""

# using BrowserConfig for global settings about the browser’s environment.
_base_browser_config = BrowserConfig(
	headless=True,
	headers=HEADERS,
	viewport_width=800,
    viewport_height=600,
	user_agent_mode="random",
	extra_args=[
		"--disable-extensions",
		"--disable-gpu",  # Disable GPU acceleration
		"--disable-dev-shm-usage",  # Disable /dev/shm usage
		"--no-sandbox",  # Required for Docker
	],
	text_mode=False,
	avoid_css=True,
	avoid_ads=True,
)


_base_crawler_run_config = CrawlerRunConfig(
	locale="en-US", # Great for accessing region-specific content or testing global behavior.
	timezone_id="America/Los_Angeles",
	geolocation=GeolocationConfig(
		latitude=34.0522,
		longitude=-118.2437,
		accuracy=10.0
	),
	only_text=True,
	excluded_selector="#ads, .tracker, _csrf",
	prefetch=False,
	stream=False,
	scan_full_page=True,
	exclude_external_links=True,
	process_iframes=False,
	remove_overlay_elements=True,
	cache_mode=CacheMode.BYPASS,
)


_base_http_crawl_config = HTTPCrawlerConfig(
	method="GET",
	headers=HEADERS,
	verify_ssl=True,
	follow_redirects=True,
)


# A lightweight, fast, and memory-efficient HTTP-only crawler. Ideal for simple scraping tasks 
# where browser rendering is unnecessary.
def _get_http_crawl_strategy(browser_config=None):
	return AsyncHTTPCrawlerStrategy(
		browser_config=browser_config or _base_http_crawl_config
	)


# (Default): Uses Playwright for browser-based crawling, supporting JavaScript rendering 
# and complex interactions.
def _get_playwright_crawl_strategy(browser_config=None, browser_adapter=None, text_mode=True):
	return AsyncPlaywrightCrawlerStrategy(
		browser_config=browser_config or _base_browser_config,
		browser_adapter=browser_adapter or PlaywrightAdapter(),
		# When text_mode=True, the crawler automatically: - Disables GPU processing. - Blocks image and JavaScript resources.
		# Reduces the viewport size to 800x600 (can override this with viewport_width and viewport_height).
		text_mode=text_mode
	)



dedup_links = {}
failed_links = {}

def _extract_failures(result, mode):
	global failed_links

	if result.url not in failed_links:
		failed_links[result.url] = []
	
	failed_links[result.url].append({
		"mode": mode,
		"error": result.error_message,
		"status_code": result.status_code,
		"redirected_status_code": result.redirected_status_code,
	})


def _extract_links_and_depth(result):
	global dedup_links

	for link in result.links.get('internal', []):
		if link['href'] not in dedup_links:
			dedup_links[link["href"]] = result.metadata.get('depth', 0) 




async def _run_crawler(url, mode, browser_config=None, run_config=None, crawler_strategy=None, enable_stream=True):
	# create an instance of AsyncWebCrawler
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or _base_browser_config) as crawler:
		try:
			# run the crawler on a URL with Stream Mode
			if enable_stream:
				async for result in await crawler.arun(
					url=url,
					config=run_config or _base_crawler_run_config,
				):
					print(f"Found {len(result.links['internal'])} internal links")
					if not result.success:
						_extract_failures(result, mode)
					else:
						# extracting links from the result (instance of the CrawlerResult class)
						_extract_links_and_depth(result)
			else:
				# run the crawler on a URL without Stream Mode
				results = await crawler.arun(
					url=url,
					config=run_config or _base_crawler_run_config
				)
				# Wait for ALL results to be collected before returning
				for result in results:
					# failure
					if not result.success:
						_extract_failures(result, mode)
					# success
					else:
						_extract_links_and_depth(result)
		except Exception as e:
			print("EXCEPTION")
			print(f"{e}")


async def _get_links_using_bfs(url, max_depth=1, max_pages=3):
	global dedup_links
	global failed_links
	dedup_links.clear()
	failed_links.clear()

	bfs_browser_config = _base_browser_config.clone(
		enable_stealth=True,
		viewport_width=1920,
    	viewport_height=1080,
	)

	filter_chain = FilterChain([
		# Only follow URLs not containing "logout" or "account" or "dashboard" or common media file extensions. This helps avoid crawling irrelevant or sensitive pages.
		URLPatternFilter(patterns=["*logout*", "*account*", "*dashboard*", "*.jpg", "*.jpeg", "*.pdf", "*.gif", "*.png", "*.mp4", "*.mp3", "*.avif", "*.avi"], reverse=True),

		# only crawl specific domains
		DomainFilter(
			allowed_domains=[url.split("/")[2]], # only crawl the domain of the initial URL
			# blocked_domains=[""]
		),

		# only include specific content types
		ContentTypeFilter(allowed_types=["text/html"])
	])

	bfs_run_config = _base_crawler_run_config.clone(
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
		stream=True,
		max_retries=1,
		proxy_config=[
			ProxyConfig.DIRECT,
			ProxyConfig(
				server="http://81.92.195.133:8800",
				username=os.environ['PROXY_USERNAME'],
				password=os.environ['PROXY_PASSWORD']
			)
		],
	)

	mode="bfs-regular"

	bfs_crawler_strategy = _get_playwright_crawl_strategy(browser_config=bfs_browser_config)

	await _run_crawler(
		url,
		mode,
		browser_config=bfs_browser_config,
		run_config=bfs_run_config,
		crawler_strategy=bfs_crawler_strategy
	)
	
	return dedup_links




html = None

async def _run_crawler_to_scrape_html(url, browser_config=None, run_config=None, crawler_strategy=None):
	global html
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or _base_browser_config) as crawler:
		result = await crawler.arun(
			url,
			config=run_config or _base_crawler_run_config
		)
		if result.success:
			print(f"result.success: {result.success}")
			print(f"result.status_code: {result.status_code}")
			html = result.cleaned_html
		else:
			pass

		


async def _scrape_content(url):
	global html
	# 1st pass try HTTP crawler strategy
	http_crawler_config = _get_http_crawl_strategy()

	await _run_crawler_to_scrape_html(url, crawler_strategy=http_crawler_config)


	# # 2nd pass try using stealth mode
	if not html:
		stealth_browser_config = _base_browser_config.clone(
			text_mode=True,
			enable_stealth=True,
		)

		print("STEALTH MODE ON...........")

		stealth_run_config = _base_crawler_run_config.clone(
			js_code=human_behavior_script_one,
			wait_until="networkidle",
			magic=True,
			override_navigator=True,
			simulate_user=True,
			delay_before_return_html=3.0,  # Additional delay
			max_retries=1,
			proxy_config=[
			ProxyConfig.DIRECT,
				ProxyConfig(
					server="http://81.92.195.85:8800",
					username=os.environ['PROXY_USERNAME'],
					password=os.environ['PROXY_PASSWORD']	
				),
			],
		)

		stealth_crawler_strategy = _get_playwright_crawl_strategy(browser_config=stealth_browser_config)

		await _run_crawler_to_scrape_html(url, crawler_strategy=stealth_crawler_strategy, run_config=stealth_run_config, browser_config=stealth_browser_config)


		# 3rd pass try using undetected stealth mode
		if not html:
			undetected_browser_config = _base_browser_config.clone(
				text_mode=False,
				enable_stealth=True,
				headless=False,
				viewport_width=1920,
				viewport_height=1080,
			)

			undetected_run_config = _base_crawler_run_config.clone(
				js_code=human_behavior_script_two,
				wait_until="networkidle",
				magic=True,
				only_text=False,
				simulate_user=True,
				override_navigator=True,
				delay_before_return_html=5.0,  # Additional delay
				max_retries=1,
				proxy_config=[
				ProxyConfig.DIRECT,
					ProxyConfig(
						server="http://81.92.195.133:8800",
						username=os.environ['PROXY_USERNAME'],
						password=os.environ['PROXY_PASSWORD']
					),
				],
			)

			undetected_crawler_strategy = _get_playwright_crawl_strategy(
				browser_config=undetected_browser_config,
				browser_adapter=UndetectedAdapter()
			)

			await _run_crawler_to_scrape_html(url, crawler_strategy=undetected_crawler_strategy, run_config=undetected_run_config, browser_config=undetected_browser_config)
	return html

if __name__ == "__main__":
	print("Running...")
	url = "https://www.sleep-coach.com/nl/blog/slaaphulpmiddelen/"
	
	asyncio.run(_scrape_content(url))
	
	print("Complete!")





    