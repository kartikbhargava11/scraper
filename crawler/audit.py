import os
import re
import json
from typing import List, Dict

import asyncio
from crawl4ai import AsyncWebCrawler, RateLimiter, UndetectedAdapter, HTTPCrawlerConfig, GeolocationConfig, PlaywrightAdapter, RoundRobinProxyStrategy
from crawl4ai.async_configs import CacheMode, ProxyConfig, BrowserConfig, CrawlerRunConfig
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy, AsyncHTTPCrawlerStrategy
from playwright.async_api import Page, BrowserContext

from crawl4ai.async_logger import AsyncLogger
from crawl4ai.user_agent_generator import UserAgentGenerator
    

# CONSTANTS
HEADERS = { # browser identity
	'Accept-Language': 'nl-NL',
	'Content-Type': 'text/html'
}

def load_proxies_from_env() -> List[Dict]:
	"Load proxies from .env"
	proxies = []

	try:
		proxy_list = os.getenv("PROXIES", "").split(",")
		for proxy in proxy_list:
			if not proxy:
				continue
			ip, port, username, password = proxy.split(":")
			proxy.append({
				"server": f"http://{ip}:{port}",
				"username": username,
				"password": password,
				"ip": ip
			})
	except Exception as e:
		print(f"Error loading proxies from .env {e}")
	return proxies

def proxy_rotation_batch():
	proxies = load_proxies_from_env()
	if not proxies:
		print("No proxies found in .env | Set PROXIES .env")
		return None
	return RoundRobinProxyStrategy(proxies)
	

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
	text_mode=True,
	avoid_css=True,
	avoid_ads=True,
	enable_stealth=True,
	use_persistent_context=True,
	max_pages_before_recycle=5,
)


_base_crawler_run_config = CrawlerRunConfig(
	locale="nl-NL", # Great for accessing region-specific content or testing global behavior.
	timezone_id="Europe/Amsterdam",
	geolocation=GeolocationConfig(
		latitude=52.3702,
		longitude=4.89517,
		accuracy=25.0
	),
	wait_until="networkidle",
	cache_mode=CacheMode.BYPASS,
	excluded_selector="#ads, .tracker, _csrf",
	stream=True,
	exclude_external_links=True,
	process_iframes=False,
	remove_overlay_elements=True,
	exclude_all_images=True,
	page_timeout=20000,
	delay_before_return_html="2.0",
	proxy_rotation_strategy=proxy_rotation_batch()
)

# MemoryAdaptiveDispatcher dynamically adjusts concurrency based on available system memory and 
# includes built-in rate limiting. This prevents out-of-memory errors and 
# avoids overwhelming target websites.
# arun_many() uses MemoryAdaptiveDispatcher by default after 0.5.0

def _get_rate_limiter(base_delay=(2.0, 3.0), max_delay=30, max_retries=2):
	return RateLimiter(
		base_delay=base_delay,
		max_delay=max_delay,
		max_retries=max_retries,
		rate_limit_codes=[429, 503, 403]
	)

