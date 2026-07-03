import os
from dotenv import load_dotenv
import asyncio
import aiohttp
import redis.asyncio as redis
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, UndetectedAdapter, HTTPCrawlerConfig, GeolocationConfig, PlaywrightAdapter, RoundRobinProxyStrategy
from crawl4ai.async_configs import CacheMode, ProxyConfig

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
from crawl4ai.user_agent_generator import UserAgentGenerator

load_dotenv()

ua_generator = UserAgentGenerator()

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

# last resort: fetch HTML via an external service
async def external_fetch(url: str) -> str:
	async with aiohttp.ClientSession() as session:
		async with session.post(
			os.environ.get('FIRECRAWL_SCRAPE_API', 'https://api.firecrawl.dev/v2/scrape'),
			json={"url": url, "formats": ["html"]},
			headers={"Authorization": f"Bearer {os.environ.get('FIRECRAWL_TOKEN')}", "Content-Type": "application/json"}
		) as resp:
			print(resp.status)
			response = await resp.text()
			return response

def load_proxies_from_env():
	"Load proxies from .env"
	proxies = []
	try:
		proxy_list = os.getenv("PROXIES", "").split(",")
		proxies.append(ProxyConfig.DIRECT)	
		for proxy in proxy_list:
			if not proxy:
				continue
			ip, port, username, password = proxy.split(":")
			proxies.append(
				ProxyConfig(
					server=f"http://{ip}:{port}",
					username=username,
					password=password,
					ip=ip
				)
			)
	except Exception as e:
		print(f"Error loading proxies from .env {e}")

	return proxies

# using BrowserConfig for global settings about the browser’s environment.
_base_browser_config = BrowserConfig(
	headless=True,
	user_agent=ua_generator.generate(os_type="windows", device_type="desktop", browser_type="chrome"),
	viewport_width=1280,
    viewport_height=950,
	extra_args=[
		"--disable-extensions",
		"--disable-gpu",  # Disable GPU acceleration
		"--disable-dev-shm-usage",  # Disable /dev/shm usage
		"--no-sandbox",  # Required for Docker
	],
	text_mode=False,
	avoid_css=True,
	avoid_ads=True,
	headers={
		'Accept-Language': os.environ.get('LOCALE', 'en-IN'),
		'Content-Type': 'text/html'
	},
)

