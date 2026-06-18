from urllib.parse import quote, urlparse
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
import langid
import edge_tts
import validators
import questionary
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

# --- CHECK FOLDERS ---
for folder_path in [OFFLINE_DIR, ARTICLES_DIR, ATTACHMENTS_DIR, ARTICLES_SYNCED_DIR]:
  folder_path.mkdir(parents=True, exist_ok=True)
# ====================================


# --- Trackback handler ---
install(show_locals=True)
console = Console()
langid.set_languages(TRANSLATE_LANGUAGES)


# :::::::::: TUI - MAIN ::::::::::
def main_tui() -> None:
  action = questionary.select(
    "What do you want to do?",
    choices=["1. Sync articles", "2. View saved articles", "3. Add URL", "4. Exit"],
  ).ask()

  match action:
    case "1. Sync articles":
      asyncio.run(handle_sync())
      main_tui()
    case "2. View saved articles":
      view_saved_articles()
      main_tui()
    case "3. Add URL":
      menu_add_url()
      main_tui()
    case "4. Exit":
      sys.exit()
# ====================================


# :::::::::: TUI - ADD URL ::::::::::
def menu_add_url() -> None:
  option = questionary.select(
    "How do you want to add it?",
    choices=["1. Single URL", "2. From file", "3. Back"],
  ).ask()

  match option:
    case "1. Single URL":
      save_single_url(input("Entered the url: "), PARAM_DEFAULTS)
    case "2. From file":
      save_multiples_url(input("Entered the file path: "), PARAM_DEFAULTS)
    case "3. Back":
      main_tui()
# ====================================


# :::::::::: JSON DATA ::::::::::
def get_json_data(json_file: json) -> str:
  with open(json_file, "r", encoding="utf-8") as f:
    json_content = json.load(f)
    return json_content

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
@click.option("-v", "--voice", is_flag=True, help="Listen to article")
@click.option("-r", "--regex", is_flag=True, help="Apply custom regular expressions")
@click.option("-i", "--input-file", type=str, help="Save URLs from an external file")
@click.option("-s", "--sync", is_flag=True, help="Start sync")
def main_cli(**kwargs) -> None:
  params = kwargs
  
  # --- Save urls from file ---
  input_file = params.get("input_file")
  # --- TUI ---
  cli_set = params.get("input_file"), params.get("url"), params.get("sync")
  if not any(cli_set):
    main_tui()


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
    valid_urls = [
      remove_tracking_param(url.strip())
      for url in content
      if validators.url(url.strip())
    ]

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
  tracking_regex = r"[?&]utm[^&]*"
  url = re.sub(tracking_regex, "", url)
  return url
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
async def load_web_site(url: str, httpx_c) -> str:
  try:
    response = await httpx_c.get(url, follow_redirects=True)
    if response.status_code == 200:
      return response.text
    
    raise Exception(f"loading website {response.status_code}")
  
  except Exception as e:
    raise Exception(e)
# ====================================


# :::::::::: GET HASH MD5 ::::::::::
def get_hash(text: bytes) -> str:
  hash_md5 = hashlib.md5(text).hexdigest()
  return hash_md5
# ====================================


# :::::::::: DOWNLOAD AND SAVE IMAGE ::::::::::
async def download_files(url: str, httpx_c) -> str:
  try:
    response = await httpx_c.get(url, follow_redirects=True)
    content_type = response.headers.get('Content-Type', '')
    if response.status_code == 200:
      file_obj =  response.content

      # --- Get info image ---
      file_extension = "." + content_type.split(";")[0].split("/")[1]
      md5_filename =get_hash(file_obj) + file_extension
      dst_path = ATTACHMENTS_DIR.joinpath(md5_filename)

      # --- Save image ---
      with open(dst_path, "wb") as file:
        file.write(file_obj)

      return md5_filename

    else:
      return None

  except Exception:  
    return None
# ====================================


# :::::::::: CONTENT TYPE ::::::::::
async def content_type(url: str, httpx_c) -> str | None:
  try:
    response = await httpx_c.head(url, follow_redirects=True)
    return response.headers.get("content-type")

  except Exception:
    return None
# ====================================


