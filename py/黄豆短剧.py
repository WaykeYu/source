# -*- coding: utf-8 -*-
"""
黄豆短剧爬虫（新站加密接口版）
站点: https://xqjzvcvt.top
参考: https://github.com/xiadasy/qx-scripts/tree/main/huangdou
"""

import gzip
import hashlib
import hmac
import json
import os
import time
import uuid
import urllib.parse

import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        pass


class _AESCBC:
    """AES-CBC/PKCS7 兼容层：优先 pycryptodome，兜底 cryptography。"""

    @staticmethod
    def encrypt(data, key, iv):
        try:
            from Crypto.Cipher import AES
            return AES.new(key, AES.MODE_CBC, iv).encrypt(_AESCBC.pad(data))
        except Exception:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            enc = cipher.encryptor()
            return enc.update(_AESCBC.pad(data)) + enc.finalize()

    @staticmethod
    def decrypt(data, key, iv):
        try:
            from Crypto.Cipher import AES
            plain = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
        except Exception:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            dec = cipher.decryptor()
            plain = dec.update(data) + dec.finalize()
        return _AESCBC.unpad(plain)

    @staticmethod
    def pad(data):
        n = 16 - (len(data) % 16)
        return data + bytes([n]) * n

    @staticmethod
    def unpad(data):
        if not data:
            return data
        n = data[-1]
        if 1 <= n <= 16:
            return data[:-n]
        return data


