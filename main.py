import re
from bs4 import BeautifulSoup, Comment, Doctype
import sys
from PIL import Image
import requests
import io

RESET = "\x1b[0m"

def rgb_to_ansi_fg(r, g, b):
    return f"\x1b[38;2;{r};{g};{b}m"

def rgb_to_ansi_bg(r, g, b):
    return f"\x1b[48;2;{r};{g};{b}m"

def image_to_terminal_art(image_source, max_width=80, char_aspect_ratio=0.5):
    try:
        img = Image.open(image_source).convert("RGB")
    except Exception as e:
        print(f"Error opening or processing image: {e}", file=sys.stderr)
        return

    original_width, original_height = img.size
    target_height_chars = int((original_height / original_width) * max_width * char_aspect_ratio)
    target_height_chars = max(1, target_height_chars + (target_height_chars % 2)) # Ensure even

    resized_height_pixels = target_height_chars * 2
    resized_width_pixels = int(original_width * (resized_height_pixels / original_height))

    if resized_width_pixels > max_width:
        resized_width_pixels = max_width
        resized_height_pixels = int(original_height * (resized_width_pixels / original_width))
        resized_height_pixels += resized_height_pixels % 2

    img = img.resize((resized_width_pixels, resized_height_pixels), Image.Resampling.LANCZOS)
    pixels = img.load()

    output_lines = []
    for y in range(0, resized_height_pixels, 2):
        line = []
        for x in range(resized_width_pixels):
            top_pixel_rgb = pixels[x, y]
            bottom_pixel_rgb = pixels[x, min(y + 1, resized_height_pixels - 1)]
            line.append(f"{rgb_to_ansi_fg(*bottom_pixel_rgb)}{rgb_to_ansi_bg(*top_pixel_rgb)}▄")
        output_lines.append("".join(line) + RESET)
    print("\n".join(output_lines))

BOLD = "\x1b[1m"
UNDERLINE = "\x1b[4m"
BLACK_FG = "\x1b[30m"
RED_FG = "\x1b[31m"
GREEN_FG = "\x1b[32m"
YELLOW_FG = "\x1b[33m"
BLUE_FG = "\x1b[34m"
CYAN_FG = "\x1b[36m"
WHITE_BG = "\x1b[47m"

class TextNode:
    def __init__(self, text):
        self.text = text
    def render(self):
        return self.text

class Anchor:
    def __init__(self, text, href):
        self.text = text
        self.href = href
    def render(self):
        return f" {BLUE_FG}{UNDERLINE}{self.text}{RESET} "

class Paragraph:
    def __init__(self, content_parts):
        self.content_parts = content_parts
    def render(self):
        return "".join(part.render() for part in self.content_parts) + "\n"

class Heading:
    def __init__(self, text, level=1):
        self.text = text
        self.level = level
    def render(self):
        style = {1: BLUE_FG, 2: GREEN_FG}.get(self.level, YELLOW_FG)
        return f"\n{BOLD}{style}{'#' * self.level} {self.text}{RESET}\n"

class ListElement:
    def __init__(self, items_content_parts):
        self.items_content_parts = items_content_parts
    def render(self):
        rendered_items = [f"{CYAN_FG}•{RESET} {"".join(part.render() for part in item_parts)}"
                          for item_parts in self.items_content_parts]
        return "\n".join(rendered_items) + "\n"

class Button:
    def __init__(self, label):
        self.label = label
    def render(self):
        return f" {BLACK_FG}{WHITE_BG}{BOLD}[ {self.label} ]{RESET}\n"

class Div:
    def __init__(self, *elements):
        self.elements = elements
    def render(self):
        return "\n\n" + "".join(element.render() for element in self.elements).strip('\n') + "\n\n"

class ImageElement:
    def __init__(self, src, base_url=None, max_width=80):
        self.src = src
        self.base_url = base_url
        self.max_width = max_width

    def render(self):
        try:
            image_url = self.src
            if self.src.startswith("/") and self.base_url:
                image_url = self.base_url.rstrip("/") + self.src

            response = requests.get(image_url, timeout=5)
            response.raise_for_status()

            image_file = io.BytesIO(response.content)
            image_to_terminal_art(image_file, max_width=self.max_width)
            print(f"\n[Image: {image_url}]\n")
            return ""
        except Exception as e:
            return f"\n[Error rendering image {self.src}: {e}]\n"