_base_crawler_run_config = CrawlerRunConfig(
	locale=os.environ.get('LOCALE', 'en-IN'), # Great for accessing region-specific content or testing global behavior.
	timezone_id=os.environ.get('TIMEZONE', 'Asia/Kolkata'),
	geolocation=GeolocationConfig(
		latitude=os.environ.get('LAT', 28.6448),
		longitude=os.environ.get('LONG', 77.2167),
		accuracy=25.0
	),
	wait_until='networkidle',
	only_text=False,
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
	headers={
		'Accept-Language': os.environ.get('LOCALE', 'en-IN'),
		'Content-Type': 'text/html'
	},
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
def _get_playwright_crawl_strategy(browser_config=None, browser_adapter=None, text_mode=False):
	return AsyncPlaywrightCrawlerStrategy(
		browser_config=browser_config or _base_browser_config,
		browser_adapter=browser_adapter or PlaywrightAdapter(),
		# When text_mode=True, the crawler automatically: - Disables GPU processing. - Blocks image and JavaScript resources.
		# Reduces the viewport size to 800x600 (can override this with viewport_width and viewport_height).
		text_mode=text_mode
	)

async def _run_crawler(url, browser_config=None, run_config=None, crawler_strategy=None):
	# create an instance of AsyncWebCrawler
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or _base_browser_config) as crawler:
		try:
			# run the crawler on a URL with Stream Mode
			if run_config.stream:
				async for result in await crawler.arun(
					url=url,
					config=run_config or _base_crawler_run_config,
				):
					print(f"Found {len(result.links['internal'])} internal links")
					return []
			else:
				# run the crawler on a URL without Stream Mode
				results = await crawler.arun(
					url=url,
					config=run_config or _base_crawler_run_config
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

async def _get_links_using_bfs(url, max_depth=1, max_pages=1):
	
	proxies = load_proxies_from_env()

	bfs_browser_config = _base_browser_config.clone(
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
		stream=False,
		max_retries=0,
		proxy_config=proxies if len(proxies) == 2 else None,
		proxy_rotation_strategy=proxies if len(proxies) > 2 else None
	)

	bfs_crawler_strategy = _get_playwright_crawl_strategy(browser_config=bfs_browser_config)

	results = await _run_crawler(
		url,
		browser_config=bfs_browser_config,
		run_config=bfs_run_config,
		crawler_strategy=bfs_crawler_strategy
	)
	
	return process_crawl_result(results)

async def _get_links_using_prefetch_mode(url):
	run_config = _base_crawler_run_config.clone(
		prefetch=True,
		enable_stealth=True,
	)
	async with AsyncWebCrawler(config=_base_browser_config) as crawler:
		result = await crawler.arun(url, config=run_config)
	
	return {
		"links": result.links['internal'] if result.success else None,
		"final_url": result.url,
		"status_code": result.status_code,
		"success": result.success,
		"error_message": result.error_message,
		"redirected_status_code": result.redirected_status_code
	}

async def _run_crawler_to_scrape_html(url, browser_config=None, run_config=None, crawler_strategy=None):
	try:
		async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config) as crawler:
			result = await crawler.arun(
				url,
				config=run_config
			)
			return result
	except Exception as e:
		print("EXCEPTION RAISED")
		response = {
			"success": False,
			"error": str(e)
		}
		return response

async def _scrape_content(url):
	# 1st pass try HTTP crawler strategy
	http_crawler_config = _get_http_crawl_strategy()

	result = await _run_crawler_to_scrape_html(url, crawler_strategy=http_crawler_config)

	proxies = load_proxies_from_env()
	

	# 2nd pass try using stealth mode
	if not result.success:
		stealth_browser_config = _base_browser_config.clone(
			enable_stealth=True,
		)

		stealth_run_config = _base_crawler_run_config.clone(
			js_code=human_behavior_script_one,
			magic=True,
			override_navigator=True,
			simulate_user=True,
			delay_before_return_html=3.0,  # Additional delay
			max_retries=0,
			proxy_config=proxies if len(proxies) == 2 else None,
			proxy_rotation_strategy=proxies if len(proxies) > 2 else None
		)

		stealth_crawler_strategy = _get_playwright_crawl_strategy(browser_config=stealth_browser_config)

		result = await _run_crawler_to_scrape_html(url, crawler_strategy=stealth_crawler_strategy, run_config=stealth_run_config, browser_config=stealth_browser_config)

		
		# 3rd pass try using undetected stealth mode
		if not result.success:
			undetected_browser_config = _base_browser_config.clone(
				enable_stealth=True,
				viewport_width=1920,
				viewport_height=1080
			)

			undetected_run_config = _base_crawler_run_config.clone(
				js_code=human_behavior_script_two,
				magic=True,
				override_navigator=True,
				simulate_user=True,
				delay_before_return_html=5.0,  # Additional delay
				fallback_fetch_function=external_fetch # fallback function (firecrawl)
			)

			undetected_crawler_strategy = _get_playwright_crawl_strategy(
				browser_config=undetected_browser_config,
				browser_adapter=UndetectedAdapter()
			)

			result = await _run_crawler_to_scrape_html(url, crawler_strategy=undetected_crawler_strategy, run_config=undetected_run_config, browser_config=undetected_browser_config)

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
	
	# result = asyncio.run(_scrape_content(url))

	result = asyncio.run(_get_links_using_prefetch_mode(url))
	
	print(result)
    