# :::::::::: GET WIKILINKS ::::::::::
def get_wikilinks(md_article: str):
  regex_brackets = r"^[!\[].*\)$"
  urls_regex = r"https?://[^\s)\"']+"

  if brackets := re.findall(regex_brackets, md_article, re.MULTILINE):
    urls = [m.group(0) for url in brackets if (m := re.search(urls_regex, url))]
    return brackets, urls

  return [], []
# ====================================


# :::::::::: BATCH DOWNLOAD ::::::::::
async def handle_images(md_article: str, wikilinks: tuple,  httpx_c) -> str:
  brackets, urls = wikilinks

  try:
    type_tasks = [content_type(url, httpx_c) for url in urls]
    file_type = await asyncio.gather(*type_tasks, return_exceptions=True)

    results = list(zip(brackets, urls, file_type))

    valid_urls_img = [(bracket, url) for bracket, url, ext in results if ext and "image" in ext]

    if not valid_urls_img:
      return md_article

    down_tasks = [download_files(url, httpx_c) for bracket, url in valid_urls_img]
    md5_obj = await asyncio.gather(*down_tasks, return_exceptions=True)

    brackets, urls = zip(*valid_urls_img)
    mapping = list(zip(brackets, urls, md5_obj))

    for ext_img, _, local_img in mapping:
    
      count = md_article.count(ext_img)
    
      if count > 1:
        md_article = re.sub(re.escape(ext_img), "", md_article, count=count - 1)
  
      local_img = f"![[{local_img}]]"
  
      md_article = re.sub(re.escape(ext_img), local_img, md_article)
  
    return md_article
  
  except Exception as e:
    show_message(e)
# ====================================


# :::::::::: SANITIZE INLINE TITLE ::::::::::
def sanitize_text(title: str) -> str:
  pattern = re.compile(r'[*"\\/<>:|?¿]')
  clean_title: str = pattern.sub("", title)
  
  return clean_title
# ====================================


# :::::::::: CLOUDFLARE AI TRANSLATE ::::::::::
async def cloudfare_translate(txt_translate: str, httpx_c) -> str:
  prompt = f"""Only the answer. Translate "{txt_translate}" to {DEFAULT_LANGUAGE} language."""
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
    if response.status_code == 200:
      answer_content = response.json()
      return answer_content["result"]["response"]
    else:
      return txt_translate

  except Exception:
    return txt_translate
# ===================================


# :::::::::: TRANSLATE ::::::::::
async def handle_translate(md_article, httpx_c) -> str:
  md_styles_pattern = r"^[!\|\[$-]"

  # --- Split in paragraphs ---

  org_chunks = [
    chunk
    for chunk in md_article.splitlines()
    if chunk and not re.match(md_styles_pattern, chunk)
  ]


  # --- Limit tasks ---
  semaphore = asyncio.Semaphore(4)

  async def rate_limit(chunk):
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


# :::::::::: REGEX RULES (CONTENT) ::::::::::
def apply_custom_regex(content: str) -> str:
  for rule in RULES_REGEX:
    content = re.sub(rule["Pattern"], rule["Replacement"], content, flags=re.MULTILINE | re.DOTALL)
# ====================================


# :::::::::: SAVE TO FILE ::::::::::
def save_to_file(name_file: str, content: str) -> None:
  out_path = ARTICLES_DIR.joinpath(f"{name_file}.md")
  with open(out_path, "w", encoding="utf-8") as f:
    f.write(content)
# ====================================


# :::::::::: FORMAT TAGS ::::::::::
def format_tags(tags: str) -> str:
  if not tags:
    return None
  
  else:
    x_tags = tags.split(",")
    return "\n" + "".join(f"  - {i}\n" for i in x_tags)
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
def del_properties(text: str, properties: iter):
  props_to_del = "|".join(properties)

  valid_lines = [line for line in text.split("\n") if not re.search(props_to_del, line)]
  cleaned_txt = '\n'.join(valid_lines)
  
  return cleaned_txt
# ====================================


# :::::::::: DELETE / MOVE JSON FINISHED ::::::::::
def delete_json(json_file: Path) -> None:
  done_path = ARTICLES_SYNCED_DIR.joinpath(json_file.name)

  if DEL_SYNCED_ARTICLES:
    json_file.unlink(missing_ok=True)
  else:
    json_file.rename(done_path)
