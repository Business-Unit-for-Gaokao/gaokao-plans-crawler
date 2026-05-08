import json
import random
import time
from datetime import datetime

import requests


class BaseCrawler:
    def __init__(self):
        self.base_url = "https://api.zjzw.cn/web/api/"
        self.default_headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "origin": "https://www.gaokao.cn",
            "referer": "https://www.gaokao.cn/",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        self.session = requests.Session()
        self.session.headers.update(self.default_headers)

        self.rate_limit_sleep = float(3)
        self.request_timeout = int(20)
        self.max_backoff = int(60)

    def build_headers(self, extra_headers=None):
        headers = dict(self.default_headers)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def request(
        self,
        method,
        url,
        *,
        params=None,
        json_data=None,
        data=None,
        headers=None,
        timeout=None,
        retry=3,
        delay=2,
        allow_statuses=(200,),
        log_prefix="请求",
    ):
        timeout = timeout or self.request_timeout
        merged_headers = self.build_headers(headers)

        for attempt in range(retry):
            try:
                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_data,
                    data=data,
                    headers=merged_headers,
                    timeout=timeout,
                )

                if response.status_code in allow_statuses:
                    return response

                print(f"⚠️  {log_prefix}失败，状态码: {response.status_code}")

            except requests.exceptions.Timeout:
                print(f"⚠️  {log_prefix}超时 (尝试 {attempt + 1}/{retry})")
            except requests.exceptions.RequestException as e:
                print(f"⚠️  {log_prefix}异常 (尝试 {attempt + 1}/{retry}): {e}")

            if attempt < retry - 1:
                time.sleep(delay * (attempt + 1))

        return None

    def get_json(
        self,
        url,
        *,
        params=None,
        headers=None,
        timeout=None,
        retry=3,
        delay=2,
        allow_statuses=(200,),
        log_prefix="GET",
    ):
        response = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            retry=retry,
            delay=delay,
            allow_statuses=allow_statuses,
            log_prefix=log_prefix,
        )
        if response is None:
            return None, None

        try:
            return response, response.json()
        except json.JSONDecodeError as e:
            print(f"⚠️  {log_prefix} JSON解析失败: {e}")
            print(f"   响应内容类型: {response.headers.get('content-type')}")
            print(f"   响应前200字符: {response.text[:200]}")
            return response, None

    def post_json(
        self,
        url=None,
        *,
        params=None,
        payload=None,
        headers=None,
        timeout=None,
        retry=3,
        delay=2,
        allow_statuses=(200,),
        log_prefix="POST",
    ):
        response = self.request(
            "POST",
            url or self.base_url,
            params=params,
            json_data=payload,
            headers=headers or {"content-type": "application/json"},
            timeout=timeout,
            retry=retry,
            delay=delay,
            allow_statuses=allow_statuses,
            log_prefix=log_prefix,
        )
        if response is None:
            return None, None

        try:
            result = response.json()
        except json.JSONDecodeError as e:
            print(f"⚠️  {log_prefix} JSON解析失败: {e}")
            print(f"   响应内容类型: {response.headers.get('content-type')}")
            print(f"   响应前200字符: {response.text[:200]}")
            return response, None

        code = result.get("code")

        if code == "1069" or code == 1069:
            message = result.get("message", "访问太过频繁")
            print(f"⚠️  限流警告: {message}")
            self.rate_limit_sleep = min(self.rate_limit_sleep * 2, self.max_backoff)
        elif code == "0000" or code == 0:
            self.rate_limit_sleep = max(self.rate_limit_sleep * 0.9, 3)

        return response, result

    def make_request(self, payload, retry=3, delay=2):
        _, result = self.post_json(
            payload=payload,
            retry=retry,
            delay=delay,
            log_prefix="统一接口请求",
        )
        return result

    def polite_sleep(self, min_delay=3.0, max_delay=6.0):
        base_delay = random.uniform(min_delay, max_delay)
        total_delay = base_delay * (self.rate_limit_sleep / 3.0)
        time.sleep(min(total_delay, 20))

    def save_to_json(self, data, filename):
        filepath = f"data/{filename}"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len(data),
                    "data": data,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"✓ 数据已保存到 {filepath}")