def _base_memory_adaptive_dispatcher(
		memory_threshold_percent=90.0,
		critical_threshold_percent=95,
		recovery_threshold_percent=85,
		max_session_permit=4,
		check_interval=5.0,
		memory_wait_timeout=1200,
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
def _get_playwright_crawl_strategy(browser_config=None, browser_adapter=None, text_mode=True):
	return AsyncPlaywrightCrawlerStrategy(
		browser_config=browser_config or _base_browser_config,
		browser_adapter=browser_adapter or PlaywrightAdapter(),
		# When text_mode=True, the crawler automatically: - Disables GPU processing. - Blocks image and JavaScript resources.
		# Reduces the viewport size to 800x600 (can override this with viewport_width and viewport_height).
		# text_mode=text_mode
	)

failed_urls = []

def _extract_failed_pages(result, mode):
	if result.status_code in (301, 302, 307, 308) and result.redirected_status_code != 200:
		print(f"Redirected to {result.redirected_url} [Fail]")
	elif result.status_code == 202:
		print("URL is still processing, it will be given more time [Fail]")
	elif result.status_code == 403:
		print("Page you're tryna find is blocked")
	elif result.status_code == 404:
		print("Page you're tryna find ain't there")
	elif result.status_code == 429:
		print("Too many requests coz server is overwhelmed")
	elif result.status_code in (500, 501, 502, 503):
		print("Server ain't responding amigo")
	else:
		print(f"Misc Failing Case StatusCode={result.status_code} ErrorMessage={result.error_message}")

	failed_urls.append(result.url)
	return result.status_code, result.url

success_urls = []

async def _extract_succeed_pages(result, mode):
	valid_pass = True

	if result.status_code == 200 and not result.error_message:
		print("URL Pass without error message and no redirects")

	elif result.status_code == 202:
		print("URL is still processing, it will be given more time [Pass]")
		valid_pass = False
		asyncio.sleep()

	elif result.status_code in (301, 302, 307, 308) and result.redirected_status_code == 200:
		print(f"Redirected to {result.redirected_url} [OK]")

	elif result.status_code in (301, 302, 307, 308) and result.redirected_status_code != 200:
		print(f"Redirected to {result.redirected_url} [Soft Fail]")
		valid_pass = False

	else:
		print(f"Misc Passing Case StatusCode={result.status_code}, ErrorMessage={result.error_message}, RedirectCode={result.redirected_status_code}, FinalCrawlerUrl={result.url}")
		valid_pass = False

	if valid_pass:
		success_urls.append(result.url)
	else:
		failed_urls.append(result.url)

	return valid_pass, result.status_code


async def _run_crawler_batch(urls, mode=None, browser_config=None, run_config=None, crawler_strategy=None, dispatcher=None):

	async def before_return_html(page: Page, context: BrowserContext, html: str, **kwargs):
		"""Hook called before returning the HTML content"""

		print(f"[HOOK] before_return_html - Got HTML content (length: {len(html)})")
		
		return page

	

	# Create crawler instance
	crawler = AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config or _base_browser_config)

	crawler.crawler_strategy.set_hook("before_return_html", before_return_html)


	try:
		await crawler.start()
		async for result in await crawler.arun_many(
			urls=urls,
			config=run_config or _base_crawler_run_config,
			dispatcher=dispatcher or _base_memory_adaptive_dispatcher()
		):
			print(f"FinalCrawledURL={result.url}, Success={result.success}, FirstStatusCode={result.status_code} (Expected: 200 or 301), RedirectedStatusCode={result.redirected_status_code} (Expected: Empty or 200)")

			if not result.success:
				_extract_failed_pages(result, mode)
			else:
				valid_pass, status_code = await _extract_succeed_pages(result, mode)

	except Exception as e:
		print("EXCEPTION")
		print(f"{e}")
	finally:
		await crawler.close()



async def _try_stealth(urls):
	mode = "stealth-session"
	
	stealth_run_config = _base_crawler_run_config.clone(
		js_code=human_behavior_script_one,
		wait_until="load",
		magic=True,
    	delay_before_return_html=2.0,  # Additional delay
		max_retries=1,
		proxy_config=[
		ProxyConfig.DIRECT,
			ProxyConfig(
				server="http://81.92.195.85:8800",
				username="162844",
				password="FQmfCN6DSW"
			),
		],
	)

	crawler_strategy = _get_playwright_crawl_strategy()

	await _run_crawler_batch(
			urls,
			mode=mode,
			run_config=stealth_run_config,
			crawler_strategy=crawler_strategy
		)


async def _try_undetected_and_stealth(urls):
	mode = "undetected-stealth-session"

	undetected_browser_config = _base_browser_config.clone(
		headless=True,
	)
	# create the crawler strategy with undetected adapter
	crawler_strategy = _get_playwright_crawl_strategy(
		browser_config=undetected_browser_config,
	    browser_adapter=UndetectedAdapter()
	)
	undetected_run_config = _base_crawler_run_config.clone(
		wait_until="load",
		js_code=human_behavior_script_two,
		magic=True,
    	delay_before_return_html=4.0,  # Additional delay
		max_retries=1,
		proxy_config=[
		ProxyConfig.DIRECT,
			ProxyConfig(
				server="http://81.92.195.133:8800",
				username="162844",
				password="FQmfCN6DSW"
			)
		],
	)
	undetected_memory_dispatcher = _base_memory_adaptive_dispatcher(
		memory_threshold_percent=92.0,
		critical_threshold_percent=97,
		recovery_threshold_percent=92.0,
		memory_wait_timeout=1800,
		rate_limiter= _get_rate_limiter(
			base_delay=(3.0, 4.0),
			max_delay=60,
			max_retries=1
		)
	)

	await _run_crawler_batch(urls, mode=mode, run_config=undetected_run_config, crawler_strategy=crawler_strategy, browser_config=undetected_browser_config, dispatcher=undetected_memory_dispatcher)


async def _scrape_html(urls):

	# 1st pass
	await _try_stealth(urls)

	if len(failed_urls) > 0:
		print("Retrying Undetected Mode....")
		await _try_undetected_and_stealth(failed_urls)

	print(f"Success URLs: {len(success_urls)}")
	print(f"Failed URLs: {len(failed_urls)}")







    