"""
Run the requests-based spider
Optimized with concurrent execution
"""
import sys
import argparse

sys.path.insert(0, '.')

from NodeScrapy.spiders.SimpleSpiderRequests import SimpleSpiderRequests

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run the FreeNodes spider')
    parser.add_argument('--workers', type=int, default=3, 
                       help='Number of concurrent workers (1-6, default: 3)')
    args = parser.parse_args()
    
    if args.workers < 1 or args.workers > 6:
        print("ERROR: Workers must be between 1 and 6")
        sys.exit(1)
    
    print(f"Starting spider with {args.workers} worker(s)...")
    spider = SimpleSpiderRequests(max_workers=args.workers)
    spider.crawl()
