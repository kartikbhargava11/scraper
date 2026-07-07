import os
import json

import aiohttp
from crawl4ai import GeolocationConfig, PlaywrightAdapter, UndetectedAdapter, RoundRobinProxyStrategy, LLMExtractionStrategy, LLMConfig, HTTPCrawlerConfig, JsonCssExtractionStrategy

from crawl4ai.async_configs import CacheMode, ProxyConfig, BrowserConfig, CrawlerRunConfig

# deep crawling can explore websites beyond a single page. 
# It has control over website's depth and filter content too
# The BFSDeepCrawlStrategy uses a breadth-first approach
# exploring all links at one depth before moving deeper:
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

# helps narrow down which pages to crawl. FilterChain combines multiple filters
from crawl4ai.deep_crawling.filters import FilterChain, URLPatternFilter, DomainFilter, ContentTypeFilter, ContentRelevanceFilter, SEOFilter

# Scorers assign priority values to discovered URLs, helping the crawler focus on the most relevant content first.
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

# Added LXMLWebScrapingStrategy for faster HTML parsing using the lxml library. 
# This can significantly improve scraping performance, especially for large or complex pages.
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy

# helps rotating user agents
from crawl4ai.user_agent_generator import UserAgentGenerator

from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy, AsyncHTTPCrawlerStrategy
from pydantic import BaseModel, Field
from typing import List

from dotenv import load_dotenv

load_dotenv()

ua_generator = UserAgentGenerator()


lxml_scraping_strategy = LXMLWebScrapingStrategy()

# extraction_strategy = JsonCssExtractionStrategy()

undetected_adapter = UndetectedAdapter()


class Specs(BaseModel):
	category: str
	value: str

class Product(BaseModel):
	name: str
	short_description: str
	price: str
	brand: str
	product_code: str
	availability: str
	specs: List[Specs]


base_llm_strategy = LLMExtractionStrategy(
	llm_config=LLMConfig(
		provider=os.environ.get('OPEN_AI_MODEL'),
		api_token=os.environ.get('OPEN_AI_KEY'),
		temperature=0.0,
		max_tokens=1100,
	),
	apply_chunking=True,
	schema=Product.model_json_schema(),
	extraction_type="schema", # or block
	instruction="Extract all the products from the content with 'name', 'short_description', 'price', 'brand', 'product code', 'availability' and 'specs' fields. Short_description should not exceed 100 words. Return valid JSON", # prompt
	chunk_token_threshold=1000, # max tokens per chunk
	overlap_rate=0.05, # 0.1 means 10% of each chunk is repeated to preserve context continuity
	input_format="html", # or markdown, fit_markdown
)

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
	max_pages_before_recycle=5,
)


base_crawler_run_config = CrawlerRunConfig(
	locale='en-IN', # Great for accessing region-specific content or testing global behavior.
	timezone_id='Asia/Kolkata',
	geolocation=GeolocationConfig(
		latitude=28.6448,
		longitude=77.2167,
		accuracy=25.0
	),
	page_timeout=240000,
	override_navigator=True,
	wait_until="load",
	cache_mode=CacheMode.BYPASS,
	excluded_selector="#ads, .tracker, _csrf",
	scan_full_page=True,
	stream=False,
	simulate_user=True,
	prefetch=False,
	exclude_external_images=True,
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
		browser_config=browser_config if browser_config else base_browser_config,
		browser_adapter=browser_adapter if browser_adapter else PlaywrightAdapter(),


		# When text_mode=True, the crawler automatically: - Disables GPU processing. - Blocks image and JavaScript resources.
		# Reduces the viewport size to 800x600 (can override this with viewport_width and viewport_height).
		text_mode=text_mode
	)

def get_http_crawl_strategy():
	return AsyncHTTPCrawlerStrategy(
		browser_config=base_http_crawl_config
	)

def get_crawling_filter_chain(url):

	initial_domain = url.split("/")[2]

	filter_chain = [
		
		# Controls which domains to include or exclude
		DomainFilter(
			allowed_domains=[initial_domain],
			# blocked_domains=[""]
		),

		# matches URL patterns using wildcard syntax
		URLPatternFilter(patterns=["*[?]*", "*account*", "*cart*"], reverse=True),

		# matches URL patterns using wildcard syntax
		URLPatternFilter(patterns=["*product*"]),

		# content type filtering
		ContentTypeFilter(allowed_types=["text/html"])
	]

	return FilterChain(filter_chain)

def get_keyword_scorer():
	# Create a relevance scorer
    return KeywordRelevanceScorer(
        keywords=[""],
        weight=0.5
    )


def get_bfs_crawl_strategy(max_depth, filter_chain=None, max_pages=None):
	return BFSDeepCrawlStrategy(
		max_depth=max_depth, # number of levels to crawl beyond the starting page
		include_external=False,
		filter_chain=filter_chain if filter_chain else FilterChain(),
		max_pages=max_pages, # max number of pages to crawl
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