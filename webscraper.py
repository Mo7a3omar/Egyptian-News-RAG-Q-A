import requests
from bs4 import BeautifulSoup
import json
import time
import random
import os
import arabic_reshaper
from bidi.algorithm import get_display
import pandas as pd
from datetime import datetime
from urllib.parse import urljoin, urlparse
import logging
import re
import pyarabic.araby as araby

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EgyptianNewsScraper")

class EgyptianNewsScraper:
    def __init__(self, output_dir="egyptian_news_data"):
        """Initialize the scraper with user agents and output directory"""
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.2 Mobile/15E148 Safari/604.1'
        ]
        
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Create a session for each website to maintain cookies
        self.sessions = {}
        
        # Define website configurations with CORRECTED URLs and selectors
        self.websites = {
            'youm7': {
                'name': 'Youm7',
                'base_url': 'https://www.youm7.com',
                'section_urls': [
                    'https://www.youm7.com/Section/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%B9%D8%A7%D8%AC%D9%84%D8%A9/65/1',
                    'https://www.youm7.com/Section/%D8%B3%D9%8A%D8%A7%D8%B3%D8%A9/319/1',
                    'https://www.youm7.com/Section/%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF/318/1'
                ],
                'article_selector': 'div.col-xs-12',
                'title_selector': 'a.bigTitle',
                'link_selector': 'a.bigTitle',
                'content_selector': 'div.articlecontent',
                'date_selector': 'span.date',
                'pagination_format': 'path_replace'  # Replace the last number in path
            },
            'ahram': {
                'name': 'Al-Ahram',
                'base_url': 'https://gate.ahram.org.eg',
                'section_urls': [
                    'https://gate.ahram.org.eg/Portal/13/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1.aspx',
                    'https://gate.ahram.org.eg/Portal/4/%D8%AD%D9%80%D9%88%D8%A7%D8%AF%D8%AB.aspx',
                    'https://gate.ahram.org.eg/Portal/25/%D8%AB%D9%82%D8%A7%D9%81%D8%A9-%D9%88%D9%81%D9%86%D9%88%D9%86.aspx'
                ],
                'article_selector': 'div.item',
                'title_selector': 'h3 a',
                'link_selector': 'h3 a',
                'content_selector': 'div#topic-body',
                'date_selector': 'span.date',
                'pagination_format': 'query_param'  # Add ?page=X parameter
            },
            'masrawy': {
                'name': 'Masrawy',
                'base_url': 'https://www.masrawy.com',
                'section_urls': [
                    'https://www.masrawy.com/news/news_egypt/section/35/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D9%85%D8%B5%D8%B1#nav',
                    'https://www.masrawy.com/news/news_economy/section/206/#nav',
                    'https://www.masrawy.com/news/education#nav'
                ],
                'article_selector': 'div.item',
                'title_selector': 'h3 a',
                'link_selector': 'h3 a',
                'content_selector': 'div.ArticleDetails',
                'date_selector': 'div.date',
                'pagination_format': 'page_param'  # Add ?p=X parameter
            },
            'elwatannews': {
                'name': 'El Watan News',
                'base_url': 'https://www.elwatannews.com',
                'section_urls': [
                    'https://www.elwatannews.com/section/115',
                    'https://www.elwatannews.com/section/39',
                    'https://www.elwatannews.com/section/77'
                ],
                'article_selector': 'div.card-body',
                'title_selector': 'h3 a',
                'link_selector': 'h3 a',
                'content_selector': 'div.article-content',
                'date_selector': 'div.date',
                'pagination_format': 'page_path'  # Add /page/X to path
            },
            'egypttoday': {
                'name': 'Egypt Today',
                'base_url': 'https://www.egypttoday.com',
                'section_urls': [
                    'https://www.egypttoday.com/Section/News/1',
                    'https://www.egypttoday.com/Section/Politics/2',
                    'https://www.egypttoday.com/Section/Business/3'
                ],
                'article_selector': 'div.sectionItem',
                'title_selector': 'h3 a',
                'link_selector': 'h3 a',
                'content_selector': 'div.articleBody',
                'date_selector': 'div.date',
                'pagination_format': 'path_replace'  # Replace the last number in path
            },
            'akhbarelyom': {
                'name': 'Akhbar El Yom',
                'base_url': 'https://akhbarelyom.com/',
                'section_urls': [
                    'https://akhbarelyom.com/news/newssection/10/1/%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF',  # Politics
                    'https://akhbarelyom.com/news/newssection/1/1/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D9%85%D8%B5%D8%B1',  # Economy
                    'https://akhbarelyom.com/news/newssection/23/1/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%B1%D9%8A%D8%A7%D8%B6%D8%A9'   # Sports
                ],
                'article_selector': 'div.news-content',
                'title_selector': 'h3 a',
                'link_selector': 'h3 a',
                'content_selector': 'div.article-content',
                'date_selector': 'div.date',
                'pagination_format': 'path_replace'  # Replace the last number in path
            },
            'almasryalyoum': {
                'name': 'Al-Masry Al-Youm',
                'base_url': 'https://www.almasryalyoum.com',
                'section_urls': [
                    'https://www.almasryalyoum.com/section/index/2',
                    'https://www.almasryalyoum.com/section/index/4',
                    'https://www.almasryalyoum.com/section/index/8'
                ],
                'article_selector': 'div.col-xs-12',
                'title_selector': 'h3 a',
                'link_selector': 'h3 a',
                'content_selector': 'div.article-text',
                'date_selector': 'div.date',
                'pagination_format': 'path_replace'  # Replace the last number in path
            },
            'dostor': {
                'name': 'Al Dostor',
                'base_url': 'https://www.dostor.org',
                'section_urls': [
                    'https://www.dostor.org/category/1',  # News
                    'https://www.dostor.org/category/4',  # Politics
                    'https://www.dostor.org/category/6'   # Economy
                ],
                'article_selector': 'div.media',
                'title_selector': 'h3 a',
                'link_selector': 'h3 a',
                'content_selector': 'div.article-text',
                'date_selector': 'span.date',
                'pagination_format': 'path_replace'  # Replace the last number in path
            }
        }
        
        # Create a directory for each website
        for website in self.websites.keys():
            website_dir = os.path.join(output_dir, website)
            if not os.path.exists(website_dir):
                os.makedirs(website_dir)
            
            # Initialize a session for each website
            self.sessions[website] = requests.Session()
        
        self.all_articles = []
    
    def get_random_headers(self, website_key):
        """Generate random headers to avoid detection"""
        user_agent = random.choice(self.user_agents)
        website_config = self.websites[website_key]
        
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.7,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "Referer": website_config['base_url'],
            "sec-ch-ua": "\" Not A;Brand\";v=\"99\", \"Chromium\";v=\"99\", \"Google Chrome\";v=\"99\"",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1"
        }
    
    def normalize_arabic_text(self, text):
        """Normalize Arabic text for storage and RAG applications"""
        if not text:
            return ""
        try:
            # Normalize Arabic text without bidi processing
            # Replace various forms of Alef
            text = re.sub("[إأآا]", "ا", text)
            # Replace various forms of Yeh
            text = re.sub("ى", "ي", text)
            # Replace various forms of Teh Marbuta
            text = re.sub("ة", "ه", text)
            # Remove diacritics (optional)
            text = re.sub("[\u064B-\u065F]", "", text)
            # Remove tatweel (kashida)
            text = re.sub("\u0640", "", text)
            
            return text
        except Exception as e:
            logger.error(f"Error normalizing Arabic text: {e}")
            return text
    
    def process_arabic_for_display(self, text):
        """Process Arabic text for display purposes only (not for storage)"""
        if not text:
            return ""
        try:
            reshaped_text = arabic_reshaper.reshape(text)
            bidi_text = get_display(reshaped_text)
            return bidi_text
        except Exception as e:
            logger.error(f"Error processing Arabic text for display: {e}")
            return text
    
    def make_request(self, website_key, url, max_retries=3):
        """Make HTTP request with retry mechanism and session cookies"""
        session = self.sessions[website_key]
        
        for attempt in range(max_retries):
            try:
                # Random delay to avoid being blocked
                time.sleep(random.uniform(3, 7))
                
                headers = self.get_random_headers(website_key)
                response = session.get(url, headers=headers, timeout=30)
                
                # Check if request was successful
                if response.status_code == 200:
                    response.encoding = 'utf-8'
                    return response
                else:
                    logger.warning(f"Failed to retrieve {url}. Status code: {response.status_code}. Attempt {attempt+1}/{max_retries}")
                    
                    # If we get a 403, try clearing cookies
                    if response.status_code == 403:
                        session.cookies.clear()
                        
                    # Longer delay before retry
                    time.sleep(random.uniform(7, 15))
            except Exception as e:
                logger.error(f"Error retrieving {url}: {e}. Attempt {attempt+1}/{max_retries}")
                time.sleep(random.uniform(7, 15))
        
        logger.error(f"Failed to retrieve {url} after {max_retries} attempts")
        return None
    
    def get_pagination_url(self, website_key, base_url, page_number):
        """Generate pagination URL based on website's pagination format"""
        website_config = self.websites[website_key]
        pagination_format = website_config.get('pagination_format', 'query_param')
        
        if pagination_format == 'query_param':
            # Add ?page=X parameter
            if '?' in base_url:
                return f"{base_url}&page={page_number}"
            else:
                return f"{base_url}?page={page_number}"
        
        elif pagination_format == 'page_param':
            # Add ?p=X parameter
            if '?' in base_url:
                return f"{base_url}&p={page_number}"
            else:
                return f"{base_url}?p={page_number}"
        
        elif pagination_format == 'page_path':
            # Add /page/X to path
            if base_url.endswith('/'):
                return f"{base_url}page/{page_number}"
            else:
                return f"{base_url}/page/{page_number}"
        
        elif pagination_format == 'path_replace':
            # Replace the last number in path
            path_parts = base_url.split('/')
            if path_parts[-1].isdigit():
                path_parts[-1] = str(page_number)
                return '/'.join(path_parts)
            else:
                # If no number at the end, just add page parameter
                if '?' in base_url:
                    return f"{base_url}&page={page_number}"
                else:
                    return f"{base_url}?page={page_number}"
        
        # Default fallback
        return f"{base_url}?page={page_number}"
    
    def extract_article_links(self, website_key, section_url, max_pages=3):
        """Extract article links from a section page"""
        article_links = []
        website_config = self.websites[website_key]
        
        # First, try to get the main section page
        response = self.make_request(website_key, section_url)
        if not response:
            logger.error(f"Failed to retrieve section page: {section_url}")
            return []
        
        # Process the first page
        soup = BeautifulSoup(response.text, 'html.parser')
        first_page_links = self.extract_links_from_page(website_key, soup, section_url)
        article_links.extend(first_page_links)
        
        logger.info(f"Found {len(first_page_links)} article links on first page of {section_url}")
        
        # Now try pagination if needed
        for page in range(2, max_pages + 1):
            page_url = self.get_pagination_url(website_key, section_url, page)
            logger.info(f"Scraping article links from: {page_url}")
            
            response = self.make_request(website_key, page_url)
            if not response:
                logger.warning(f"Failed to retrieve page {page} of {section_url}")
                continue
            
            soup = BeautifulSoup(response.text, 'html.parser')
            page_links = self.extract_links_from_page(website_key, soup, page_url)
            
            if not page_links:
                logger.info(f"No articles found on page {page} of {section_url}, stopping pagination")
                break
            
            article_links.extend(page_links)
            logger.info(f"Found {len(page_links)} article links on page {page} of {section_url}")
            
            # Random delay between page requests
            time.sleep(random.uniform(3, 7))
        
        # Remove duplicates while preserving order
        unique_links = []
        seen = set()
        for link in article_links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)
        
        return unique_links
    
    def extract_links_from_page(self, website_key, soup, page_url):
        """Extract article links from a BeautifulSoup object"""
        website_config = self.websites[website_key]
        links = []
        
        # Find all article elements
        articles = soup.select(website_config['article_selector'])
        
        if not articles:
            logger.warning(f"No articles found using selector '{website_config['article_selector']}' on {page_url}")
            # Try alternative selectors as fallback
            articles = soup.select('article') or soup.select('.news-item') or soup.select('.article') or soup.select('.card')
            
            if not articles:
                logger.error(f"No articles found with fallback selectors on {page_url}")
                return links
        
        for article in articles:
            try:
                # Extract link
                link_element = None
                
                # Try the configured selector first
                if website_config['link_selector']:
                    link_element = article.select_one(website_config['link_selector'])
                
                # If that fails, try common link patterns
                if not link_element:
                    link_element = (
                        article.select_one('a') or 
                        article.select_one('h2 a') or 
                        article.select_one('h3 a') or
                        article.select_one('.title a')
                    )
                
                if link_element and link_element.has_attr('href'):
                    link = link_element['href']
                    
                    # Make sure we have absolute URLs
                    if not link.startswith('http'):
                        link = urljoin(website_config['base_url'], link)
                    
                    # Only include links from the same domain
                    if urlparse(link).netloc == urlparse(website_config['base_url']).netloc:
                        links.append(link)
            except Exception as e:
                logger.error(f"Error extracting link: {e}")
        
        return links
    
    def scrape_article(self, website_key, article_url):
        """Scrape a single article"""
        website_config = self.websites[website_key]
        
        logger.info(f"Scraping article: {article_url}")
        response = self.make_request(website_key, article_url)
        
        if not response:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        try:
            # Extract title
            title_element = soup.select_one(website_config['title_selector'])
            
            # If the configured selector fails, try common title selectors
            if not title_element:
                title_element = (
                    soup.select_one('h1') or 
                    soup.select_one('.article-title') or 
                    soup.select_one('.entry-title')
                )
            
            title = title_element.text.strip() if title_element else "No title found"
            
            # Extract date
            date_element = soup.select_one(website_config['date_selector'])
            
            # If the configured selector fails, try common date selectors
            if not date_element:
                date_element = (
                    soup.select_one('.date') or 
                    soup.select_one('.article-date') or 
                    soup.select_one('time') or
                    soup.select_one('.entry-date')
                )
            
            date = date_element.text.strip() if date_element else "No date found"
            
            # Extract content
            content_element = soup.select_one(website_config['content_selector'])
            
            # If the configured selector fails, try common content selectors
            if not content_element:
                content_element = (
                    soup.select_one('.article-text') or 
                    soup.select_one('.entry-content') or 
                    soup.select_one('.article-body') or
                    soup.select_one('.content')
                )
            
            if content_element:
                # Try to get paragraphs
                paragraphs = content_element.select('p')
                
                if paragraphs:
                    content = '\n'.join([p.text.strip() for p in paragraphs if p.text.strip()])
                else:
                    # If no paragraphs found, get all text
                    content = content_element.text.strip()
            else:
                # Fallback: try to get all paragraphs from the page
                paragraphs = soup.select('p')
                content = '\n'.join([p.text.strip() for p in paragraphs if p.text.strip() and len(p.text.strip()) > 50])
                
                if not content:
                    content = "No content found"
            
            # Store original text without bidi processing for RAG applications
            # This is the key change to fix the Arabic text formatting issue
            title_processed = title  # Store original Arabic text
            date_processed = date    # Store original date
            content_processed = content  # Store original content
            
            # Create article data dictionary
            article_data = {
                'title': title_processed,
                'original_title': title,
                'date': date_processed,
                'original_date': date,
                'content': content_processed,
                'url': article_url,
                'source': website_config['name'],
                'scrape_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            return article_data
        
        except Exception as e:
            logger.error(f"Error scraping article {article_url}: {e}")
            return None
    
    def scrape_website(self, website_key, articles_per_section=10, max_pages=3):
        """Scrape articles from a specific website"""
        website_config = self.websites[website_key]
        website_articles = []
        
        logger.info(f"\n{'='*50}")
        logger.info(f"Scraping website: {website_config['name']}")
        logger.info(f"{'='*50}\n")
        
        for section_url in website_config['section_urls']:
            logger.info(f"\nScraping section: {section_url}")
            
            # Get article links from the section
            article_links = self.extract_article_links(website_key, section_url, max_pages)
            
            # Limit the number of articles per section
            article_links = article_links[:articles_per_section]
            
            logger.info(f"Found {len(article_links)} article links in this section")
            
            # Scrape each article
            for article_url in article_links:
                article_data = self.scrape_article(website_key, article_url)
                
                if article_data:
                    website_articles.append(article_data)
                    self.all_articles.append(article_data)
                    
                    # Save individual article as JSON
                    self.save_article(website_key, article_data)
                
                # Random delay between article requests
                time.sleep(random.uniform(2, 5))
        
        # Save all articles from this website as a single JSON file
        self.save_website_articles(website_key, website_articles)
        
        return website_articles
    
    def save_article(self, website_key, article_data):
        """Save a single article as JSON file"""
        # Create a safe filename from the title
        safe_title = ''.join(c if c.isalnum() else '_' for c in article_data['title'][:50])
        filename = f"{safe_title}_{int(time.time())}.json"
        
        file_path = os.path.join(self.output_dir, website_key, filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(article_data, f, ensure_ascii=False, indent=4)
    
    def save_website_articles(self, website_key, articles):
        """Save all articles from a website as a single JSON file"""
        if not articles:
            logger.warning(f"No articles to save for {website_key}")
            return
        
        filename = f"{website_key}_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = os.path.join(self.output_dir, filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=4)
        
        logger.info(f"Saved {len(articles)} articles from {self.websites[website_key]['name']} to {file_path}")
    
    def save_all_articles(self):
        """Save all scraped articles as JSON and CSV"""
        if not self.all_articles:
            logger.warning("No articles to save")
            return
        
        # Save as JSON
        json_filename = f"all_egyptian_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        json_path = os.path.join(self.output_dir, json_filename)
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.all_articles, f, ensure_ascii=False, indent=4)
        
        # Save as CSV
        csv_filename = f"all_egyptian_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = os.path.join(self.output_dir, csv_filename)
        
        # Convert to DataFrame and save as CSV
        df = pd.DataFrame(self.all_articles)
        df.to_csv(csv_path, index=False, encoding='utf-8')
        
        logger.info(f"Saved {len(self.all_articles)} articles to:")
        logger.info(f"- JSON: {json_path}")
        logger.info(f"- CSV: {csv_path}")
    
    def run(self, articles_per_section=10, max_pages=3, websites=None):
        """Run the scraper for all configured websites or a subset"""
        start_time = time.time()
        
        # If websites is None, scrape all websites
        # Otherwise, scrape only the specified websites
        website_keys = websites if websites else self.websites.keys()
        
        for website_key in website_keys:
            if website_key not in self.websites:
                logger.warning(f"Website '{website_key}' not found in configuration. Skipping.")
                continue
                
            try:
                self.scrape_website(website_key, articles_per_section, max_pages)
            except Exception as e:
                logger.error(f"Error scraping website {website_key}: {e}")
        
        # Save all articles
        self.save_all_articles()
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"\n{'='*50}")
        logger.info(f"Scraping completed in {duration:.2f} seconds")
        logger.info(f"Total articles scraped: {len(self.all_articles)}")
        logger.info(f"{'='*50}\n")

# Run the scraper
if __name__ == "__main__":
    # Create the scraper
    scraper = EgyptianNewsScraper(output_dir="egyptian_news_dataset")
    
    # Run the scraper with custom parameters
    # Start with just a few reliable websites to test
    
    # scraper.run(
    #     articles_per_section=10, 
    #     max_pages=2,
    #     websites=['youm7', 'ahram', 'masrawy', 'dostor']
    # )
    
    # Run all websites
    scraper.run(articles_per_section=20, max_pages=3)
