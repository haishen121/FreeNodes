"""
SimpleSpider using requests + BeautifulSoup instead of Scrapy
This is a more reliable alternative that avoids Scrapy 2.16.0 bugs on Windows
Optimized with better error handling, retry logic, and performance improvements
"""
from __future__ import annotations

import os
import re
import sys
import time
import logging
import datetime as dt
from urllib.parse import urljoin
from typing import Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import yaml
from fake_useragent import UserAgent

from utils.Config import CONFIG, ConfigData

# Setup logging - output to both console and file
logger = logging.getLogger('SimpleSpider')
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter('%(message)s')
console_handler.setFormatter(console_format)

# File handler
file_handler = logging.FileHandler('scrapy.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_format = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
file_handler.setFormatter(file_format)

logger.addHandler(console_handler)
logger.addHandler(file_handler)


class SimpleSpiderRequests:
    """
    A simple spider using requests and BeautifulSoup.
    Replaces Scrapy-based SimpleSpider with equivalent functionality.
    """
    
    targets = ("clashmeta", "ndnode", "nodev2ray",
               "nodefree", "v2rayshare", "wenode")
    configs: Dict[str, ConfigData]
    
    def __init__(self, max_workers: int = 3):
        self.configs = {name: CONFIG.get(name) for name in self.targets}
        self.max_workers = max_workers
        
        # Create session with connection pooling and optimized retry logic
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=requests.adapters.Retry(
                total=2,              # Reduced from 3 to 2 retries
                backoff_factor=0.5,   # Faster retry: 0.5s, 1s
                status_forcelist=[500, 502, 503, 504],
                raise_on_status=False  # Don't raise exception on retry failure
            )
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Rotate user agents
        try:
            self.ua = UserAgent()
            self.session.headers.update({
                'User-Agent': self.ua.random,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            })
        except:
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
        
        logger.info(f"Targets: {self.targets}")
        logger.info(f"Loaded config keys: {list(self.configs.keys())}")
        
        # Validate configs
        for name, config in self.configs.items():
            if not config:
                logger.info(f"ERROR: Configuration for '{name}' is missing or empty!")
            else:
                logger.info(f"✓ Configuration for '{name}' is valid.")
    
    def _find_links(self, name: str, text: str) -> List[Tuple[str, str]]:
        """Find links in text and return them with their extension."""
        logger.info(f"{name} _find_links()")
        links = []
        pattern = self.configs[name]["pattern"]
        for link in re.findall(pattern, text):
            _, ext = os.path.splitext(link.strip())
            if ext not in (".txt", ".yaml"):
                logger.info(f"{name} could not parse {link}, skipping")
                continue
            logger.info(f"{name} found {link}")
            links.append((link, ext))
        return links
    
    def _parse_tag(self, name: str, tag) -> Tuple[str, dt.date]:
        """Parse tag and return link and date."""
        link = tag.get("href", "")
        logger.info(f"{name} _parse_tag {link}")
        date = dt.date.today()
        
        if not link:
            return link, date
        
        pattern = re.compile(r"(?:\d{4}[-年])?(\d{1,2})[-月](\d{1,2})")
        for match in pattern.finditer(str(tag)):
            if not match:
                continue
            month, day = map(int, match.groups())
            if not 0 < month < 12 or not 0 < day < 32:
                continue
            date = dt.date(dt.date.today().year, month, day)
            logger.info(f"{name} found {link} on {date}")
            break
        
        return link, date
    
    def crawl_single_target(self, name: str, config: ConfigData) -> bool:
        """Crawl a single target website. Returns True if successful."""
        
        if not config:
            logger.info(f"{name} is not configured, skipping")
            return False
        
        logger.info(f"\n{'='*60}")
        logger.info(f"{name} start")
        logger.info(f"{'='*60}")
        
        try:
            # Step 1: Fetch the main page with timeout (10 seconds)
            response = self.session.get(config["start_url"], timeout=10)
            response.raise_for_status()
            
            # Step 2: Parse the page
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Step 3: Find all matching tags
            tags = soup.select(config["selector"])
            
            if not tags:
                logger.info(f"{name} ERROR: No matching tags found")
                return False
            
            # Step 4: Extract links from all tags and find the latest date
            parsed_tags = [self._parse_tag(name, tag) for tag in tags]
            parsed_tags = [(url, date) for url, date in parsed_tags if url]
            
            if not parsed_tags:
                logger.info(f"{name} ERROR: No valid links found")
                return False
            
            # Sort by date (newest first)
            parsed_tags.sort(key=lambda x: x[1], reverse=True)
            
            up_date = dt.datetime.strptime(config["up_date"], "%Y-%m-%d").date()
            
            # Check if the latest link is newer than configured up_date
            latest_url, latest_date = parsed_tags[0]
            logger.info(f"{name} latest date on website: {latest_date}, configured up_date: {up_date}")
            
            # Check if output files exist
            txt_file = os.path.join("nodes", f"{name}.txt")
            yaml_file = os.path.join("nodes", f"{name}.yaml")
            files_exist = os.path.exists(txt_file) or os.path.exists(yaml_file)
            
            if latest_date <= up_date and files_exist:
                logger.info(f"{name} is up to date, skipping (latest: {latest_date})")
                return True  # Not an error, just no update needed
            
            if latest_date <= up_date and not files_exist:
                logger.info(f"{name} config is up to date but files missing, forcing download...")
                # Continue to download even though date is not newer
            
            logger.info(f"{name} has updates! Processing latest links...")
            
            # Process up to 3 most recent links
            success_count = 0
            for rel_url, web_date in parsed_tags[0:3]:
                logger.info(f"\n{name} processing {rel_url} ({web_date})")
                
                # Follow the blog URL with timeout
                blog_url = urljoin(config["start_url"], rel_url)
                logger.info(f"{name} accessing {blog_url}")
                
                try:
                    blog_response = self.session.get(blog_url, timeout=10)  # Increased from 5 to 10 seconds
                    blog_response.raise_for_status()
                    
                    # Find node links in blog (both .txt and .yaml)
                    node_links = self._find_links(name, blog_response.text)
                    
                    # Try to download both txt and yaml for each link
                    for link, ext in node_links:
                        # Download the content once
                        try:
                            node_response = self.session.get(link, timeout=10)  # Increased from 5 to 10 seconds
                            node_response.raise_for_status()
                            
                            # Validate response
                            if len(node_response.text) < 100:
                                if 'error' in node_response.text.lower():
                                    logger.info(f"  ⚠ WARNING: Invalid content for {link}")
                                    continue
                            
                            # Save as .txt file
                            txt_saved = False
                            yaml_saved = False
                            
                            # Try to save TXT
                            if ext == ".txt":
                                from utils.GeoLoc import base64decode
                                content = base64decode(node_response.text)
                                
                                if len(content) > 100:
                                    txt_filename = f"{name}.txt"
                                    txt_filepath = os.path.join("nodes", txt_filename)
                                    with open(txt_filepath, "w", encoding="utf-8") as f:
                                        f.write(content)
                                    logger.info(f"  ✓ Saved {txt_filepath} ({len(content)} bytes)")
                                    txt_saved = True
                                else:
                                    logger.info(f"  ⚠ WARNING: TXT content too small for {name}, skipping")
                            
                            # Try to save YAML
                            if ext == ".yaml":
                                try:
                                    # Handle encoding issues - clashmeta has emoji and special characters
                                    yaml_text = node_response.text
                                    
                                    # Method 1: Try direct parse first
                                    try:
                                        data = yaml.safe_load(yaml_text)
                                    except (yaml.YAMLError, UnicodeError):
                                        # Method 2: Remove problematic characters
                                        import re
                                        # Keep only printable ASCII + basic whitespace
                                        yaml_text = re.sub(r'[^\x20-\x7e\x0a\x0d\x09]', '', yaml_text)
                                        
                                        # Also remove YAML tags like !<str>
                                        yaml_text = re.sub(r'!<\w+>\s*', '', yaml_text)
                                        
                                        data = yaml.safe_load(yaml_text)
                                    
                                    if isinstance(data, dict) and ('proxies' in data or 'proxy-groups' in data):
                                        yaml_filename = f"{name}.yaml"
                                        yaml_filepath = os.path.join("nodes", yaml_filename)
                                        with open(yaml_filepath, "w", encoding="utf-8") as f:
                                            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
                                        logger.info(f"  ✓ Saved {yaml_filepath}")
                                        yaml_saved = True
                                    else:
                                        logger.info(f"  ⚠ WARNING: Invalid YAML structure for {name}, skipping")
                                except Exception as e:
                                    logger.info(f"  ⚠ WARNING: Failed to parse YAML: {type(e).__name__}: {str(e)[:100]}")
                            
                            # Also try to save the other format if not already saved
                            if ext == ".txt" and not yaml_saved:
                                # Try to convert and save as YAML
                                try:
                                    from utils.GeoLoc import base64decode
                                    content = base64decode(node_response.text)
                                    # Attempt to parse as YAML (some sites provide both)
                                    data = yaml.safe_load(content)
                                    if isinstance(data, dict) and ('proxies' in data or 'proxy-groups' in data):
                                        yaml_filename = f"{name}.yaml"
                                        yaml_filepath = os.path.join("nodes", yaml_filename)
                                        with open(yaml_filepath, "w", encoding="utf-8") as f:
                                            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
                                        logger.info(f"  ✓ Saved {yaml_filepath} (converted from TXT)")
                                except:
                                    pass  # It's OK if conversion fails
                            
                            elif ext == ".yaml" and not txt_saved:
                                # Try to convert and save as TXT
                                try:
                                    data = yaml.safe_load(node_response.text)
                                    if isinstance(data, dict) and 'proxies' in data:
                                        # Convert proxies to TXT format
                                        proxies = data['proxies']
                                        txt_lines = []
                                        for proxy in proxies:
                                            # Simple conversion (you may need to adjust based on actual format)
                                            txt_lines.append(str(proxy))
                                        
                                        txt_content = '\n'.join(txt_lines)
                                        if len(txt_content) > 100:
                                            txt_filename = f"{name}.txt"
                                            txt_filepath = os.path.join("nodes", txt_filename)
                                            with open(txt_filepath, "w", encoding="utf-8") as f:
                                                f.write(txt_content)
                                            logger.info(f"  ✓ Saved {txt_filepath} (converted from YAML)")
                                except:
                                    pass  # It's OK if conversion fails
                            
                            if txt_saved or yaml_saved:
                                success_count += 1
                                
                        except requests.exceptions.Timeout:
                            logger.info(f"  ✗ ERROR: Timeout downloading {link}")
                            continue
                        except Exception as e:
                            logger.info(f"  ✗ ERROR: Failed to download {link}: {e}")
                            continue
                
                except requests.exceptions.Timeout:
                    logger.info(f"  ✗ ERROR: Timeout accessing {blog_url} (5s limit)")
                    continue
                except requests.exceptions.RequestException as e:
                    logger.info(f"  ✗ ERROR: Failed to access {blog_url}: {e}")
                    continue
            
            if success_count > 0:
                # Update config with the latest date
                CONFIG.set(name, {"up_date": latest_date.strftime("%Y-%m-%d")})
                CONFIG.save()
                logger.info(f"\n{name} SUCCESS: Updated {success_count} files, config updated to {latest_date}")
            else:
                logger.info(f"\n{name} WARNING: No files were successfully downloaded")
            
            return success_count > 0
            
        except requests.exceptions.Timeout:
            logger.info(f"{name} ERROR: Timeout accessing main page (5s limit)")
            return False
        except requests.exceptions.RequestException as e:
            logger.info(f"{name} ERROR: Failed to fetch main page: {e}")
            return False
        except Exception as e:
            logger.info(f"{name} ERROR: Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _download_and_save(self, name: str, link: str, ext: str, web_date: dt.date) -> bool:
        """Download a file and save it. Returns True if successful."""
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                node_response = self.session.get(link, timeout=5)
                node_response.raise_for_status()
                
                # Validate response content
                if len(node_response.text) < 100:
                    if 'error' in node_response.text.lower() or node_response.status_code >= 500:
                        raise Exception(f"Invalid response (too short, possible error page)")
                
                # Save to file
                folder = "nodes"
                os.makedirs(folder, exist_ok=True)
                
                txt_saved = False
                yaml_saved = False
                
                if ext == ".txt":
                    from utils.GeoLoc import base64decode
                    content = base64decode(node_response.text)
                    
                    # Validate content size
                    if len(content) > 100:
                        txt_filename = f"{name}.txt"
                        txt_filepath = os.path.join(folder, txt_filename)
                        with open(txt_filepath, "w", encoding="utf-8") as f:
                            f.write(content)
                        logger.info(f"  ✓ Saved {txt_filepath} ({len(content)} bytes)")
                        txt_saved = True
                    else:
                        logger.info(f"  ⚠ WARNING: Content too small for {name}, skipping")
                
                elif ext == ".yaml":
                    try:
                        data = yaml.safe_load(node_response.text)
                        
                        # Validate YAML structure
                        if isinstance(data, dict) and ('proxies' in data or 'proxy-groups' in data):
                            yaml_filename = f"{name}.yaml"
                            yaml_filepath = os.path.join(folder, yaml_filename)
                            with open(yaml_filepath, "w", encoding="utf-8") as f:
                                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
                            logger.info(f"  ✓ Saved {yaml_filepath}")
                            yaml_saved = True
                        else:
                            logger.info(f"  ⚠ WARNING: Invalid YAML structure for {name}, skipping")
                    
                    except yaml.YAMLError as e:
                        logger.info(f"  ⚠ WARNING: Failed to parse YAML: {e}")
                
                # Try to convert and save in the other format if not already saved
                if ext == ".txt" and not yaml_saved:
                    # Try to convert and save as YAML
                    try:
                        from utils.GeoLoc import base64decode
                        content = base64decode(node_response.text)
                        # Attempt to parse as YAML
                        data = yaml.safe_load(content)
                        if isinstance(data, dict) and ('proxies' in data or 'proxy-groups' in data):
                            yaml_filename = f"{name}.yaml"
                            yaml_filepath = os.path.join(folder, yaml_filename)
                            with open(yaml_filepath, "w", encoding="utf-8") as f:
                                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
                            logger.info(f"  ✓ Saved {yaml_filepath} (converted from TXT)")
                            yaml_saved = True
                    except:
                        pass  # It's OK if conversion fails
                
                elif ext == ".yaml" and not txt_saved:
                    # Try to convert and save as TXT
                    try:
                        data = yaml.safe_load(node_response.text)
                        if isinstance(data, dict) and 'proxies' in data:
                            # Convert proxies to TXT format
                            proxies = data['proxies']
                            txt_lines = []
                            for proxy in proxies:
                                # Simple conversion (you may need to adjust based on actual format)
                                txt_lines.append(str(proxy))
                            
                            txt_content = '\n'.join(txt_lines)
                            if len(txt_content) > 100:
                                txt_filename = f"{name}.txt"
                                txt_filepath = os.path.join(folder, txt_filename)
                                with open(txt_filepath, "w", encoding="utf-8") as f:
                                    f.write(txt_content)
                                logger.info(f"  ✓ Saved {txt_filepath} (converted from YAML)")
                                txt_saved = True
                    except:
                        pass  # It's OK if conversion fails
                
                # Return success if either format was saved
                if txt_saved or yaml_saved:
                    return True
                else:
                    return False
                    
            except Exception as e:
                logger.info(f"  Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    logger.info(f"  ✗ ERROR: Failed to download {link} after {max_retries} attempts")
                    return False
        
        return False
    
    def crawl(self):
        """Main crawling logic with concurrent execution."""
        logger.info("\n" + "="*60)
        logger.info("=== Starting Crawl ===")
        logger.info(f"Max workers: {self.max_workers}")
        logger.info("="*60)
        
        start_time = time.time()
        results = {}
        
        try:
            # Option 1: Sequential crawling (more reliable)
            if self.max_workers == 1:
                logger.info("Running in sequential mode...")
                for name, config in self.configs.items():
                    logger.info(f"Processing target: {name}")
                    results[name] = self.crawl_single_target(name, config)
                    # Small delay between targets to be polite
                    time.sleep(1)
            
            # Option 2: Concurrent crawling (faster)
            else:
                logger.info(f"Running in concurrent mode with {self.max_workers} workers...")
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_name = {
                        executor.submit(self.crawl_single_target, name, config): name
                        for name, config in self.configs.items()
                    }
                    
                    for future in as_completed(future_to_name):
                        name = future_to_name[future]
                        try:
                            results[name] = future.result()
                            status = "✓ Success" if results[name] else "✗ Failed"
                            logger.info(f"Target completed: {name} [{status}]")
                        except Exception as e:
                            logger.error(f"Target {name} generated an exception: {e}")
                            results[name] = False
        finally:
            # Ensure session is closed properly
            self.session.close()
            logger.info("Session closed")
        
        # Summary
        elapsed = time.time() - start_time
        logger.info("\n" + "="*60)
        logger.info("=== Crawl Complete ===")
        logger.info("="*60)
        logger.info(f"Time elapsed: {elapsed:.2f} seconds")
        
        success = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info(f"Overall success rate: {success}/{total}")
        
        for name, result in results.items():
            status = "✓ SUCCESS" if result else "✗ FAILED"
            logger.info(f"  {status}: {name}")
        
        return results
    
if __name__ == "__main__":
    import sys
    
    spider = SimpleSpiderRequests()
    results = spider.crawl()
    
    # Exit with appropriate code
    if all(results.values()):
        sys.exit(0)  # All successful
    else:
        sys.exit(1)  # Some failed
