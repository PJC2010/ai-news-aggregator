from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import trafilatura


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(html: str) -> str:
    parser = PlainText()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


class ArticleParser:
    def __init__(self, client):
        self.client = client
        self.robots = {}

    async def authorize(self, url: str) -> float:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            robot = RobotFileParser()
            try:
                response = await self.client.get(origin + "/robots.txt")
                robot.parse(response.text.splitlines())
            except Exception:
                # Cache denial for this run to avoid repeatedly retrying a failing origin.
                robot.parse(["User-agent: *", "Disallow: /"])
            self.robots[origin] = robot
        robot = self.robots[origin]
        agent = self.client.settings.user_agent
        if not robot.can_fetch(agent, url):
            raise PermissionError("Article extraction is not permitted by robots policy")
        return robot.crawl_delay(agent) or 0

    async def extract(self, url: str) -> str:
        try:
            # Check the robots policy for every redirected URL, before fetching its body.
            response = await self.client.get(url, authorize=self.authorize)
        except PermissionError:
            return ""
        if "html" not in response.headers.get("content-type", "").lower():
            return ""
        return (
            trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            or ""
        )
