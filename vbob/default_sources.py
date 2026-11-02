"""首次启动预置的刮削源。

默认源以可编辑的普通源写入数据库（builtin=0），用户可以直接修改 URL 和选择器，
删掉后也可以通过设置页的“恢复默认源”重新添加。这里只存配置，不包含运行时状态。
"""

from __future__ import annotations

from typing import Any

DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "name": "javBus",
        "enabled": True,
        "priority": 1,
        "type": "feature",
        "feature": "jav_code",
        "request": {
            "url": "https://www.busfan.cyou/{jav_code}",
            "method": "GET",
            "encoding": "auto",
        },
        "extract": {
            "title": 'xpath: //a[@class="bigImage"]/img/@title',
            "code": (
                'xpath: //div[contains(@class,"info")]//p[1]'
                '//span[contains(@style,"CC0000")]/text()'
            ),
            "release_date": 'xpath: //p[contains(.,"發行日期")]/text()',
            "actresses": {
                "selector": 'xpath: //div[contains(@class,"star-box")]//a[@title]',
                "name": "@title",
                "url": "@href",
            },
            "tags": 'xpath: //span[@class="genre"]/label/a/text() | array',
            "cover_url": 'xpath: //a[@class="bigImage"]/img/@src',
            "runtime_sec": 'xpath: //p[contains(.,"長度")]/text()',
            "series": 'xpath: //p[contains(.,"系列")]/a/text()',
            "overview": 'xpath: //meta[@name="description"]/@content',
            "censored": (
                'xpath: //ul[contains(@class,"nav")]'
                '//li[contains(@class,"active")]/a/text()'
            ),
            "studio": 'xpath: //p[contains(.,"製作商")]/a/text()',
        },
        "validators": [],
        "defaults": {},
    },
    {
        "name": "javBusActress",
        "enabled": True,
        "priority": 20,
        "type": "actress",
        "request": {
            "url": "{actress_url}",
            "method": "GET",
            "encoding": "auto",
            "rate_limit": {"qps": 1},
        },
        "extract": {
            "birth_date": (
                'xpath: //div[contains(@class,"avatar-box")]'
                '//p[contains(.,"生日")]/text()'
            ),
            "height_cm": (
                'xpath: //div[contains(@class,"avatar-box")]'
                '//p[contains(.,"身高")]/text()'
            ),
            "cup": r"regex: 罩杯[:：]\s*([A-Za-z]+)",
            "bust_cm": (
                'xpath: //div[contains(@class,"avatar-box")]'
                '//p[contains(.,"胸圍")]/text()'
            ),
            "waist_cm": (
                'xpath: //div[contains(@class,"avatar-box")]'
                '//p[contains(.,"腰圍")]/text()'
            ),
            "hips_cm": (
                'xpath: //div[contains(@class,"avatar-box")]'
                '//p[contains(.,"臀圍")]/text()'
            ),
            "cover_url": 'xpath: //div[contains(@class,"avatar-box")]//img/@src',
        },
        "defaults": {"nationality": "日本"},
        "validators": [],
    },
]
