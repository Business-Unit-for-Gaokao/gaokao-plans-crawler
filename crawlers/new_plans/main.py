import sys
from .crawler import NewPlanCrawler


def main():
    years_arg = sys.argv[1] if len(sys.argv) > 1 else None
    provinces_arg = sys.argv[2] if len(sys.argv) > 2 else None

    crawler = NewPlanCrawler()
    crawler.crawl(years=years_arg, province_ids=provinces_arg)


if __name__ == "__main__":
    main()
