from urllib.parse import quote, urlparse
from collections.abc import Iterator
from datetime import datetime as dt
from pathlib import Path
import asyncio
import hashlib
import json
import sys
import re

import yaml
import click
import httpx
import mistune
import edge_tts
import validators
import questionary
from loguru import logger
import py3langid as langid
from rich.table import Table
from pydefuddle import defuddle
from readability import Document
from rich.console import Console
from rich.traceback import install
from markdownify import markdownify as md
from rich.progress import Progress, SpinnerColumn, TextColumn
from markdown_plain_text.extention import convert_to_plain_text


# :::::::::: TO-DO :::::::::::
# ✔️ Add Translate
# ✔️ @click
# ✔️ Add Download for PDF articles
# ✔️ Add MS TTS EDGE
# ✔️ Check settings / paths
# Handle errors
# ✔️ Tags function
# Replace build_template to kwargs(?())
# ✔️ Add detailed information during sync
# ✔️ Only create audio if the article length is < n
# ✔️ Using a class in main
# ====================================


# :::::::::: LOAD SETTINGS ::::::::::
settings_file = Path(__file__).parent.joinpath("Settings.yaml")

with open(settings_file, "r", encoding="utf-8") as file:
  settings = yaml.safe_load(file)

# --- Paths ----
OFFLINE_DIR = Path(__file__).parent.joinpath("Offline")
ARTICLES_DIR = Path(settings["PATHS"]["ARTICLES_DIR"])
ATTACHMENTS_DIR = Path(settings["PATHS"]["ATTACHMENTS_DIR"])
ARTICLES_SYNCED_DIR = Path(__file__).parent.joinpath("Done")
TEMPLATE = Path(__file__).parent.joinpath("Template")

# --- Settings ---
TRANSLATE_LANGUAGES = settings["OTHERS"]["TRANSLATE_LANGUAGES"]
USER_AGENT = settings["OTHERS"]["USERAGENT"]
DATETIME_FORMAT = settings["OTHERS"]["DATETIME_FORMAT"]
DEFAULT_LANGUAGE = settings["OTHERS"]["DEFAULT_LANGUAGE"]
REQUEST_TIMEOUT = settings["OTHERS"]["REQUEST_TIMEOUT"]
READING_THRESHOLD = settings["OTHERS"]["READING_THRESHOLD"]
WPM = settings["OTHERS"]["WPM"]
DEL_SYNCED_ARTICLES = settings["OTHERS"]["DEL_SYNCED_ARTICLES"]
USERAGENT = settings["OTHERS"]["USERAGENT"]
TTS_VOICE = settings["OTHERS"]["TTS_VOICE"]

# --- PARAM DEFAULTS ----
PARAM_DEFAULTS = settings["PARAM_DEFAULTS"]

# --- API ---
CLOUDFARE_URL = settings["API"]["CLOUDFARE_URL"]
API_KEY = settings["API"]["API_KEY"]

