"""内置刮削源模板。

模板只提供结构，不含任何凭据：TMDB 使用 ``vars.api_key`` 占位，
用户在设置页填入自己的密钥即可。模板通过 API 实例化为普通自定义源，
之后可以自由编辑或删除。

说明：
- TMDB 使用 ``api.tmdb.org`` 备用域名，部分网络下 ``api.themoviedb.org``
  会被 DNS 污染而无法访问；
- Shikimori 是 MyAnimeList 的镜像，无需密钥，但要求可识别的 User-Agent。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import NotFoundError

SHIKIMORI_UA = "WengGui/VBob (https://github.com/WengGui/VBob)"

TMDB_KEY_HINT = "请先在 themoviedb.org 申请 API Key，并填入「API 密钥」。"

# TMDB 电影：搜索接口提供中文标题/简介/海报，详情接口补齐时长、类型与导演。
TMDB_MOVIE_EXTRACT = {
    "_tmdb_id": "json: results[0].id",
    "title": "json: results[0].title",
    "release_date": "json: results[0].release_date",
    "overview": "json: results[0].overview",
    "cover_url": "json: results[0].poster_path",
}
TMDB_MOVIE_DETAIL_EXTRACT = {
    "original_title": "json: original_title",
    "runtime_sec": "json: runtime",
    "genres": "json: genres[*].name",
    "studio": "json: production_companies[0].name",
    "country": "json: production_countries[0].name",
    "series": "json: belongs_to_collection.name",
    "director": "json: credits.crew[?job=='Director'] | [0].name",
    "overview": "json: overview",
}

# TMDB 剧集/动漫共用 /search/tv 与 /tv/{id}，只是媒体类型不同。
TMDB_TV_EXTRACT = {
    "_tmdb_id": "json: results[0].id",
    "title": "json: results[0].name",
    "release_date": "json: results[0].first_air_date",
    "overview": "json: results[0].overview",
    "cover_url": "json: results[0].poster_path",
}
TMDB_TV_DETAIL_EXTRACT = {
    "original_title": "json: original_name",
    "runtime_sec": "json: episode_run_time[0]",
    "genres": "json: genres[*].name",
    "studio": "json: production_companies[0].name",
    "country": "json: production_countries[0].name",
    "director": "json: created_by[0].name",
    "overview": "json: overview",
}


def _tmdb_config(
    name: str,
    category: str,
    search_path: str,
    detail_path: str,
    extract: dict[str, str],
    detail_extract: dict[str, str],
    priority: int,
) -> dict[str, Any]:
    """拼装 TMDB 源配置；电影与剧集只有路径和字段不同。"""
    return {
        "name": name,
        "enabled": True,
        "priority": priority,
        "type": "query",
        "category": category,
        "vars": {"api_key": ""},
        "request": {
            "url": (
                f"https://api.tmdb.org/3{search_path}"
                "?api_key={api_key}&language=zh-CN&include_adult=false&query={title}"
            ),
            "method": "GET",
            "timeout_ms": 15000,
            "rate_limit": {"qps": 4},
        },
        # TMDB 海报是根相对路径，需要拼到图片 CDN 而不是 API 域名。
        "asset_base_url": "https://image.tmdb.org/t/p/w500",
        "extract": extract,
        "detail": {
            "url": (
                f"https://api.tmdb.org/3{detail_path}"
                "?api_key={api_key}&language=zh-CN&append_to_response=credits"
            ),
            "method": "GET",
            "extract": detail_extract,
        },
    }


SOURCE_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "tmdb-movie",
        "name": "TMDB 电影",
        "description": f"按标题搜索电影，补全中文名、简介、海报、时长、类型、导演。{TMDB_KEY_HINT}",
        "config": _tmdb_config(
            "TMDB 电影",
            "movie",
            "/search/movie",
            "/movie/{_tmdb_id}",
            TMDB_MOVIE_EXTRACT,
            TMDB_MOVIE_DETAIL_EXTRACT,
            100,
        ),
    },
    {
        "key": "tmdb-series",
        "name": "TMDB 剧集",
        "description": f"按标题搜索电视剧，补全中文名、简介、海报、类型与制作公司。{TMDB_KEY_HINT}",
        "config": _tmdb_config(
            "TMDB 剧集",
            "series",
            "/search/tv",
            "/tv/{_tmdb_id}",
            TMDB_TV_EXTRACT,
            TMDB_TV_DETAIL_EXTRACT,
            100,
        ),
    },
    {
        "key": "tmdb-anime",
        "name": "TMDB 动漫",
        "description": f"按标题搜索动画剧集，优先提供中文标题与简介。{TMDB_KEY_HINT}",
        "config": _tmdb_config(
            "TMDB 动漫",
            "anime",
            "/search/tv",
            "/tv/{_tmdb_id}",
            TMDB_TV_EXTRACT,
            TMDB_TV_DETAIL_EXTRACT,
            100,
        ),
    },
    {
        "key": "theporndb",
        "name": "ThePornDB",
        "description": (
            "欧美成人影片/场景元数据，按标题搜索；需要 ThePornDB API Token。"
        ),
        "config": {
            "name": "ThePornDB",
            "enabled": True,
            "priority": 100,
            "type": "query",
            "category": "other",
            "vars": {"api_key": ""},
            "request": {
                "url": "https://api.theporndb.net/graphql",
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer {api_key}",
                    "Accept": "application/json",
                },
                # stash-box 兼容的 GraphQL 查询；字段可按实际响应增删。
                "body": {
                    "query": (
                        "query SearchScene($term: String!) { "
                        "searchScene(term: $term) { id title details date image "
                        "studio { name } performers { performer { name } } "
                        "tags { name } } }"
                    ),
                    "variables": {"term": "{title}"},
                },
                "timeout_ms": 15000,
                "rate_limit": {"qps": 1},
            },
            "extract": {
                "title": "json: data.searchScene[0].title",
                "release_date": "json: data.searchScene[0].date",
                "overview": "json: data.searchScene[0].details",
                "cover_url": "json: data.searchScene[0].image",
                "studio": "json: data.searchScene[0].studio.name",
                "tags": "json: data.searchScene[0].tags[*].name",
                "actresses": (
                    "json: data.searchScene[0].performers[*].performer.name"
                ),
            },
        },
    },
    {
        "key": "shikimori-anime",
        "name": "Shikimori 动漫",
        "description": "MyAnimeList 镜像，补全原名、海报、类型与制作公司；无需密钥。",
        "config": {
            "name": "Shikimori 动漫",
            "enabled": True,
            "priority": 110,
            "type": "query",
            "category": "anime",
            "request": {
                "url": "https://shikimori.one/api/animes?search={title}&limit=1",
                "method": "GET",
                "headers": {"User-Agent": SHIKIMORI_UA},
                "timeout_ms": 15000,
                "rate_limit": {"qps": 1},
            },
            # 封面是 /system/... 根相对路径。
            "asset_base_url": "https://shikimori.one",
            "extract": {
                "_shiki_id": "json: [0].id",
                "title": "json: [0].name",
                "release_date": "json: [0].aired_on",
                "cover_url": "json: [0].image.original",
            },
            "detail": {
                "url": "https://shikimori.one/api/animes/{_shiki_id}",
                "method": "GET",
                "extract": {
                    "title": "json: name",
                    "original_title": "json: japanese[0]",
                    # Shikimori 的 description 是俄文，中文简介交给 TMDB 提供。
                    "release_date": "json: aired_on",
                    "cover_url": "json: image.original",
                    "runtime_sec": "json: duration",
                    "genres": "json: genres[*].name",
                    "studio": "json: studios[0].name",
                },
            },
        },
    },
]


def list_templates() -> list[dict[str, Any]]:
    """返回模板的公开信息，供设置页展示；配置深拷贝避免调用方修改内置数据。"""
    return [
        {
            "key": template["key"],
            "name": template["name"],
            "description": template["description"],
            "config": deepcopy(template["config"]),
        }
        for template in SOURCE_TEMPLATES
    ]


def get_template(key: str) -> dict[str, Any]:
    """按 key 取模板；不存在时抛 NotFoundError。"""
    for template in SOURCE_TEMPLATES:
        if template["key"] == key:
            return deepcopy(template)
    raise NotFoundError("刮削源模板不存在")