# ====================================


# :::::::::: SHOW MESSAGES ::::::::::
def show_message(msg: str, custom_style="Bold") -> None:
  console.print(f"{msg}", style=custom_style)
# ====================================


# :::::::::: MICROSOFT EDGE TTS ::::::::::
def text_to_voice(text: str, name_file: str) -> None:
  output_audio_file = ATTACHMENTS_DIR.joinpath(f"{name_file}.mp3")
  try:
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    communicate.save_sync(output_audio_file)
  except Exception as e:
    show_message(e)
# ====================================


# :::::::::: GET PDFS ::::::::::
async def get_pdfs(md_article: str, httpx_c) -> str:
  try:
    # --- Find all urls ---
    all_urls = re.findall(URL_REGEX, md_article, re.MULTILINE)

    filetype_results = await asyncio.gather(
    *[get_file_bytes(url, httpx_c) for url in all_urls],
    return_exceptions=True
    )

    valid_pdf_urls = [
    url
    for result in filetype_results
    if result and not isinstance(result, Exception)
    for data, url in [result]
    if data and data.startswith(b"%PDF")
]

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
  except Exception as e:
    console.print(f"pdf {e}")
# ====================================


# :::::::::: GET FILE TYPE ::::::::::
async def get_file_bytes(url: str, httpx_c) -> tuple | None:
  try:
    response = await httpx_c.get(url, headers={"Range": "bytes=0-32"}, follow_redirects=True)
    if not response.status_code == 206:
      return ""
    data = response.content
    return data, url
  
  except Exception as e:
    console.print(f" get file {e}")
# ====================================



# :::::::::: MARKDOWN AND METADATA ::::::::::
def get_markdown(pure_html: str) -> tuple:
  readbility_obj = Document(pure_html)
  
  md_article = md(readbility_obj.summary(keep_all_images=True))

  author = readbility_obj.author() if not readbility_obj.author().startswith("[") else None
  
  title = sanitize_text(readbility_obj.title())

  num_words = len(md_article.split())
  
  read_time = num_words // WPM
  
  """
  defud_obj = defuddle(pure_html, url=url)
  md_article = defud_obj.markdown
  publi_date = defud_obj.published
  author = defud_obj.author
  title = sanitize_text(defud_obj.title)
  num_words = len(md_article.split(" "))
  read_time = num_words // WPM
  """
  return md_article, author, title, num_words, read_time
# ====================================

# :::::::::: MAIN ::::::::::
async def main(json_data: dict, json_file: str, progress_bar, task_id, httpx_c) -> None:

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

  # --- APPLY REGEX CONTENT RULES ---
  if custom_regex and RULES_REGEX:
    progress_bar.update(task_id, advance=10, description="[cyan]Applying[/cyan] regex rules")

    md_article = apply_custom_regex(md_article)

  # --- TRANSLATE ---
  progress_bar.update(task_id, advance=10, description="[cyan]Translating[/cyan]")
  
  article_lang = langid.classify(title)[0].upper()
  if translation and article_lang != DEFAULT_LANGUAGE:
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


  
# :::::::::: START SYNC ::::::::::
async def run_sync(json_data: dict, json_file, semaphore, progress_bar, httpx_c):
  async with semaphore:
    try:
      task_id = progress_bar.add_task("Procesando...", total=100, filename=json_data["url"])
      await main(json_data, json_file, progress_bar, task_id, httpx_c)
      progress_bar.update(task_id, completed=100, description="[green]✓ Done[/green]")
    except Exception as e: 
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
  
  with Progress(SpinnerColumn(), TextColumn(custom_bar), refresh_per_second=5) as progress_bar:
    async with httpx.AsyncClient(headers={"User-Agent": USERAGENT}) as httpx_c:
      await asyncio.gather(*(run_sync(json_data[0], json_data[1], semaphore, progress_bar, httpx_c) for json_data in articles_json), return_exceptions=True)
  
  console.print("[bold green]✓ Sync Finished[/bold green]")
# ====================================


if __name__ == "__main__":
  main_cli()


