#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


README_PATH = Path(__file__).resolve().parents[1] / "README.md"
SECTION_START = "<!-- integration-translation-report:start -->"
SECTION_END = "<!-- integration-translation-report:end -->"


REPOSITORIES = [
    {
        "full_name": "TheIntroDB/universal-extension",
        "description": "A browser extension to integrate TIDB into almost any site!",
    },
    {
        "full_name": "TheIntroDB/jellyfin-plugin",
        "description": "A Jellyfin plugin to skip intros, recaps, and credits with TheIntroDB",
    },
    {
        "full_name": "TheIntroDB/stremio-enhanced-plugin",
        "description": "Skip segments for shows and movies in Stremio Enhanced using TheIntroDB",
    },
    {
        "full_name": "TheIntroDB/kodi-addon",
        "description": "A Kodi addon to skip intro, recap, credits, and preview segments in movies and TV shows with TheIntroDB!",
    },
    {
        "full_name": "TheIntroDB/emby-plugin",
        "description": "An Emby plugin to skip intros, recaps, and credits with TheIntroDB",
    },
]


TRANSLATION_ROOT_NAMES = {
    "_locales",
    "l10n",
    "locale",
    "locales",
    "localisation",
    "localization",
    "lang",
    "langs",
    "language",
    "languages",
    "i18n",
    "intl",
    "translation",
    "translations",
}

LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:[-_][a-z0-9]{2,8}){0,2}$", re.IGNORECASE)
RESOURCE_LANGUAGE_RE = re.compile(r"^resource\.language\.([a-z0-9_@-]+)$", re.IGNORECASE)
LOCALE_FILE_RE = re.compile(r"^(?P<locale>[a-z]{2,3}(?:[-_][a-z0-9]{2,8}){0,2})$", re.IGNORECASE)
FILE_LOCALE_RE = re.compile(
    r"^(?P<stem>.+?)[._-](?P<locale>[a-z]{2,3}(?:[-_][a-z0-9]{2,8}){0,2})\.(?P<ext>json|ya?ml|po|mo|resx|xml|properties|ini)$",
    re.IGNORECASE,
)
TRANSLATION_FILE_EXTENSIONS = {
    ".json",
    ".yaml",
    ".yml",
    ".po",
    ".mo",
    ".resx",
    ".xml",
    ".properties",
    ".ini",
}
TRANSLATION_CODE_FILE_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
}


@dataclass
class TranslationRoot:
    path: str
    languages: set[str]