class Spider(BaseSpider):
    BASE_URL = "https://xqjzvcvt.top"
    API_BASE = BASE_URL + "/api"

    # 新站 Flutter Web 端 platformKey，来自参考脚本 api.js
    PLATFORM_KEY = "7961beb44246e3012ce228d6b5ced05a"
    VERSION = "2.0.0"
    DEVICE_TYPE = "web"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Origin": BASE_URL,
        "Referer": BASE_URL + "/home",
        "Content-Type": "application/octet-stream",
    }

    def __init__(self):
        super().__init__()
        self.name = "黄豆短剧"
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.session_id = uuid.uuid4().hex
        self.device_id = self.session_id
        self.token = ""
        self.error_play_url = "https://vjs.zencdn.net/v/oceans.mp4"
        self._class_cache = None
        self._nav_filter_cache = {}  # code -> navFilter 子标签列表

    def init(self, extend="{}"):
        if extend:
            try:
                cfg = json.loads(extend)
                self.name = cfg.get("name", self.name)
                base_url = cfg.get("base_url") or cfg.get("site")
                if base_url:
                    self.BASE_URL = base_url.rstrip("/")
                    self.API_BASE = self.BASE_URL + "/api"
                    self.HEADERS["Origin"] = self.BASE_URL
                    self.HEADERS["Referer"] = self.BASE_URL + "/home"
                    self.session.headers.update(self.HEADERS)
                self.token = cfg.get("token", self.token)
            except Exception as e:
                print(e)
        return None

    def getName(self):
        return self.name

    def homeContent(self, filter):
        result = {
            "class": [],
            "filters": {},
            "list": [],
            "parse": 0,
            "jx": 0,
        }
        try:
            result["class"] = self._classes()
            result["filters"] = self._filters(result["class"])
            data = self._api("/drama/list", {"page": "1", "page_size": "18"})
            for item in self._list_from_data(data):
                result["list"].append(self._parse_vod(item))
        except Exception as e:
            print(e)
        return result

    def categoryContent(self, tid, pg, filter, extend):
        result = {
            "page": int(pg),
            "pagecount": 999,
            "limit": 18,
            "total": 99999,
            "list": [],
            "parse": 0,
            "jx": 0,
        }
        try:
            extend = extend or {}
            if tid and tid not in ("all", "recommend"):
                # yuandou 走 navBlock；其他分类走 navFilter + list
                if tid == "yuandou":
                    data = self._api("/drama/navBlock", {
                        "code": "yuandou",
                        "tab": "recommend",
                        "page": str(pg),
                    })
                    items = self._items_from_nav_block(data)
                else:
                    sub_tabs = self._get_nav_filter(tid)
                    sub_idx = self._to_int(extend.get("sub"), 0)
                    if sub_idx < 0 or sub_idx >= len(sub_tabs):
                        sub_idx = 0
                    sub = sub_tabs[sub_idx] if sub_tabs else {}
                    flt = sub.get("filter", {})
                    req = {
                        "page": str(pg),
                        "page_size": "18",
                        "cat_id": flt.get("cat_id", ""),
                        "order": flt.get("order", "") or extend.get("order", ""),
                    }
                    tag_id = flt.get("tag_id", "")
                    if tag_id:
                        req["tag_id"] = tag_id
                    data = self._api("/drama/list", req)
                    items = self._list_from_data(data)
            else:
                req = {"page": str(pg), "page_size": "18"}
                order = extend.get("order")
                if order:
                    req["order"] = order
                update_status = extend.get("update_status")
                if update_status:
                    req["update_status"] = update_status
                data = self._api("/drama/list", req)
                items = self._list_from_data(data)
            result["list"] = [self._parse_vod(x) for x in items]
            if len(items) < 18:
                result["pagecount"] = int(pg)
            else:
                result["pagecount"] = int(pg) + 1
        except Exception as e:
            print(e)
        return result

    def detailContent(self, ids):
        result = {"list": [], "parse": 0, "jx": 0}
        try:
            vid = str(ids[0]).replace("rp_", "")
            obj = self._api("/drama/detail", {"id": vid})
            data = obj.get("data", obj) if isinstance(obj, dict) else {}
            if not isinstance(data, dict):
                return result

            data = self._unlock_detail(data)
            vod_id = self._safe_id(data.get("id") or data.get("drama_id") or vid)
            title = data.get("name") or data.get("title") or data.get("t") or vod_id
            cover = self._cover(data)
            episode_count = self._to_int(data.get("episode_count") or data.get("free_episodes"), 0)
            episodes = data.get("episodes") if isinstance(data.get("episodes"), list) else []
            if not episode_count:
                episode_count = len(episodes) or 1

            play_parts = []
            if episodes:
                for idx, ep in enumerate(episodes, 1):
                    seq = ep.get("seq") or ep.get("episode") or ep.get("ep") or idx
                    ep_name = ep.get("name") or ep.get("title") or "第%s集" % seq
                    play_parts.append("%s$%s|%s" % (ep_name, vod_id, seq))
            else:
                for seq in range(1, episode_count + 1):
                    play_parts.append("第%s集$%s|%s" % (seq, vod_id, seq))

            vod = {
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": cover,
                "type_name": data.get("category") or data.get("type") or "",
                "vod_year": "",
                "vod_area": "",
                "vod_remarks": data.get("update_label") or ("全%s集" % episode_count),
                "vod_actor": "",
                "vod_director": "",
                "vod_content": data.get("description") or data.get("summary") or title,
                "vod_play_from": "黄豆短剧",
                "vod_play_url": "#".join(play_parts),
            }
            result["list"].append(vod)
        except Exception as e:
            print(e)
        return result

    def searchContent(self, key, quick, pg="1"):
        result = {
            "page": int(pg),
            "pagecount": 999,
            "limit": 18,
            "total": 99999,
            "list": [],
            "parse": 0,
            "jx": 0,
        }
        try:
            # /drama/searchResult 在部分环境会返回非加密兜底内容；/drama/list 的 keywords 更稳定。
            data = self._api("/drama/list", {
                "page": str(pg),
                "page_size": "18",
                "keywords": str(key),
            })
            items = self._list_from_data(data)
            result["list"] = [self._parse_vod(x) for x in items]
            if len(items) < 18:
                result["pagecount"] = int(pg)
            else:
                result["pagecount"] = int(pg) + 1
        except Exception as e:
            print(e)
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {
            "parse": 0,
            "playUrl": "",
            "url": self.error_play_url,
            "jx": 0,
            "header": {
                "User-Agent": self.HEADERS["User-Agent"],
                "Referer": self.BASE_URL + "/home",
                "Origin": self.BASE_URL,
            },
        }
        try:
            if not id:
                return result
            if str(id).startswith("http"):
                result["url"] = id
                return result

            vid, seq = self._split_play_id(id)
            api_obj = self._api("/drama/play", {"id": vid, "seq": str(seq)}, silent=True)
            data = api_obj.get("data", {}) if isinstance(api_obj, dict) else {}
            play_url = data.get("m3u8") or data.get("url")
            if not play_url:
                play_url = self._hls_url(vid, seq)
            result["url"] = play_url
        except Exception as e:
            print(e)
            try:
                vid, seq = self._split_play_id(id)
                result["url"] = self._hls_url(vid, seq)
            except Exception:
                pass
        return result

    # ==================== 加密 API ====================

    def _api(self, path, data=None, silent=False):
        path = "/" + path.lstrip("/")
        request_id = str(uuid.uuid4())
        key = self._derive_key(request_id, self.PLATFORM_KEY)
        iv = os.urandom(16)

        payload = {
            "token": self.token or "",
            "deviceId": self.device_id,
            "data": data or {},
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body = iv + _AESCBC.encrypt(gzip.compress(raw), key, iv)

        ts = int(time.time())
        sign_text = "Dart|%s|%s|%s|%s" % (self.session_id, request_id, ts, path)
        headers = dict(self.HEADERS)
        headers.update({
            "version": self.VERSION,
            "deviceType": self.DEVICE_TYPE,
            "time": str(ts),
            "sign": hashlib.sha256(sign_text.encode("utf-8")).hexdigest() + "-" + str(ts),
            "requestId": request_id,
            "sessionId": self.session_id,
            "deviceBrand": "",
            "deviceModel": "",
            "systemName": "",
            "systemVersion": "",
        })

        try:
            r = self.session.post(self.API_BASE + path, data=body, headers=headers, timeout=20, verify=False)
            r.raise_for_status()
            return self._decrypt_response(r.content, request_id)
        except Exception as e:
            if not silent:
                print("_api error %s: %s" % (path, e))
            return {}

    def _derive_key(self, request_id, platform_key):
        rid = str(request_id).replace("-", "")
        return hmac.new(platform_key.encode("utf-8"), bytes.fromhex(rid), hashlib.sha256).digest()

    def _decrypt_response(self, blob, request_id):
        if not blob or len(blob) < 32 or (len(blob) - 16) % 16 != 0:
            try:
                return json.loads(blob.decode("utf-8"))
            except Exception:
                return {}
        key = self._derive_key(request_id, self.PLATFORM_KEY)
        iv, ct = blob[:16], blob[16:]
        plain = _AESCBC.decrypt(ct, key, iv)
        if plain[:2] == b"\x1f\x8b":
            plain = gzip.decompress(plain)
        return json.loads(plain.decode("utf-8"))

    # ==================== 数据处理 ====================

    def _classes(self):
        if self._class_cache:
            return self._class_cache
        classes = [{"type_id": "all", "type_name": "全部短剧"}]
        try:
            obj = self._api("/drama/navList", {})
            data = obj.get("data", obj) if isinstance(obj, dict) else {}
            for item in self._list_from_data(data):
                tid = str(item.get("code") or item.get("id") or item.get("cat_id") or "")
                name = item.get("name") or item.get("title") or item.get("code") or ""
                if tid and name:
                    classes.append({"type_id": tid, "type_name": name})
        except Exception as e:
            print(e)
        self._class_cache = classes
        return classes

    def _get_nav_filter(self, code):
        """获取指定 code 的 navFilter 子标签列表，带缓存。"""
        if code not in self._nav_filter_cache:
            try:
                obj = self._api("/drama/navFilter", {"code": str(code)})
                data = obj.get("data", obj) if isinstance(obj, dict) else {}
                self._nav_filter_cache[code] = self._list_from_data(data)
            except Exception as e:
                print(e)
                self._nav_filter_cache[code] = []
        return self._nav_filter_cache.get(code, [])

    def _filters(self, classes):
        filters = {}
        common = [
            {"key": "order", "name": "排序", "value": [
                {"n": "默认", "v": ""},
                {"n": "最新", "v": "new"},
                {"n": "最热", "v": "hot"},
            ]},
            {"key": "update_status", "name": "状态", "value": [
                {"n": "全部", "v": ""},
                {"n": "连载", "v": "0"},
                {"n": "完结", "v": "1"},
            ]},
        ]
        for c in classes:
            tid = c["type_id"]
            if tid not in ("all", "yuandou"):
                sub_tabs = self._get_nav_filter(tid)
                if sub_tabs:
                    sub_vals = [{"n": t.get("name", "默认"), "v": str(i)} for i, t in enumerate(sub_tabs)]
                    filters[tid] = [
                        {"key": "sub", "name": "子分类", "value": sub_vals},
                    ] + common
                else:
                    filters[tid] = common
            else:
                filters[tid] = common
        return filters

    def _list_from_data(self, data):
        if not isinstance(data, dict):
            return data if isinstance(data, list) else []
        if isinstance(data.get("list"), list):
            return data["list"]
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("data"), dict):
            return self._list_from_data(data["data"])
        if isinstance(data.get("data"), list):
            return data["data"]
        return []

    def _items_from_nav_block(self, data):
        blocks = self._list_from_data(data.get("data", data) if isinstance(data, dict) else data)
        items = []
        for block in blocks:
            if isinstance(block, dict):
                arr = block.get("items")
                if isinstance(arr, list):
                    items.extend(arr)
                elif block.get("id") or block.get("drama_id"):
                    items.append(block)
        return items

    def _parse_vod(self, item):
        item = item or {}
        vid = self._safe_id(item.get("id") or item.get("drama_id") or "")
        name = item.get("name") or item.get("title") or item.get("t") or vid
        cover = self._cover(item)
        remarks = item.get("update_label") or item.get("corner") or ""
        if not remarks:
            ep_count = item.get("episode_count") or item.get("episodes")
            if ep_count:
                remarks = "全%s集" % ep_count
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": cover,
            "vod_remarks": remarks,
        }

    def _cover(self, item):
        return (
            item.get("img_y") or item.get("img_x") or item.get("img") or
            item.get("cover") or item.get("pic") or ""
        )

    def _unlock_detail(self, d):
        if not isinstance(d, dict):
            return d
        eps = d.get("episodes")
        if isinstance(eps, list):
            for ep in eps:
                if isinstance(ep, dict):
                    ep["is_buy"] = True
                    ep["type"] = "free"
                    ep["price"] = 0
                    ep["methods"] = []
        d["pay_type"] = "free"
        d["money"] = 0
        d["episode_price"] = 0
        d["points_price"] = 0
        d["can_vip_watch"] = True
        d["is_buy_whole"] = True
        d["vip_episodes"] = []
        d["coin_episodes"] = []
        d["points_episodes"] = []
        return d

    def _safe_id(self, vid):
        return str(vid or "").replace("rp_", "")

    def _split_play_id(self, play_id):
        parts = str(play_id).split("|", 1)
        vid = self._safe_id(parts[0])
        seq = parts[1] if len(parts) > 1 and parts[1] else "1"
        return vid, seq

    def _hls_url(self, vid, seq):
        return "%s/api/drama/hls/%s/%s/play.m3u8?line=free" % (self.BASE_URL, self._safe_id(vid), seq)

    def _to_int(self, value, default=0):
        try:
            return int(value)
        except Exception:
            return default


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    s = Spider()
    s.init()

    print("=== 首页 ===")
    home = s.homeContent(True)
    print("分类:", home["class"])
    print("推荐:", len(home["list"]))
    for v in home["list"][:3]:
        print(v)

    print("\n=== 分类 ===")
    tid = home["class"][1]["type_id"] if len(home["class"]) > 1 else "all"
    cate = s.categoryContent(tid, 1, True, {})
    print("分类列表:", len(cate["list"]))
    for v in cate["list"][:3]:
        print(v)

    if home["list"]:
        vid = home["list"][0]["vod_id"]
        print("\n=== 详情 ===", vid)
        detail = s.detailContent([vid])
        print(json.dumps(detail, ensure_ascii=False)[:1000])
        if detail["list"] and detail["list"][0]["vod_play_url"]:
            first = detail["list"][0]["vod_play_url"].split("#")[0].split("$", 1)[1]
            print("\n=== 播放 ===", first)
            print(s.playerContent("黄豆短剧", first, []))
