import os
import json

import aiohttp
from crawl4ai import GeolocationConfig, PlaywrightAdapter, RoundRobinProxyStrategy, LLMExtractionStrategy, LLMConfig, HTTPCrawlerConfig
from crawl4ai.async_configs import CacheMode, ProxyConfig, BrowserConfig, CrawlerRunConfig
from crawl4ai.user_agent_generator import UserAgentGenerator
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy, AsyncHTTPCrawlerStrategy
from pydantic import BaseModel, Field
from typing import List

from dotenv import load_dotenv

load_dotenv()

ua_generator = UserAgentGenerator()

class Product(BaseModel):
	name: str
	price: str


# using BrowserConfig for global settings about the browser’s environment.
base_browser_config = BrowserConfig(
	headers={
		'Accept-Language': 'en-IN',
		'Content-Type': 'text/html'
	},
	headless=True,
	viewport_width=1280,
	viewport_height=950,
	user_agent=ua_generator.generate(os_type="windows", device_type="desktop", browser_type="chrome"),
	avoid_css=True,
	avoid_ads=True,
	use_persistent_context=True
)


base_crawler_run_config = CrawlerRunConfig(
	locale='en-IN', # Great for accessing region-specific content or testing global behavior.
	timezone_id='Asia/Kolkata',
	geolocation=GeolocationConfig(
		latitude=28.6448,
		longitude=77.2167,
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

base_http_crawl_config = HTTPCrawlerConfig(
	method="GET",
	headers={
		'Accept-Language': 'en-IN',
		'Content-Type': 'text/html'
	},
	verify_ssl=True,
	follow_redirects=True,
)

base_llm_strategy = LLMExtractionStrategy(
	llm_config=LLMConfig(
		provider=os.environ.get('OPEN_AI_MODEL'),
		api_token=os.environ.get('OPEN_AI_KEY'),
		temperature=0.0,
		max_tokens=800,
	),
	apply_chunking=True,
	schema=Product.model_json_schema(),
	extraction_type="schema", # or block
	instruction="Extract all the product with 'name' and 'price' from the content", # prompt
	chunk_token_threshold=1000, # max tokens per chunk
	overlap_rate=0.05, # 0.1 means 10% of each chunk is repeated to preserve context continuity
	input_format="html", # or markdown, fit_markdown
)

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
	else:
		if len(proxies) == 2:
			base_crawler_run_config.proxy_config = proxies 
		elif len(proxies) > 2:
			base_crawler_run_config.proxy_rotation_strategy = RoundRobinProxyStrategy(proxies)
	


# (Default): Uses Playwright for browser-based crawling, supporting JavaScript rendering 
# and complex interactions.
def get_playwright_crawl_strategy(browser_config=None, browser_adapter=None, text_mode=False):
	return AsyncPlaywrightCrawlerStrategy(
		browser_config=browser_config or base_browser_config,
		browser_adapter=browser_adapter or PlaywrightAdapter(),
		# When text_mode=True, the crawler automatically: - Disables GPU processing. - Blocks image and JavaScript resources.
		# Reduces the viewport size to 800x600 (can override this with viewport_width and viewport_height).
		text_mode=text_mode
	)

def get_http_crawl_strategy():
	return AsyncHTTPCrawlerStrategy(
		browser_config=base_http_crawl_config
	)

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