import re
import json
import base64
import requests
import urllib.parse
from bs4 import BeautifulSoup
from base.spider import Spider

class Spider(Spider):
    HOST = "https://wbbb1.com"
    PLAY_URL = "https://wbbb1.com/vplay/"
    PARSE_HOST = "https://xn--qvr2v.850088.xyz"
    CATEGORY_MAP = {
        "电影": "dianying",
        "剧集": "juji",
        "动漫": "dongman",
        "综艺": "zongyi"
    }

    def getName(self):
        return "歪比巴卜"

    def init(self, extend=""):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": self.HOST + "/"
        }
        self.session.headers.update(self.headers)

    def _get(self, url, referer=None):
        try:
            h = dict(self.headers)
            if referer:
                h["Referer"] = referer
            r = self.session.get(url, headers=h, timeout=15, verify=False)
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except requests.RequestException:
            return ""

    def _fix_url(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.HOST + url
        return url

    def _play_url(self, url):
        if not url:
            return ""
        if url.startswith("http") and "/vplay/" in url:
            m = re.search(r"/vplay/([^/?#]+\.html)", url)
            return self.PLAY_URL + m.group(1) if m else url
        if url.startswith("http"):
            return url
        m = re.search(r"/vplay/([^/?#]+\.html)", url)
        if m:
            return self.PLAY_URL + m.group(1)
        return self.PLAY_URL + url.strip("/")

    def _text(self, item):
        return item.get_text(" ", strip=True) if item else ""

    def _pic(self, item):
        if not item:
            return ""
        return self._fix_url(item.get("data-original") or item.get("data-src") or item.get("data-lazyload") or item.get("src") or "")

    def _parse_list(self, html):
        soup = BeautifulSoup(html or "", "html.parser")
        items = soup.select("a.module-poster-item[href*='/detail/']") or soup.select("a[href*='/detail/']:has(img)")
        data, seen = [], set()
        for a in items:
            href = a.get("href", "")
            m = re.search(r"/detail/(\d+)\.html", href)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            img = a.select_one("img")
            name = a.get("title") or (img.get("alt") if img else "") or self._text(a.select_one(".module-poster-item-title")) or self._text(a)
            pic = self._pic(img)
            note = self._text(a.select_one(".module-item-note")) or self._text(a.select_one(".module-poster-item-note"))
            data.append({
                "vod_id": m.group(1),
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": note
            })
        return data

    def homeContent(self, filter):
        html = self._get(self.HOST + "/")
        classes = [{"type_id": v, "type_name": k} for k, v in self.CATEGORY_MAP.items()]
        return {"class": classes, "list": self._parse_list(html), "filters": {}}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        html = self._get(f"{self.HOST}/show/{tid}--------{page}---.html")
        data = self._parse_list(html)
        return {
            "page": page,
            "pagecount": 999 if data else page,
            "limit": len(data),
            "total": 999999 if data else 0,
            "list": data
        }

    def detailContent(self, ids):
        result = []
        for vid in ids:
            html = self._get(f"{self.HOST}/detail/{vid}.html")
            soup = BeautifulSoup(html or "", "html.parser")
            name = self._text(soup.select_one("h1")) or self._text(soup.select_one(".module-info-heading h1")) or vid
            img = soup.select_one(".module-info-poster img") or soup.select_one(".module-item-pic img") or soup.select_one("img.lazy")
            pic = self._pic(img)
            desc = self._text(soup.select_one(".module-info-introduction-content")) or self._text(soup.select_one(".module-info-content"))
            sources, urls = self._parse_play_sources(soup)
            if not sources:
                sources, urls = self._parse_play_sources_fallback(html)
            result.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_content": desc,
                "vod_play_from": "$$$".join(sources),
                "vod_play_url": "$$$".join(urls)
            })
        return {"list": result}

    def _parse_play_sources(self, soup):
        sources, urls = [], []
        tabs = [self._text(i) for i in soup.select(".module-tab-item[data-dropdown-value], .module-tab-item")]
        panels = soup.select(".module-play-list")
        for i, panel in enumerate(panels):
            eps = []
            for a in panel.select("a.module-play-list-link[href*='/vplay/'], a[href*='/vplay/']"):
                title = self._text(a) or a.get("title") or "播放"
                href = self._play_url(a.get("href", ""))
                if href:
                    eps.append(f"{title}${href}")
            if eps:
                sources.append(tabs[i] if i < len(tabs) and tabs[i] else f"线路{i + 1}")
                urls.append("#".join(eps))
        return sources, urls

    def _parse_play_sources_fallback(self, html):
        groups, order = {}, []
        for href, name in re.findall(r'<a[^>]+href=["\']([^"\']*/vplay/[^"\']+\.html)["\'][^>]*>(.*?)</a>', html or "", re.S):
            clean = re.sub(r"<.*?>", "", name).strip() or "播放"
            m = re.search(r"/vplay/\d+-(\d+)-\d+\.html", href)
            key = m.group(1) if m else "1"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(f"{clean}${self._play_url(href)}")
        sources = [f"线路{k}" for k in order]
        urls = ["#".join(groups[k]) for k in order]
        return sources, urls

    def searchContent(self, key, quick, pg="1"):
        wd = urllib.parse.quote(key)
        html = self._get(f"{self.HOST}/search/{wd}-------------.html")
        return {"list": self._parse_list(html), "page": int(pg or 1)}

    def _decode_url(self, url, encrypt):
        if not url:
            return ""
        if str(encrypt) == "1":
            try:
                return urllib.parse.unquote(url)
            except Exception:
                return url
        if str(encrypt) == "2":
            try:
                return urllib.parse.unquote(base64.b64decode(url).decode("utf-8"))
            except Exception:
                return url
        return url

    def _player_data(self, html):
        m = re.search(r"player_aaaa\s*=\s*(\{.*?\})\s*</script>", html or "", re.S) or re.search(r"player_data\s*=\s*(\{.*?\})", html or "", re.S)
        if not m:
            return {}
        try:
            return json.loads(m.group(1))
        except Exception:
            return {}

    def _dmapi(self, play, next_url=""):
        api_url = self.PARSE_HOST + "/dmapi.php?url=" + urllib.parse.quote(play + (("&next=//wbbb1.com" + next_url) if next_url else ""), safe="")
        html = self._get(api_url, self.PARSE_HOST + "/player/")
        m = re.search(r'(https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*)', html or "", re.S)
        return m.group(1).replace("\\/", "/") if m else ""

    def _iframe_url(self, play, next_url="", title=""):
        url = self.PARSE_HOST + "/player/?url=" + urllib.parse.quote(play, safe="")
        if next_url:
            url += "&next=" + urllib.parse.quote("//wbbb1.com" + next_url, safe="")
        if title:
            url += "&title=" + urllib.parse.quote(title)
        return url

    def _extract_m3u8(self, html):
        m = re.search(r'(https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*)', html or "", re.S)
        return m.group(1).replace("\\/", "/") if m else ""

    def playerContent(self, flag, id, vipFlags):
        play_page = self._play_url(id)
        html = self._get(play_page)
        data = self._player_data(html)
        if data:
            play = self._decode_url(data.get("url", ""), data.get("encrypt", 0))
            next_url = data.get("link_next", "")
            title = data.get("vod_data", {}).get("vod_name", "") if isinstance(data.get("vod_data"), dict) else ""
            if play:
                if re.search(r"\.(m3u8|mp4)(\?|$)", play):
                    return {
                        "parse": 0,
                        "url": self._fix_url(play),
                        "header": {"User-Agent": self.headers["User-Agent"], "Referer": play_page}
                    }
                real = self._dmapi(play, next_url)
                if real:
                    return {
                        "parse": 0,
                        "url": real,
                        "header": {"User-Agent": self.headers["User-Agent"], "Referer": self.PARSE_HOST + "/player/"}
                    }
                return {
                    "parse": 1,
                    "url": self._iframe_url(play, next_url, title),
                    "header": {"User-Agent": self.headers["User-Agent"], "Referer": play_page}
                }
        real = self._extract_m3u8(html)
        if real:
            return {
                "parse": 0,
                "url": real,
                "header": {"User-Agent": self.headers["User-Agent"], "Referer": play_page}
            }
        return {"parse": 1, "url": play_page, "header": self.headers}