def api_get_json(url: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "theintrodb-translations-report",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def normalize_language(language: str) -> str:
    return language.replace("-", "_").lower()


def is_locale(value: str) -> bool:
    return bool(LOCALE_RE.fullmatch(value))


def nearest_translation_root(parts: list[str], file_index: int) -> str | None:
    for index in range(file_index - 1, -1, -1):
        if parts[index].lower() in TRANSLATION_ROOT_NAMES:
            return "/".join(parts[: index + 1])
    return None


def detect_translation_roots(paths: Iterable[str]) -> list[TranslationRoot]:
    roots: dict[str, TranslationRoot] = {}

    for path in paths:
        parts = path.split("/")
        if not parts:
            continue

        for index, part in enumerate(parts[:-1]):
            resource_match = RESOURCE_LANGUAGE_RE.fullmatch(part)
            if resource_match and index > 0:
                root_path = "/".join(parts[:index])
                language = normalize_language(resource_match.group(1))
                roots.setdefault(root_path, TranslationRoot(path=root_path, languages=set())).languages.add(language)

            if part.lower() in TRANSLATION_ROOT_NAMES and index + 1 < len(parts):
                candidate = parts[index + 1]
                if is_locale(candidate):
                    root_path = "/".join(parts[: index + 1])
                    language = normalize_language(candidate)
                    roots.setdefault(root_path, TranslationRoot(path=root_path, languages=set())).languages.add(language)

        file_name = parts[-1]
        suffix = Path(file_name).suffix.lower()
        if suffix in TRANSLATION_FILE_EXTENSIONS:
            match = FILE_LOCALE_RE.fullmatch(file_name)
            if match and not is_locale(match.group("stem")):
                locale = normalize_language(match.group("locale"))
                parent = "/".join(parts[:-1]) or "."
                roots.setdefault(parent, TranslationRoot(path=parent, languages=set())).languages.add(locale)

            locale_only_match = LOCALE_FILE_RE.fullmatch(Path(file_name).stem)
            if locale_only_match:
                root_path = nearest_translation_root(parts, len(parts) - 1)
                if root_path:
                    locale = normalize_language(locale_only_match.group("locale"))
                    roots.setdefault(root_path, TranslationRoot(path=root_path, languages=set())).languages.add(locale)

        if suffix in TRANSLATION_CODE_FILE_EXTENSIONS:
            locale_only_match = LOCALE_FILE_RE.fullmatch(Path(file_name).stem)
            if locale_only_match:
                root_path = nearest_translation_root(parts, len(parts) - 1)
                if root_path:
                    locale = normalize_language(locale_only_match.group("locale"))
                    roots.setdefault(root_path, TranslationRoot(path=root_path, languages=set())).languages.add(locale)

    return sorted(roots.values(), key=lambda root: root.path)


def collect_repo_status(full_name: str, description: str) -> dict:
    repo = api_get_json(f"https://api.github.com/repos/{full_name}")
    default_branch = repo["default_branch"]
    tree = api_get_json(
        f"https://api.github.com/repos/{full_name}/git/trees/{default_branch}?recursive=1"
    )
    paths = [item["path"] for item in tree.get("tree", [])]
    translation_roots = detect_translation_roots(paths)

    return {
        "full_name": full_name,
        "html_url": repo["html_url"],
        "default_branch": default_branch,
        "description": description,
        "translation_roots": translation_roots,
    }


def markdown_link(url: str, label: str) -> str:
    return f"[{label}]({url})"


def render_repo_lines(statuses: list[dict]) -> list[str]:
    lines: list[str] = []
    lines.append("| Repository | Translation Path(s) | Languages |")
    lines.append("| --- | --- | --- |")

    for status in statuses:
        repo_name = status["full_name"].split("/", 1)[1]
        repo_link = markdown_link(status["html_url"], repo_name)

        if status["translation_roots"]:
            paths = []
            languages = []
            for root in status["translation_roots"]:
                if root.path == ".":
                    root_url = status["html_url"]
                else:
                    encoded_path = quote(root.path)
                    root_url = f"{status['html_url']}/tree/{status['default_branch']}/{encoded_path}"
                paths.append(markdown_link(root_url, root.path))
                languages.append(", ".join(sorted(root.languages)))
            path_cell = "<br>".join(paths)
            language_cell = "<br>".join(languages)
        else:
            path_cell = "Not detected"
            language_cell = "-"

        lines.append(f"| {repo_link} | {path_cell} | {language_cell} |")

    return lines


def render_generated_section(statuses: list[dict]) -> str:
    lines = [
        SECTION_START,
        "",
        "### Integration Status",
        "",
        "This table is generated automatically by the scheduled workflow and scans each integration repository for translation directories and locale folders. `Not detected` means the scan did not find a recognized translation structure in the repository tree.",
        "",
        *render_repo_lines(statuses),
        "",
        SECTION_END,
    ]
    return "\n".join(lines)


def update_readme(section: str) -> None:
    content = README_PATH.read_text(encoding="utf-8")

    if SECTION_START in content and SECTION_END in content:
        pattern = re.compile(
            rf"{re.escape(SECTION_START)}.*?{re.escape(SECTION_END)}",
            re.DOTALL,
        )
        updated = pattern.sub(section, content)
    else:
        insertion_point = "To edit or add translation files or strings for an integration, please open a pull request in the relevant repository.\n"
        updated = content.replace(
            insertion_point,
            insertion_point + "\n" + section + "\n",
        )

    README_PATH.write_text(updated, encoding="utf-8")


def main() -> int:
    statuses = []
    failures = []

    for repo in REPOSITORIES:
        try:
            statuses.append(collect_repo_status(repo["full_name"], repo["description"]))
        except (HTTPError, URLError, TimeoutError) as error:
            failures.append(f"{repo['full_name']}: {error}")

    if failures:
        failure_text = "\n".join(failures)
        raise RuntimeError(f"Failed to fetch one or more repositories:\n{failure_text}")

    section = render_generated_section(statuses)
    update_readme(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
