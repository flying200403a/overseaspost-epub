# -*- coding: utf-8 -*-

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, date
from ebooklib import epub
import requests
import re
import time
import os


TARGET_DATE = os.getenv('TARGET_DATE', '').strip()   # 例如 '2026-03-28'，留空则抓今天
TOP_N = int(os.getenv('TOP_N', '50'))
RETRY_TIMES = int(os.getenv('RETRY_TIMES', '4'))
RETRY_SLEEP = int(os.getenv('RETRY_SLEEP', '2'))


class OverseasPostDailyForceN:
    BASE_URL = 'https://overseaspost.news/'
    INDEX_URL = 'https://overseaspost.news/'

    EXTRA_CSS = '''
    body {
        font-family: Georgia, "Times New Roman", "Noto Serif CJK SC", "Source Han Serif SC", serif;
        font-size: 1em;
        line-height: 1.68;
        color: #111;
        background: #fff;
    }
    h1.article-title {
        font-family: Georgia, "Times New Roman", serif;
        font-size: 2em;
        line-height: 1.2;
        margin: 0 0 0.35em 0;
        padding-bottom: 0.2em;
        color: #000;
    }
    .article-author {
        font-size: 0.95em;
        color: #444;
        margin: 0 0 0.35em 0;
        font-weight: bold;
    }
    .article-meta {
        font-size: 0.92em;
        color: #666;
        margin-bottom: 0.75em;
        font-style: italic;
    }
    .article-excerpt {
        font-size: 1em;
        color: #333;
        margin: 0 0 1.4em 0;
        padding: 0.75em 0.9em;
        background: #f7f7f7;
        border-left: 3px solid #bbb;
        line-height: 1.6;
    }
    .article-body {
        max-width: 42em;
        margin: 0 auto;
    }
    p {
        text-indent: 2em;
        margin: 0.35em 0 0.85em 0;
        text-align: justify;
    }
    h2, h3, h4 {
        font-family: Georgia, "Times New Roman", serif;
        margin-top: 1.2em;
        margin-bottom: 0.5em;
        line-height: 1.3;
        color: #000;
    }
    blockquote {
        margin: 1em 2em;
        padding-left: 1em;
        border-left: 3px solid #bbb;
        color: #333;
        font-style: italic;
    }
    a {
        color: #111;
        text-decoration: none;
    }
    hr {
        border: none;
        border-top: 1px solid #ccc;
        margin: 1.5em 0;
    }
    '''

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })

    def log(self, msg):
        print(msg, flush=True)

    def fetch_url(self, url, desc=''):
        last_err = None
        for i in range(RETRY_TIMES):
            try:
                self.log('请求%s: 第 %d/%d 次 -> %s' % (desc or 'URL', i + 1, RETRY_TIMES, url))
                r = self.session.get(url, timeout=30)
                r.raise_for_status()
                return r.text
            except Exception as e:
                last_err = e
                self.log('请求失败%s: 第 %d/%d 次 -> %s | %s' % (desc or 'URL', i + 1, RETRY_TIMES, url, e))
                if i < RETRY_TIMES - 1:
                    time.sleep(RETRY_SLEEP)
        raise last_err

    def get_target_date(self):
        if TARGET_DATE:
            try:
                return datetime.strptime(TARGET_DATE, '%Y-%m-%d').date()
            except Exception:
                self.log('TARGET_DATE 格式错误，应为 YYYY-MM-DD，改为今天')
        return date.today()

    def parse_date_text(self, text):
        if not text:
            return None
        text = ' '.join(text.split()).strip()

        m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass

        m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if m:
            try:
                return datetime.strptime(m.group(1), '%Y-%m-%d').date()
            except Exception:
                pass

        for fmt in ('%b %d, %Y', '%B %d, %Y', '%d %b %Y', '%d %B %Y'):
            try:
                return datetime.strptime(text, fmt).date()
            except Exception:
                pass

        m = re.search(r'([A-Za-z]+ \d{1,2}, \d{4})', text)
        if m:
            s = m.group(1)
            for fmt in ('%b %d, %Y', '%B %d, %Y'):
                try:
                    return datetime.strptime(s, fmt).date()
                except Exception:
                    pass
        return None

    def is_article_url(self, url):
        if not url:
            return False

        p = urlparse(url)
        if 'overseaspost.news' not in p.netloc:
            return False

        path = p.path.strip('/')
        if not path:
            return False

        bad_prefixes = (
            'about', 'archive', 'tag', 'tags', 'author', 'authors',
            'search', 'subscribe', 'signin', 'login', 'account',
            'podcast', 'video', 'privacy', 'terms', 'feed'
        )
        for bp in bad_prefixes:
            if path == bp or path.startswith(bp + '/'):
                return False

        return True

    def get_index_urls(self):
        return [self.INDEX_URL]

    def extract_candidate_links_from_index(self, soup):
        results = []
        seen = set()

        selectors = [
            'article a[href]',
            'main a[href]',
            'h1 a[href]',
            'h2 a[href]',
            'h3 a[href]',
            'a[href]',
        ]

        for sel in selectors:
            for a in soup.select(sel):
                href = a.get('href', '').strip()
                if not href:
                    continue

                url = urljoin(self.BASE_URL, href)
                if not self.is_article_url(url):
                    continue

                text = a.get_text(' ', strip=True)
                title = text if text else url

                if text and len(text) < 6:
                    continue

                if url in seen:
                    continue

                seen.add(url)
                results.append((title, url))

        return results

    def get_candidate_links(self):
        all_links = []
        seen = set()

        for idx_url in self.get_index_urls():
            try:
                raw = self.fetch_url(idx_url, '首页')
                soup = BeautifulSoup(raw, 'html.parser')
                links = self.extract_candidate_links_from_index(soup)
                self.log('列表页候选链接数: %s -> %d' % (idx_url, len(links)))

                for title, url in links:
                    if url in seen:
                        continue
                    seen.add(url)
                    all_links.append((title, url))
            except Exception as e:
                self.log('读取列表页失败: %s | %s' % (idx_url, e))

        forced = all_links[:TOP_N]
        self.log('强制检查前 %d 篇候选文章' % len(forced))

        for i, (title, url) in enumerate(forced, 1):
            self.log('候选[%02d]: %s | %s' % (i, title, url))

        return forced

    def article_soup(self, url):
        raw = self.fetch_url(url, '文章')
        return BeautifulSoup(raw, 'html.parser')

    def extract_title(self, soup):
        selectors = [
            'h1.post-title',
            'h1.entry-title',
            'h1.article-title',
            '.gh-article-title',
            'article h1',
            'main h1',
            'h1'
        ]
        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                t = node.get_text(' ', strip=True)
                if t:
                    return t
        if soup.title:
            return soup.title.get_text(' ', strip=True)
        return 'Untitled'

    def extract_pubtime(self, soup):
        selectors = [
            'meta[property="article:published_time"]',
            'meta[name="article:published_time"]',
            'meta[name="pubdate"]',
            'meta[name="publish-date"]',
            'time[datetime]',
            'time',
            '.post-date',
            '.entry-date',
            '.meta time',
            '.byline time',
            '.gh-article-meta time',
            '.meta',
            '.byline'
        ]

        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                if node.name == 'meta':
                    val = node.get('content', '').strip()
                    if val:
                        return val
                if node.has_attr('datetime'):
                    dt = node.get('datetime', '').strip()
                    if dt:
                        return dt
                txt = node.get_text(' ', strip=True)
                if txt:
                    return txt

        txt = soup.get_text(' ', strip=True)

        m = re.search(r'([A-Za-z]+ \d{1,2}, \d{4})', txt)
        if m:
            return m.group(1)

        m = re.search(r'(\d{4}-\d{2}-\d{2})', txt)
        if m:
            return m.group(1)

        return ''

    def extract_excerpt(self, soup):
        selectors = [
            '.gh-article-excerpt.is-body',
            '.gh-article-excerpt',
            '.article-excerpt',
            '.post-excerpt',
            'meta[name="description"]',
            'meta[property="og:description"]',
            'meta[name="twitter:description"]'
        ]

        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                if node.name == 'meta':
                    val = node.get('content', '').strip()
                    if val:
                        return val
                txt = node.get_text(' ', strip=True)
                if txt:
                    return txt
        return ''

    def extract_reading_time(self, soup):
        selectors = [
            '.gh-article-meta',
            '.gh-article-meta-wrapper',
            '.article-meta',
            '.post-meta',
            '.gh-post-meta',
            'article'
        ]

        for sel in selectors:
            for node in soup.select(sel):
                txt = node.get_text(' ', strip=True)
                if not txt:
                    continue

                m = re.search(r'(\d+\s*(?:min|mins|minute|minutes)\s+read)', txt, re.I)
                if m:
                    return m.group(1)

                m = re.search(r'(\d+\s*分钟阅读)', txt)
                if m:
                    return m.group(1)

        all_text = soup.get_text(' ', strip=True)

        m = re.search(r'(\d+\s*(?:min|mins|minute|minutes)\s+read)', all_text, re.I)
        if m:
            return m.group(1)

        m = re.search(r'(\d+\s*分钟阅读)', all_text)
        if m:
            return m.group(1)

        return ''

    def extract_tags(self, soup):
        tags = []
        seen = set()

        selectors = [
            'a[href*="/tag/"]',
            '.gh-article-tag',
            '.article-tag',
            '.post-tag',
            '.tag'
        ]

        for sel in selectors:
            for node in soup.select(sel):
                txt = node.get_text(' ', strip=True)
                if not txt:
                    continue
                if len(txt) > 30:
                    continue
                if txt.lower() in ('tag', 'tags'):
                    continue
                if txt in seen:
                    continue
                seen.add(txt)
                tags.append(txt)

        return tags

    def extract_author(self, soup):
        selectors = [
            '.gh-article-author-name',
            '.gh-author-name',
            '.author-name',
            '[rel="author"]',
            'meta[name="author"]',
            'meta[property="article:author"]'
        ]

        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                if node.name == 'meta':
                    val = node.get('content', '').strip()
                    if val:
                        return val
                txt = node.get_text(' ', strip=True)
                if txt:
                    return txt

        for a in soup.select('a[href*="/author/"]'):
            txt = a.get_text(' ', strip=True)
            if txt and len(txt) <= 50:
                return txt

        for script in soup.select('script[type="application/ld+json"]'):
            txt = script.get_text(strip=True)
            if not txt:
                continue
            m = re.search(r'"author"\s*:\s*\{.*?"name"\s*:\s*"([^"]+)"', txt, re.S)
            if m:
                return m.group(1).strip()

        return ''

    def normalize_pub_date_display(self, pubtime):
        if not pubtime:
            return ''
        pubtime = pubtime.strip()

        m = re.search(r'(\d{4}-\d{2}-\d{2})', pubtime)
        if m:
            return m.group(1)

        d = self.parse_date_text(pubtime)
        if d:
            return d.strftime('%Y-%m-%d')

        return pubtime

    def extract_article_meta(self, soup):
        pubtime = self.extract_pubtime(soup)
        return {
            'title': self.extract_title(soup),
            'author': self.extract_author(soup),
            'pubtime': pubtime,
            'pubdate_display': self.normalize_pub_date_display(pubtime),
            'excerpt': self.extract_excerpt(soup),
            'reading_time': self.extract_reading_time(soup),
            'tags': self.extract_tags(soup),
        }

    def locate_article_body(self, soup):
        selectors = [
            '.gh-content',
            '.gh-article-content',
            'article',
            '.post-content',
            '.entry-content',
            '.article-content',
            '.post-body',
            '.entry-body',
            'main'
        ]
        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                text = node.get_text(' ', strip=True)
                if len(text) > 300:
                    return node
        return soup.body if soup.body else soup

    def article_matches_date(self, url, target):
        try:
            soup = self.article_soup(url)
            pub = self.extract_pubtime(soup)
            pub_date = self.parse_date_text(pub)
            title = self.extract_title(soup)

            self.log('检查文章: %s | 时间=%s | 标题=%s' % (url, pub, title))

            if pub_date == target:
                return title, soup, True
            return title, soup, False
        except Exception as e:
            self.log('分析文章失败: %s | %s' % (url, e))
            return None, None, False

    def preprocess_html(self, soup):
        for tag in soup.select('script, style, noscript, iframe, video, audio, source, canvas, svg, form, button'):
            tag.decompose()

        for tag in soup.select('img, picture, figure, figcaption'):
            tag.decompose()

        remove_selectors = [
            '[class*="related"]', '[id*="related"]',
            '[class*="recommend"]', '[id*="recommend"]',
            '[class*="read-more"]', '[id*="read-more"]',
            '[class*="newsletter"]', '[id*="newsletter"]',
            '[class*="subscribe"]', '[id*="subscribe"]',
            '[class*="share"]', '[id*="share"]',
            '[class*="social"]', '[id*="social"]',
            '[class*="comment"]', '[id*="comment"]',
            '[class*="promo"]', '[id*="promo"]',
            'aside', 'nav', 'footer'
        ]
        for sel in remove_selectors:
            for tag in soup.select(sel):
                tag.decompose()

        keywords = [
            '推荐阅读', '延伸阅读', '相关阅读', '相关文章',
            'Read more', 'Related', 'Recommended',
            'You may also like', 'Continue reading', 'Further reading'
        ]
        for tag in soup.find_all(['div', 'section', 'aside', 'p', 'ul']):
            text = tag.get_text(' ', strip=True)
            if not text:
                continue
            low = text.lower()
            for kw in keywords:
                if kw.lower() in low and len(text) < 400:
                    tag.decompose()
                    break

        for a in soup.find_all('a'):
            a.unwrap()

        return soup

    def remove_duplicate_leading_meta(self, wrapper, title, excerpt, author, pubdate_display, reading_time, tags):
        texts_to_remove = set()
        if title:
            texts_to_remove.add(title.strip())
        if excerpt:
            texts_to_remove.add(excerpt.strip())
        if author:
            texts_to_remove.add(author.strip())
            texts_to_remove.add(('作者：' + author).strip())
        if pubdate_display:
            texts_to_remove.add(pubdate_display.strip())
        if reading_time:
            texts_to_remove.add(reading_time.strip())
        for t in tags or []:
            if t:
                texts_to_remove.add(t.strip())

        removed = 0
        for tag in list(wrapper.find_all(['h1', 'h2', 'p', 'div', 'header'], limit=20)):
            txt = tag.get_text(' ', strip=True)
            if not txt:
                continue

            if txt in texts_to_remove:
                tag.decompose()
                removed += 1
                continue

            if title and txt == title:
                tag.decompose()
                removed += 1
                continue

            if excerpt and txt == excerpt:
                tag.decompose()
                removed += 1
                continue

            if removed >= 8:
                break

    def build_clean_article_html(self, soup):
        meta_info = self.extract_article_meta(soup)

        title = meta_info['title']
        author = meta_info['author']
        pubdate_display = meta_info['pubdate_display']
        excerpt = meta_info['excerpt']
        reading_time = meta_info['reading_time']
        tags = meta_info['tags']

        soup = self.preprocess_html(soup)
        body = self.locate_article_body(soup)

        new_html = BeautifulSoup(
            '<html><head><meta charset="utf-8"/></head><body></body></html>',
            'html.parser'
        )
        b = new_html.body

        h1 = new_html.new_tag('h1')
        h1['class'] = 'article-title'
        h1.string = title
        b.append(h1)

        if author:
            author_div = new_html.new_tag('div')
            author_div['class'] = 'article-author'
            author_div.string = '作者：' + author
            b.append(author_div)

        meta_parts = []
        if pubdate_display:
            meta_parts.append(pubdate_display)
        if reading_time:
            meta_parts.append(reading_time)
        if tags:
            meta_parts.append(' / '.join(tags))

        if meta_parts:
            meta = new_html.new_tag('div')
            meta['class'] = 'article-meta'
            meta.string = ' · '.join(meta_parts)
            b.append(meta)

        if excerpt:
            ex = new_html.new_tag('div')
            ex['class'] = 'article-excerpt'
            ex.string = '摘要：' + excerpt
            b.append(ex)

        wrapper = new_html.new_tag('div')
        wrapper['class'] = 'article-body'

        if body:
            for child in list(body.children):
                try:
                    wrapper.append(child)
                except Exception:
                    pass

        self.remove_duplicate_leading_meta(
            wrapper, title, excerpt, author, pubdate_display, reading_time, tags
        )

        b.append(wrapper)

        for tag in new_html.select('img, picture, figure, figcaption, video, audio, iframe, script, style, noscript'):
            tag.decompose()

        for a in new_html.find_all('a'):
            a.unwrap()

        for tag in new_html.find_all(['p', 'div', 'section']):
            if not tag.get_text(' ', strip=True) and not tag.find(['h1', 'h2', 'h3', 'blockquote', 'ul', 'ol']):
                tag.decompose()

        return str(new_html), meta_info

    def collect_articles(self):
        target = self.get_target_date()
        candidates = self.get_candidate_links()
        articles = []
        seen = set()

        for guessed_title, url in candidates:
            if url in seen:
                continue
            seen.add(url)

            title, soup, ok = self.article_matches_date(url, target)
            if not ok or soup is None:
                continue

            html, meta = self.build_clean_article_html(soup)
            articles.append({
                'title': meta.get('title') or title or guessed_title,
                'url': url,
                'html': html
            })

        if not articles:
            self.log('没有找到目标日期 %s 的文章' % target.strftime('%Y-%m-%d'))
            return target, []

        articles.sort(key=lambda x: x['title'])
        self.log('最终匹配到 %d 篇文章' % len(articles))
        return target, articles

    def build_epub(self, out_path):
        target, articles = self.collect_articles()
        if not articles:
            raise RuntimeError('没有匹配文章，未生成 EPUB')

        book = epub.EpubBook()
        title = '海上邮报 ' + target.strftime('%Y-%m-%d')

        book.set_identifier('overseaspost-' + target.strftime('%Y-%m-%d'))
        book.set_title(title)
        book.set_language('zh-CN')
        book.add_author('ChatGPT')

        style_item = epub.EpubItem(
            uid='style_nav',
            file_name='style/nav.css',
            media_type='text/css',
            content=self.EXTRA_CSS
        )
        book.add_item(style_item)

        intro = epub.EpubHtml(title='目录', file_name='index.xhtml', lang='zh-CN')
        intro.content = '<h1>%s</h1><div class="article-meta">%s</div>' % (
            title, target.strftime('%Y-%m-%d')
        )
        book.add_item(intro)

        toc = [epub.Link('index.xhtml', '目录', 'index')]
        spine = ['nav', intro]

        for i, art in enumerate(articles, 1):
            c = epub.EpubHtml(
                title=art['title'],
                file_name='article_%03d.xhtml' % i,
                lang='zh-CN'
            )
            c.content = art['html']
            book.add_item(c)
            spine.append(c)
            toc.append(epub.Link(c.file_name, art['title'], 'article_%03d' % i))

        book.toc = tuple(toc)
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        epub.write_epub(out_path, book, {})
        self.log('已生成 EPUB: %s' % out_path)


def main():
    crawler = OverseasPostDailyForceN()
    target = crawler.get_target_date()
    out_path = os.path.join('output', 'overseaspost-%s.epub' % target.strftime('%Y-%m-%d'))
    crawler.build_epub(out_path)


if __name__ == '__main__':
    main()