# --- REGEX ---
RULES_REGEX = settings["REGEX"]
URL_REGEX = r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9]{1,6}\b(?:[-a-zA-Z0-9@:%_\+.~#?&/=]*)"

# --- LOGS ---
LOG_FILE = Path(__file__).parent /  "logs.log" 
logger.add(LOG_FILE, format="\n" + "="*50 + "\n{time: HH:mm:ss} | {level} | LINE: {line} \n" + "="*50 + "\n")

# --- CHECK FOLDERS ---
for folder_path in [OFFLINE_DIR, ARTICLES_DIR, ATTACHMENTS_DIR, ARTICLES_SYNCED_DIR]:
  folder_path.mkdir(parents=True, exist_ok=True)
# ====================================


# --- Trackback Handler ---
install(show_locals=True)
console = Console()
langid.set_languages(TRANSLATE_LANGUAGES)


# :::::::::: TUI - MAIN ::::::::::
def main_tui() -> None:
  while True:
    action = questionary.select("What do you want to do?", choices=["1. Sync articles", "2. View saved articles", "3. Add URL", "4. Exit"],).ask()
  
    match action:
      case "1. Sync articles":
        asyncio.run(handle_sync())
      
      case "2. View saved articles":
        view_saved_articles()
      
      case "3. Add URL":
        menu_add_url()
      
      case "4. Exit":
        break
# ====================================


# :::::::::: TUI - ADD URL ::::::::::
def menu_add_url() -> None:
  option = questionary.select("How do you want to add it?", choices=["1. Single URL", "2. From file", "3. Back"],).ask()

  match option:
    case "1. Single URL":
      save_single_url(input("Entered the url: "), PARAM_DEFAULTS)
    case "2. From file":
      save_multiples_url(input("Entered the file path: "), PARAM_DEFAULTS)
    case "3. Back":
      main_tui()
# ====================================


# :::::::::: JSON DATA ::::::::::
def get_json_data(json_path: Path) -> str:
  with open(json_path, "r", encoding="utf-8") as f:
    return json.load(f)
# ====================================


# :::::::::: TUI - VIEW SAVED LINKS ::::::::::
def view_saved_articles() -> None:

  # --- Get article list ---
  json_files = list(OFFLINE_DIR.glob("*.json"))

  if not len(json_files):
    show_message("No items saved")

  else:
    json_data = [data for json_f in json_files if (data := get_json_data(json_f))]

    # --- Build Table ---
    table = Table(title="Links saved", show_lines=True)
    table.add_column("Url", style="cyan")
    table.add_column("Created", style="yellow", justify="center")
    table.add_column("Attributes", style="green", justify="center")

    # --- Get Attributes ---
    for data in json_data:
      valid_attr = [k for k, v in data.items() if v and k not in ["url", "sync", "creation_date", "input_file"]]
      attributes = " - ".join(valid_attr)

      table.add_row(data["url"], str(data["creation_date"]), attributes)

    console.print(table)
# ====================================


# :::::::::: GET URLS  ::::::::::
@click.command()
@click.argument("url", required=False)
@click.option("-l", "--labels", type=str, help="Add tags to the article")
@click.option("-t", "--translate", is_flag=True, help="Translate article")
@click.option("-v", "--voice", is_flag=True, help="Create an audio version of the article")
@click.option("-r", "--regex", is_flag=True, help="Apply custom regex")
@click.option("-i", "--input-file", type=str, help="Save urls from an external file")
@click.option("-p", "--pdfs", type=str, help="Download external pdfs")
@click.option("-s", "--sync", is_flag=True, help="Start sync")
def main_cli(**kwargs) -> None:
  params = kwargs
  
  # --- Save urls from file ---
  input_file = params.get("input_file")
  # --- TUI ---
  cli_set = params.get("input_file"), params.get("url"), params.get("sync")
  if not any(cli_set):
    main_tui()
   
   # --- Multiples urls ---
  elif input_file:
    save_multiples_url(input_file, params)

  # --- Save single url ---
  elif params.get("url"):
    url = params.get("url")
    save_single_url(url, params)

  # --- Start sync ---
  elif params.get("sync"):
    asyncio.run(handle_sync())
# ====================================


# :::::::::: SAVE MULTIPLE URLS FROM CLI ::::::::::
def save_multiples_url(input_file: str, params: dict) -> None:

  # --- Load urls from file ---
  with open(input_file, "r", encoding="utf-8") as f:
    content = f.readlines()
    valid_urls = [remove_tracking_param(url.strip()) for url in content if validators.url(url.strip())]

  # --- Save each url ---
  for url in valid_urls:
    unique_params = params.copy()
    creation_date = {"creation_date": dt.now().strftime("%Y-%m-%d %H:%M")}
    unique_params.update(creation_date)
    unique_params["url"] = url
    # del unique_params["input_file"]
    save_changes_on_file(unique_params)
  
  show_message(f"{len(valid_urls)} urls saved!")
# ====================================


# :::::::::: SAVE ONE URL ::::::::::
def save_single_url(url: str, params: dict) -> None:
  if not validators.url(url):
    show_message("Invalid url")
    return
 
  creation_date = {"creation_date": dt.now().strftime("%Y-%m-%d %H:%M")}
  params = params.copy()
  params.update(creation_date)
  params["url"] = remove_tracking_param(url)
  save_changes_on_file(params)
  
  show_message("Url saved!")
# ====================================


# ::::::::::REMOVE TRACKING PARAMETERS ::::::::::
def remove_tracking_param(url: str) -> str:
  return re.sub(r"[?&]utm[^&]*", "", url)
# ====================================


# :::::::::: SAVE PARAMETERS IN JSON ::::::::::
def save_changes_on_file(params: dict) -> None:
  if validators.url(params.get("url")):

    url = params.get("url").encode("utf-8")
    json_name = get_hash(url)
    full_path = OFFLINE_DIR.joinpath(f"{json_name}.json")
  
    with open(full_path, "w", encoding="utf-8") as f:
      json.dump(params, f, ensure_ascii=False, indent=4)
# ====================================


# :::::::::: GET WEB PAGE ::::::::::
@logger.catch
async def load_web_site(url: str, httpx_c: httpx.Client) -> str | None:
  response = await httpx_c.get(url, follow_redirects=True)
  return response.text if response.status_code == 200 else None
# ====================================


# :::::::::: GET HASH MD5 ::::::::::
def get_hash(text: bytes) -> str:
  return hashlib.md5(text).hexdigest()
# ====================================


# :::::::::: DOWNLOAD AND SAVE IMAGE ::::::::::
async def download_files(url: str, httpx_c: httpx.Client) -> str:
  try:
    response = await httpx_c.get(url, follow_redirects=True)
    content_type = response.headers.get('Content-Type', '')
    
    if response.status_code != 200:
      return f"![error downloading]({url})" # for avoid local images emptys
      
    file_obj =  response.content

    # --- Get info image ---
    file_extension = "." + content_type.split(";")[0].split("/")[1]
    md5_filename = get_hash(file_obj) + file_extension
    dst_path = ATTACHMENTS_DIR.joinpath(md5_filename)
      
    # --- Save image ---
    with open(dst_path, "wb") as file:
      file.write(file_obj)

    return md5_filename

  except Exception:  
    logger.exception("Error downloading images")
# ====================================


# :::::::::: CONTENT TYPE ::::::::::
@logger.catch
async def content_type(url: str, httpx_c: httpx.Client) -> str | None:
  response = await httpx_c.head(url, follow_redirects=True)
  return response.headers.get("content-type") if response.status_code == 200 else None
# ====================================

"""
# :::::::::: GET WIKILINKS ::::::::::
def get_wikilinks(md_article: str):
  regex_brackets = r"^[!\[].*\)$"
  urls_regex = r"https?://[^\s)\"']+"

  if brackets := re.findall(regex_brackets, md_article, re.MULTILINE):
    urls = [m.group(0) for url in brackets if (m := re.search(urls_regex, url))]
    return brackets, urls

  return [], []
# ====================================
"""

# :::::::::: CATCH BRACKETS ::::::::::
def catch_brackets(md_article: str) -> list | None:
  regex_brackets = r"^[!\\[].*\)$"
  return brackets if (brackets := re.findall(regex_brackets, md_article, re.MULTILINE)) else []
# ====================================


# :::::::::: CATCH IMG URLS ::::::::::
def catch_bra_urls(brackets: list) -> list | None:
  urls_regex = r"http[^)]*(?=\))"
  return urls if (urls := [m.group(0) for url in brackets if (m := re.search(urls_regex, url))]) else []
# ====================================


# :::::::::: SANITIZE FILENAME ::::::::::
def sanitize_text(text: str) -> str:
  cleaned_text = re.sub(r'[\\/:*?"<>|\.]+', "", text)
  return cleaned_text[:200]
# ====================================


# ::::: LOCAL TRANSLATE :::::
async def local_translate(text: str, httpx_c: httpx.Client) -> str:
  url = "http://10.111.222.1:7777/v1/chat/completions" 
  params={"model": "default", "messages": [{"role": "system", "content": "665"}, {"role": "user", "content": text}], "temperature": 0.3}
  
  try:
    response = await httpx_c.post(url, json=params, headers={"Authorization": "Bearer bbb"}, timeout=60)
    return response.json()["choices"][0]["message"]["content"].strip() if response.status_code == 200 else text
    
  except Exception:
    logger.exception("Error translating text")
    return text
# ====================================


# :::::::::: CLOUDFLARE TRANSLATE ::::::::::
async def cloudfare_translate(txt_translate: str, httpx_c: httpx.Client) -> str:
  prompt = f"""
  Translate the following text into {DEFAULT_LANGUAGE}.
  Keep the original meaning, tone, and logic completely unchanged.
  Use natural, fluent, and accurate expressions.
  Do not add extra explanations or comments.
  Output only the translated result.
  Text to translate: {txt_translate}
  """

  headers: dict = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
  }
  body: dict = {
    "messages": [
      {"role": "system", "content": prompt},
      {"role": "user", "content": ""},
    ]
  }

  try:
    response = await httpx_c.post(CLOUDFARE_URL, headers=headers, json=body)
    answer_content = response.json()["result"]["response"] 
    return answer_content if response.status_code == 200 else txt_translate

  except Exception:
    logger.exception("Error translating with cloudfare")
    return txt_translate
# ===================================


"""
# :::::::::: TRANSLATE - OLD ::::::::::
async def handle_translate(md_article: str, httpx_c: httpx.Client) -> str:
  md_styles_pattern = r"^[!\|\[$-]"

  # --- Split in paragraphs ---
  org_chunks = [chunk for chunk in md_article.splitlines() if chunk and not re.match(md_styles_pattern, chunk)]

  # --- Limit tasks ---
  semaphore = asyncio.Semaphore(4)

  async def rate_limit(chunk: str):
    async with semaphore:
      return await cloudfare_translate(chunk, httpx_c) 

  trans_tasks = [rate_limit(org_chunk) for org_chunk in org_chunks]

  trans_chunks: list = await asyncio.gather(*trans_tasks, return_exceptions=True)

  translated_map = dict(zip(org_chunks, trans_chunks))
  
  translated_article = md_article
  
  for original_chunk, translated_chunk in translated_map.items():
    translated_article = re.sub(re.escape(original_chunk), translated_chunk, translated_article, count=1)

  return translated_article
# ====================================
"""

# :::::::::: REGEX RULES (CONTENT) ::::::::::
def apply_custom_regex(content: str) -> str:
  for rule in RULES_REGEX:
    content = re.sub(rule["Pattern"], rule["Replacement"], content, flags=re.MULTILINE | re.DOTALL)
  return content
# ====================================


# :::::::::: SAVE TO FILE ::::::::::
def save_to_file(name_file: str, content: str) -> None:
  out_path = ARTICLES_DIR.joinpath(f"{name_file}.md")
  with open(out_path, "w", encoding="utf-8") as f:
    f.write(content)
# ====================================


# :::::::::: FORMAT TAGS ::::::::::
def format_tags(tags: str) -> str | None:
  x_tags = tags.split(",")
  return "\n" + "".join(f"  - {i}\n" for i in x_tags) if not tags else None
# ====================================


# :::::::::: BUILD TEMPLATE ::::::::::
def build_template(*args) -> str:
  creation_date, author, num_words, read_time, full_article, url, tags, audio, pdf_files = args
  
  metadata = {
    "%CREATIONDATE": creation_date,
    "%AUTHOR": author,
    "%WORDS": num_words,
    "%READTIME": read_time,
    "%ARTICLE": full_article,
    "%URL": url,
    "%TAGS": tags,
    "%AUDIO": audio,
    "%PDF": pdf_files
  }

  missing_values = [key for key, value in metadata.items() if not value]
  with open(TEMPLATE, "r", encoding="utf-8") as f:
    template = f.read()
  
  if missing_values:
    template = del_properties(template, missing_values)
  
  for var, value in filter(lambda item: item[0] not in missing_values, metadata.items()):
    if var in template:
      template = template.replace(str(var), str(value))

  return template
# ====================================


# :::::::::: DEL UNUSED PROPERTIES ::::::::::
def del_properties(text: str, properties: Iterator[str]):
  props_to_del = "|".join(properties)

  valid_lines = [line for line in text.split("\n") if not re.search(props_to_del, line)]
  cleaned_txt = '\n'.join(valid_lines)
  
  return cleaned_txt
# ====================================


# :::::::::: DELETE / MOVE JSON FINISHED ::::::::::
def delete_json(json_path: Path) -> None:
  done_path = ARTICLES_SYNCED_DIR.joinpath(json_path.name)
  json_path.unlink(missing_ok=True) if DEL_SYNCED_ARTICLES else json_path.rename(done_path)
# ====================================


# :::::::::: SHOW MESSAGES ::::::::::
def show_message(msg: str, custom_style="Bold") -> None:
  console.print(f"{msg}", style=custom_style)
# ====================================


# :::::::::: MICROSOFT EDGE TTS ::::::::::
@logger.catch
def text_to_voice(text: str, name_file: str) -> None:
  output_audio_file = ATTACHMENTS_DIR.joinpath(f"{name_file}.mp3")
  communicate = edge_tts.Communicate(text, TTS_VOICE)
  communicate.save_sync(output_audio_file)
# ====================================


# :::::::::: GET PDFS ::::::::::
@logger.catch
async def get_pdfs(md_article: str, httpx_c: httpx.Client) -> str | None:
  # --- Find all urls ---
  all_urls = re.findall(URL_REGEX, md_article, re.MULTILINE)

  filetype_results = await asyncio.gather(*[get_file_bytes(url, httpx_c) for url in all_urls], return_exceptions=True)

  valid_pdf_urls = [url for result in filetype_results if result and not isinstance(result, Exception) for data, url in [result] if data and data.startswith(b"%PDF")]

  if not valid_pdf_urls:
    return None

  download_tasks = [download_files(url, httpx_c) for url in valid_pdf_urls]
  pdfs_md5_names = await asyncio.gather(*download_tasks, return_exceptions=True)

  pdf_sublist = []
        
  for ext_pdf, local_pdf in zip(valid_pdf_urls, pdfs_md5_names):
    pdf_filename = ext_pdf.split("/")[-1]
    pdf_name_formated = re.sub(r"-|_|%\d{2}|(?<=\.pdf).+$", " ", pdf_filename).capitalize()
    pdf_sublist.append(f"\t - [{pdf_name_formated}]({local_pdf})\n")
          
  header = "- Papers cited in this article:" + "\n"
  stylized_sublist = header + "".join(pdf_sublist)
              
  return stylized_sublist
# ====================================


# :::::::::: GET FILE TYPE ::::::::::
@logger.catch
async def get_file_bytes(url: str, httpx_c: httpx.Client) -> tuple | None:
  response = await httpx_c.get(url, headers={"Range": "bytes=0-32"}, follow_redirects=True)
  return response.content, url if response.status_code == 206 else None
# ====================================


# :::::::::: MARKDOWN AND METADATA ::::::::::
def get_markdown(pure_html: str) -> tuple:
  readbility_obj = Document(pure_html)
  
  md_article = md(readbility_obj.summary(keep_all_images=True))

  author = sanitize_text(readbility_obj.author()) if not readbility_obj.author().startswith("[") else None
  
  title = sanitize_text(readbility_obj.title())

  num_words = len(md_article.split())
  
  read_time = num_words // WPM
  
  return md_article, author, title, num_words, read_time
# ====================================


# :::: CATCH MARKDOWN PARAGRAPHS (WTF WITH THESE FUNCTIONS 💀😭) :::::
def catch_md_paragraphs(children):
  result = []
  for node in children:
    node_type = node["type"]

    if node_type == "image":
      continue

    if node_type == "link":
      link_text = catch_md_paragraphs(node.get("children", []))
      url = node.get("attrs", {}).get("url", "")
      result.append(f"[{link_text}]({url})")
      continue

    if node_type == "emphasis":
      inner_text = catch_md_paragraphs(node.get("children", []))
      result.append(f"*{inner_text}*")
      continue

    if node_type == "strong":
      inner_text = catch_md_paragraphs(node.get("children", []))
      result.append(f"**{inner_text}**")
      continue

    if node_type == "codespan":
      text = node.get("raw", "")
      result.append(f"`{text}`")
      continue

    if node_type == "strikethrough":
      inner_text = catch_md_paragraphs(node.get("children", []))
      result.append(f"~~{inner_text}~~")
      continue

    if node_type == "underline":
      inner_text = catch_md_paragraphs(node.get("children", []))
      result.append(f"<u>{inner_text}</u>")
      continue

    if node_type == "mark":
      inner_text = catch_md_paragraphs(node.get("children", []))
      result.append(f"=={inner_text}==")
      continue

    if node_type == "subscript":
      inner_text = catch_md_paragraphs(node.get("children", []))
      result.append(f"~{inner_text}~")
      continue

    if node_type == "superscript":
      inner_text = catch_md_paragraphs(node.get("children", []))
      result.append(f"^{inner_text}^")
      continue

    if node_type == "inline_html":
      text = node.get("raw", "")
      result.append(text)
      continue

    text = node.get("raw")
    if text:
      result.append(text)
    elif node_type in ("linebreak", "softbreak"):
      result.append(" ")
    elif "children" in node:
      result.append(catch_md_paragraphs(node["children"]))

  return "".join(result)


def is_link_or_img(children):
  real_nodes = [n for n in children if n["type"] not in ("softbreak", "linebreak")]
  return len(real_nodes) == 1 and real_nodes[0]["type"] in ("link", "image")


def catch_paragraphs(nodes, excluded=False):
  paragraphs = []
  for node in nodes:
    node_type = node["type"]

    if node_type in ("table"):
      paragraphs.extend(  catch_paragraphs(node.get("children", []), excluded=True))
      continue

    if node_type == "paragraph":
      children = node.get("children", [])
      if not excluded and not is_link_or_img(children):
        text = catch_md_paragraphs(children).strip()
        if text:
          paragraphs.append(text)
      continue

    if "children" in node:
      paragraphs.extend(  catch_paragraphs(node["children"], excluded))

  return paragraphs
# ====================================

"""
# :::::::::: MAIN - OLD ::::::::::
async def main(json_data: dict, json_file: str, progress_bar, task_id, httpx_c: httpx.Client) -> None:

  # --- JSON SETTINGS ---
  creation_date = json_data["creation_date"]
  url = json_data["url"]
  voice = json_data["voice"]
  tags = json_data["labels"]
  custom_regex = json_data["regex"]
  translation = json_data["translate"]
  
  # --- LOAD WEB SITE AND GET HTML ---
  pure_html = await load_web_site(url, httpx_c)
  progress_bar.update(task_id, advance=10, description="[cyan]Downloading[/cyan] website")

  # --- MARKDOWN ---
  progress_bar.update(task_id, advance=10, description="[cyan]Extracting[/cyan] article")
  
  md_article, author, title, num_words, read_time = await asyncio.to_thread(get_markdown, pure_html)

  # --- APPLY CUSTOM REGEX ---
  if custom_regex and RULES_REGEX:
    progress_bar.update(task_id, advance=10, description="[cyan]Applying[/cyan] regex rules")

    md_article = apply_custom_regex(md_article)

  # --- TRANSLATE ---
  article_lang = langid.classify(title)[0].upper()
  if translation and article_lang != DEFAULT_LANGUAGE:
    progress_bar.update(task_id, advance=10, description="[cyan]Translating[/cyan]")
    md_article = await handle_translate(md_article, httpx_c)
    title = sanitize_text(await handle_translate(title, httpx_c))

  # --- EDGE TTS ---
  audio_file = None

  if voice and read_time < READING_THRESHOLD:
    progress_bar.update(task_id, advance=10, description="[cyan]Generating[/cyan] audio")

    audio_name = get_hash(title.encode("utf-8"))
    audio_file = f"![[{audio_name}.mp3]]"
    plain_text = convert_to_plain_text(md_article)

    await asyncio.to_thread(text_to_voice, plain_text, audio_name)

  # --- IMAGES ---

  progress_bar.update(task_id, advance=10, description="[cyan]Downloading[/cyan] images")

  wikilinks = get_wikilinks(md_article)

  md_article = await handle_images(md_article, wikilinks, httpx_c)

  # --- PDFS FILES ---

  progress_bar.update(task_id, advance=10, description="[cyan]Extracting[/cyan] pdfs")
  
  pdf_files = await get_pdfs(md_article, httpx_c)

  # --- BUILD TEMPLATE ---
  progress_bar.update(task_id, advance=10, description="[cyan]Building[/cyan] template")
  
  article_params = (
    creation_date,
    author,
    num_words,
    read_time,
    md_article,
    url,
    format_tags(tags),
    audio_file,
    pdf_files,
  )

  note_templated = build_template(*article_params)

  # --- SAVE FILE ---
  progress_bar.update(task_id, advance=10, description="[cyan]Saving[/cyan] file")

  save_to_file(sanitize_text(title), note_templated)

  # --- DEL ARTICLE DOWNLOADED ---
  delete_json(json_file)

  progress_bar.update(task_id, completed=100)
# ====================================
"""

# :::::::::: MAIN CLASS (First attempt) ::::::::::
class ArticleBuilder:
  def __init__(self, json_data: dict, json_file: Path, httpx_c: httpx.Client, progress_bar, task_id):
    
    # --- Metadata ---
    self.creation_date = json_data["creation_date"]
    self.url = json_data["url"]
    self.voice = json_data["voice"]
    self.tags = json_data["labels"]
    self.custom_regex = json_data["regex"]
    self.translation = json_data["translate"]
    self.pdfs = json_data["pdfs"]
    
    # --- Class args(?) ---
    self.json_file = json_file
    self.httpx_c = httpx_c
    self.progress_bar = progress_bar
    self.task_id = task_id

    # --- Instance attributes(?) ---
    self.md_article = None
    self.author = None
    self.title = None
    self.num_words = None
    self.read_time = None
    self.audio_file = None
    self.pdf_files = None

  # --- UPDATE PROGRESS ---
  def _progress(self, desc: str, advance: int = 10) -> None:
    self.progress_bar.update(self.task_id, advance=advance, description=f"[cyan]{desc}[/cyan]")

  # --- RUN ---
  async def run(self) -> None:
    
    # --- LOAD PAGE --- 
    pure_html = await self.load_web_site()
    self._progress("Downloading website...")
    
    if not pure_html:
      return
        
    # --- MARKDOWN ---
    self._progress("Extracting article...")
    self.md_article, self.author, self.title, self.num_words, self.read_time = await asyncio.to_thread(get_markdown, pure_html)
    
    # --- REGEX --- 
    if self.custom_regex and RULES_REGEX:
      self._progress("Applying regex rules...")
      self.md_article = apply_custom_regex(self.md_article)

    # --- TRANSLATE ---
    article_lang = langid.classify(self.title)[0].upper()
    if self.translation and article_lang != DEFAULT_LANGUAGE:
      self._progress("Translating...")
      self.md_article = await self.handle_translate(self.md_article)
      self.title = sanitize_text(await self.handle_translate(self.title))
    
    # --- AUDIO NOTE --- 
    if self.voice and self.read_time < READING_THRESHOLD:
      self._progress("Generating audio...")
      audio_name = get_hash(self.title.encode("utf-8"))
      self.audio_file = f"![[{audio_name}.mp3]]"
      plain_text = convert_to_plain_text(self.md_article)
      await asyncio.to_thread(text_to_voice, plain_text, audio_name)

    # --- IMAGES ---
    self._progress("Downloading images...")
    brackets = catch_brackets(self.md_article)
    urls = catch_bra_urls(brackets)
    
    self.md_article = await self.handle_images(brackets, urls)
    
    # --- PDFS ---
    if self.pdfs:
      self._progress("Extracting PDF...")
      self.pdf_files = await self.get_pdfs()

    # --- TEMPLATE ---
    self._progress("Building template...")
    note_templated = self.build_note()

    # --- SAVE ARTICLE ---
    self._progress("Saving file...")
    save_to_file(sanitize_text(self.title), note_templated)
    
    # --- DELETE JSON ---
    delete_json(self.json_file)
    self.progress_bar.update(self.task_id, completed=100)


  # :::::::::: CLASS - LOAD WEB PAGE ::::::::::
  @logger.catch
  async def load_web_site(self) -> str | None:
    response = await self.httpx_c.get(self.url, follow_redirects=True)
    return response.text if response.status_code == 200 else None
  # ====================================


  # :::::::::: CLASS - TRANSLATE ::::::::::
  async def handle_translate(self, text: str) -> str:
    mistune_inst = mistune.create_markdown(renderer=None)
    md_tree = mistune_inst(self.md_article)
    
    paragraphs =   catch_paragraphs(md_tree)
    org_chunks = [paraph for paraph in paragraphs if not paraph.startswith("!")]

    # --- Limit tasks ---
    semaphore = asyncio.Semaphore(4)
  
    async def rate_limit(chunk: str):
      async with semaphore:
        return await local_translate(chunk, self.httpx_c) 
  
    trans_tasks = [rate_limit(org_chunk) for org_chunk in org_chunks]
  
    trans_chunks: list = await asyncio.gather(*trans_tasks, return_exceptions=True)
  
    translated_map = dict(zip(org_chunks, trans_chunks))
    
    translated_article = text
    
    for original_chunk, translated_chunk in translated_map.items():
      translated_article = re.sub(re.escape(original_chunk), translated_chunk, translated_article, count=1)
  
    return translated_article
  # ====================================


  # ::::::::::: CLASS - HANDLE IMAGES ::::::::::
  @logger.catch
  async def handle_images(self, brackets: list, urls: list) -> str:
    # --- get type ---
    type_tasks = [content_type(url, self.httpx_c) for url in urls]
    files_type = await asyncio.gather(*type_tasks, return_exceptions=True)

    # --- filter valid images ---
    valid_imgs: list[tuple] = [(bracket, url) for bracket, url, ext in list(zip(brackets, urls, files_type)) if ext and "image" in ext]

    if not valid_imgs:
      return self.md_article

    # --- download images ---
    down_tasks = [download_files(url, self.httpx_c) for bracket, url in valid_imgs]
    md5_imgs = await asyncio.gather(*down_tasks, return_exceptions=True)

    mapping = [valid_imgs[i] + (md5_imgs[i],) for i in range(len(md5_imgs))]

    # ---- remove duplicates ---
    done = set()
    for ext_img, _, local_img in mapping:
      if ext_img in done:
        continue
      done.add(ext_img)
      count = self.md_article.count(ext_img)
      
      if count > 1:
          self.md_article = self.md_article.replace(ext_img, "", count - 1)
      
      md5_local = f"![[{local_img}]]"
      self.md_article = self.md_article.replace(ext_img, md5_local, 1)  # 

    return self.md_article
  # ====================================


  # :::::::::: CLASS - GET PDFS ::::::::::
  @logger.catch
  async def get_pdfs(self) -> str | None:
    
    # --- Find all urls ---
    all_urls = re.findall(URL_REGEX, self.md_article, re.MULTILINE)

    filetype_results = await asyncio.gather(
    *[get_file_bytes(url, self.httpx_c) for url in all_urls],
    return_exceptions=True
    )

    valid_pdf_urls = [url for result in filetype_results if result and not isinstance(result, Exception) for data, url in [result] if data and data.startswith(b"%PDF")]

    if not valid_pdf_urls:
      return None

    download_tasks = [download_files(url, self.httpx_c) for url in valid_pdf_urls]
    pdfs_md5_names = await asyncio.gather(*download_tasks, return_exceptions=True)

    pdf_sublist = []
        
    for ext_pdf, local_pdf in zip(valid_pdf_urls, pdfs_md5_names):
      pdf_filename = ext_pdf.split("/")[-1]
      pdf_name_formated = re.sub(r"-|_|%\d{2}|(?<=\.pdf).+$", " ", pdf_filename).capitalize()
      pdf_sublist.append(f"\t - [{pdf_name_formated}]({local_pdf})\n")
          
    header = "- Papers cited in this article:" + "\n"
    stylized_sublist = header + "".join(pdf_sublist)

    return stylized_sublist
      
  # --- Build Note ----
  def build_note(self) -> str:
    article_params = (
      self.creation_date, self.author, self.num_words, self.read_time,
      self.md_article, self.url, format_tags(self.tags),
      self.audio_file, self.pdf_files,
    )
    
    return build_template(*article_params)
# ====================================


# :::::::::: RUN SYNC ::::::::::
async def run_sync(json_data: dict, json_file: str, semaphore, progress_bar, httpx_c: httpx.Client) -> None:
  async with semaphore:
    try:
      
      task_id = progress_bar.add_task("Starting...", total=100, filename=json_data["url"])
      processor = ArticleBuilder(json_data, json_file, httpx_c, progress_bar, task_id)
      await processor.run()
      progress_bar.update(task_id, completed=100, description="[green]✓ Done[/green]")
    
    except Exception as e:
      logger.exception("run sync")
      progress_bar.update(task_id, description=f"[red]ERROR: [/red] {e}")
# ====================================


# ::::::::::QUEUE ARTICLES ::::::::::
async def handle_sync() -> None:
  articles_json = [(json.loads(f.read_text()), f) for f in list(OFFLINE_DIR.glob("*.json"))]
  
  if not articles_json:
    show_message("Nothing to sync")
    return
  
  semaphore = asyncio.Semaphore(4)
  
  custom_bar = r"{task.percentage}% - {task.description} ([yellow]{task.fields[filename]}[/yellow])"
  
  try:
    
    with Progress(SpinnerColumn(), TextColumn(custom_bar), refresh_per_second=5) as progress_bar:
      async with httpx.AsyncClient(headers={"User-Agent": USERAGENT}) as httpx_c:
        await asyncio.gather(*(run_sync(json_data[0], json_data[1], semaphore, progress_bar, httpx_c) for json_data in articles_json), return_exceptions=True)
        console.print("[bold green]✓ Sync Finished[/bold green]")
  
  except Exception:
    console.print("[bold red]Sync Failed[/bold red]")
# ====================================


if __name__ == "__main__":
  main_cli()
  
