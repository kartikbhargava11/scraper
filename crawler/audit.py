import os

import asyncio
import aiohttp
from crawl4ai import AsyncWebCrawler, RateLimiter, UndetectedAdapter, GeolocationConfig, PlaywrightAdapter, RoundRobinProxyStrategy
from crawl4ai.async_configs import CacheMode, ProxyConfig, BrowserConfig, CrawlerRunConfig
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
from playwright.async_api import Page, BrowserContext
from crawl4ai.async_logger import AsyncLogger
from crawl4ai.user_agent_generator import UserAgentGenerator

from dotenv import load_dotenv


load_dotenv()


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

# Simulate human-like behavior
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

ua_generator = UserAgentGenerator()

# using BrowserConfig for global settings about the browser’s environment.
_base_browser_config = BrowserConfig(
	headless=True,
	viewport_width=1280,
	viewport_height=800,
	user_agent=ua_generator.generate(os_type="windows", device_type="desktop", browser_type="chrome"),
	avoid_css=True,
	avoid_ads=True,
	enable_stealth=True,
	use_persistent_context=True,
	max_pages_before_recycle=5,
)


_base_crawler_run_config = CrawlerRunConfig(
	locale=os.environ.get('LOCALE', 'en-IN'), # Great for accessing region-specific content or testing global behavior.
	timezone_id=os.environ.get('TIMEZONE', 'Asia/Kolkata'),
	geolocation=GeolocationConfig(
		latitude=os.environ.get('LAT', 28.6448),
		longitude=os.environ.get('LONG', 77.2167),
		accuracy=25.0
	),
	override_navigator=True,
	wait_until="load",
	cache_mode=CacheMode.BYPASS,
	excluded_selector="#ads, .tracker, _csrf",
	scan_full_page=True,
	stream=False,
	process_iframes=False,
	remove_overlay_elements=True,
	delay_before_return_html=2.0,
)

# MemoryAdaptiveDispatcher dynamically adjusts concurrency based on available system memory and 
# includes built-in rate limiting. This prevents out-of-memory errors and 
# avoids overwhelming target websites.
# arun_many() uses MemoryAdaptiveDispatcher by default after 0.5.0

def _get_rate_limiter(base_delay=(3.0, 5.0), max_delay=45, max_retries=1):
	return RateLimiter(
		base_delay=base_delay, # random delays between 3 and 5 seconds
		max_delay=max_delay, # cap delay at 45 seconds
		max_retries=max_retries, # retry one more time on rate limiting errors
		rate_limit_codes=[429, 503, 504, 202] # handle these http codes
	)

def _base_memory_adaptive_dispatcher(
		memory_threshold_percent=90.0, # pause if memory exceeds this
		critical_threshold_percent=95, 
		recovery_threshold_percent=85, 
		max_session_permit=4, # maximum concurrent tasks
		check_interval=5.0, # how often to check the memory
		memory_wait_timeout=1200, # raise MemoryError 
		rate_limiter=None):
	return MemoryAdaptiveDispatcher(
		memory_threshold_percent=memory_threshold_percent,
		critical_threshold_percent=critical_threshold_percent,
		recovery_threshold_percent=recovery_threshold_percent,
		max_session_permit=max_session_permit,
		check_interval=check_interval,
		rate_limiter=rate_limiter if rate_limiter is not None else _get_rate_limiter(),
		memory_wait_timeout=memory_wait_timeout
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


async def _run_crawler_batch(urls, browser_config=None, run_config=None, crawler_strategy=None, dispatcher=None):

	response_dict = {}

	# Create crawler instance
	async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or _base_browser_config) as crawler:

		_count_403s = False
		_count_429s = False
		_count_202s = False

		for url in urls:
			try:
				result = await crawler.arun(
					url=url['url_address'],
					config=run_config or _base_crawler_run_config,
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

async def _try_stealth(urls):
	proxies = load_proxies_from_env()
	
	stealth_run_config = _base_crawler_run_config.clone(
		js_code=human_behavior_script_one,
		wait_until="load",
		magic=True,
    	delay_before_return_html=2.0,  # Additional delay
		max_retries=0,
		proxy_config=proxies if len(proxies) == 2 else None,
		proxy_rotation_strategy=proxies if len(proxies) > 2 else None,
		session_id="xx127421x2281adzsa14"
	)

	crawler_strategy = _get_playwright_crawl_strategy()

	return await _run_crawler_batch(
			urls,
			run_config=stealth_run_config,
			crawler_strategy=crawler_strategy
		)


async def _try_undetected_and_stealth(urls):

	undetected_browser_config = _base_browser_config.clone(
		viewport_width=1920,
		viewport_height=1080,
	)
	# create the crawler strategy with undetected adapter
	crawler_strategy = _get_playwright_crawl_strategy(
		browser_config=undetected_browser_config,
	    browser_adapter=UndetectedAdapter()
	)
	undetected_run_config = _base_crawler_run_config.clone(
		wait_until="networkidle",
		js_code=human_behavior_script_two,
		magic=True,
		simulate_user=True,
		override_navigator=True,
		session_id="xx127421x2281adzsa14",
    	delay_before_return_html=4.0,  # Additional delay
		# fallback_fetch_function=external_fetch
	)

	return await _run_crawler_batch(
		urls,
		run_config=undetected_run_config,
		crawler_strategy=crawler_strategy,
		browser_config=undetected_browser_config
	)


async def _scrape_html_bulk(urls):
	# urls <- list of dic
	# [
	#	{url_id: 12, url_address: 'https://google.com'},
	#	{url_id: 13, url_address: 'https://apple.com'},
	# ]

	print(f"Crawling {len(urls)} urls using STEALTH mode")

	response = await _try_stealth(urls)
	
	retries = [{"url_id": url_id, "url_address": res['url_address']} for url_id, res in response.items() if not res['success']]

	print(f"{len(retries)} failed out of {len(urls)} total urls using STEALTH")

	print(f"Retrying {len(retries)} urls using UNDETECTED_STEATH")

	if retries:
		retry_response = await _try_undetected_and_stealth(retries)

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



if __name__ == "__main__":
	print("Running...")
	urls = [
		{"url_id": 1, "url_address": "https://www.finassverzekert.nl/fr/assurer-lamborghini",},
		{"url_id": 2, "url_address": "https://www.finassverzekert.nl/en/cloverleaf",},
		{"url_id": 3, "url_address": "https://www.finassverzekert.nl/en/insurance-quad-700cc",}
	]
	
	result = asyncio.run(_scrape_html_bulk(urls))
	
	print(result)
	

    