class Parser:
    def parse(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        page_title = soup.find('title').get_text(strip=True) if soup.find('title') else "No Title"
        return self._parse_elements(soup.find('html') or soup), page_title

    def _parse_elements(self, tag):
        if isinstance(tag, str):
            return [TextNode(tag.strip())] if tag.strip() else []
        if not hasattr(tag, 'name') or isinstance(tag, (Comment, Doctype)) or tag.name.lower() in {'style', 'script', 'noscript'}:
            return []

        tag_name = tag.name.lower()
        if tag_name in ['h1', 'h2', 'h3']:
            return [Heading(tag.get_text(strip=True), level=int(tag_name[1]))]
        elif tag_name == 'p':
            return [Paragraph(self._parse_inline_content(tag))]
        elif tag_name == 'ul':
            return [ListElement([self._parse_inline_content(li) for li in tag.find_all('li', recursive=False)])]
        elif tag_name == 'a':
            text = tag.get_text(strip=True)
            return [Anchor(text, tag.get('href', '#'))] if text else []
        elif tag_name == 'button':
            return [Button(tag.get_text(strip=True))]
        elif tag_name == 'img':
            return [ImageElement(tag['src'])] if 'src' in tag.attrs else []
        else: # Container elements or unsupported tags
            elements = []
            for child in tag.contents:
                elements.extend(self._parse_elements(child))
            return elements or ([TextNode(tag.get_text(strip=True))] if tag.get_text(strip=True) else [])

    def _parse_inline_content(self, parent_tag):
        parsed_inline_elements = []
        for content_node in parent_tag.contents:
            if isinstance(content_node, (Comment, Doctype)):
                continue
            if isinstance(content_node, str):
                text = content_node.strip()
                if text and "endif" not in text.lower() and "[if" not in text.lower() and "<!" not in text:
                    parsed_inline_elements.append(TextNode(text))
            elif hasattr(content_node, 'name'):
                tag_name = content_node.name.lower()
                if tag_name in {'script', 'style', 'noscript'}:
                    continue
                elif tag_name == 'a':
                    text = content_node.get_text(strip=True)
                    if text:
                        parsed_inline_elements.append(Anchor(text, content_node.get('href', '#')))
                elif tag_name == 'img':
                    if 'src' in content_node.attrs:
                        parsed_inline_elements.append(ImageElement(content_node['src']))
                else:
                    text = content_node.get_text(strip=True)
                    if text:
                        parsed_inline_elements.append(TextNode(text))
        return parsed_inline_elements

class Renderer:
    def clear(self):
        print("\033c", end="")

    def render(self, elements, title=None):
        if title:
            print(f"{BOLD}{CYAN_FG}{'=' * (len(title) + 6)}\n=== {title} ===\n{'=' * (len(title) + 6)}{RESET}\n")
        for element in elements:
            if isinstance(element, ImageElement):
                element.render()
            else:
                print(element.render(), end='')

    def refresh(self, elements, title=None):
        self.clear()
        self.render(elements, title)

class Browser:
    def __init__(self):
        self.history = []
        self.current_url = None
        self.parser = Parser()
        self.renderer = Renderer()
        self.search_db = {
            "hello": """<title>Hello World!</title><h1>Hello Page</h1><p>Welcome to the hello page!</p><img src="hello_image.png" alt="Hello"><ul><li>Greeting</li><li>World</li></ul>""",
            "python": """<title>Python Info</title><h1>Python Programming</h1><p>Python is a high-level, interpreted programming language.</p><p>Learn more at <a href="https://python.org">python.org</a>.</p><button>Go to Python Website</button>""",
            "example": """<title>Example Result</title><h1>Example Search Result</h1><p>This is a custom result for 'example'.</p>"""
        }

    def navigate(self, url):
        self.current_url = url
        self.history.append(url)
        self._load_content(url)

    def _load_content(self, url):
        html_content = ""
        try:
            if url == "home":
                html_content = """<title>TUI Browser Home</title><h1>Welcome to the TUI Browser!</h1><p>Type go &lt;url&gt; to navigate, search &lt;query&gt; to search, or back to go back.</p><img src="browser_icon.png" alt="Browser Icon"><ul><li>Example Link: <a href="example.com">Go to Example</a></li><li>Another Page: <a href="another_page">Another Local Page</a></li></ul>"""
            elif url == "another_page":
                html_content = """<title>Another Page</title><h1>Another Page</h1><p>You've navigated to another local page.</p><p>Go <a href="home">back home</a>.</p>"""
            elif url.startswith("search:"):
                query = url[7:].strip()
                html_content = self.search_db.get(query, f"""<title>Search Results for "{query}"</title><h1>Search Results for "{query}"</h1><p>No results found for your query. Try 'hello', 'python', or 'example'.</p>""")
            else:
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
                print(f"Fetching {url}...")
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                html_content = response.text
                print(f"Successfully fetched {url}")
        except requests.exceptions.RequestException as e:
            html_content = f"""<title>Error</title><h1>Error Loading Page</h1><p>Could not load {url}</p><p>Error: {e}</p><p>Please check the URL and your internet connection.</p>"""
            print(f"Error fetching {url}: {e}", file=sys.stderr)
        except Exception as e:
            html_content = f"""<title>Unexpected Error</title><h1>An Unexpected Error Occurred</h1><p>Error: {e}</p>"""
            print(f"An unexpected error occurred: {e}", file=sys.stderr)

        elements, page_title = self.parser.parse(html_content)
        self.renderer.refresh(elements, page_title)

    def go_back(self):
        if len(self.history) > 1:
            self.history.pop()
            self.current_url = self.history[-1]
            self._load_content(self.current_url)
        else:
            print("No history to go back to.")

    def handle_input(self, user_input):
        if user_input.startswith("go "):
            self.navigate(user_input[3:].strip())
        elif user_input.startswith("search "):
            self.navigate(f"search:{user_input[7:].strip()}")
        elif user_input == "back":
            self.go_back()
        else:
            print("Unknown command. Commands: go <url>, search <query>, back, quit")

    def start(self):
        print("Welcome to the TUI Web Browser!\nCommands: go <url>, search <query>, back, quit")
        self._load_content("home")
        while True:
            user_input = input("> ")
            if user_input == "quit":
                print("Exiting browser.")
                break
            self.handle_input(user_input)

def main():
    browser = Browser()
    browser.start()

if __name__ == "__main__":
    main()
