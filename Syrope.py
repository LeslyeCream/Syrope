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
import aiohttp
import edge_tts
import requests
import validators
import questionary
from rich.table import Table
from bs4 import BeautifulSoup
from langdetect import detect
from readability import Document
from rich.console import Console
from rich.traceback import install
from markdownify import markdownify as md
from rich.progress import Progress, SpinnerColumn, TextColumn
from markdown_plain_text.extention import convert_to_plain_text


# ::::: TO-DO ::::::
# ✔️ Add Translate
# ✔️ @click
# Add Download PDF' articles
# ✔️ Add MS TTS EDGE
# ✔️ Check settings / paths
# Handle errors
# ✔️ Tags function
# replace build_template to kwargs
# ✔️ Add detailed information during sync
# ✔️ Only create audio if the article length is < n
# ====================================


# --- Trackback handler ---
install(show_locals=True)


# ::::: LOAD SETTINGS :::::
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

# --- CHECK FOLDERS ---
for folder_path in [OFFLINE_DIR, ARTICLES_DIR, ATTACHMENTS_DIR, ARTICLES_SYNCED_DIR]:
  folder_path.mkdir(parents=True, exist_ok=True)
# ====================================


# ::::: GET JSON DATA :::::
def get_json_data(json_file: Path) -> str:
  with open(json_file, "r", encoding="utf-8") as f:
    json_fields = json.load(f)
    return (
      json_fields["creation_date"],
      json_fields["url"],
      json_fields["voice"],
      json_fields["labels"],
      json_fields["regex"],
      json_fields["translate"],
    )
# ====================================


# ::::: TUI - MAIN :::::
def main_tui() -> None:
  action = questionary.select(
    "What do you want to do?",
    choices=["1. Sync articles", "2. View saved articles", "3. Add URL", "4. Exit"],
  ).ask()

  match action:
    case "1. Sync articles":
      asyncio.run(start_sync())
    case "2. View saved articles":
      view_saved_articles()
    case "3. Add URL":
      menu_add_url()
    case "4. Exit":
      sys.exit()
# ====================================


# ::::: TUI - ADD URL :::::
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


# ::::: TUI - VIEW SAVED LINKS :::::
def view_saved_articles() -> None:

  # --- Get article list ---
  saved_links = []
  json_files = list(OFFLINE_DIR.glob("*.json"))

  if len(json_files) < 1:
    show_message("No items saved")

  else:
    saved_links = [
      (data[1], data[0])
      for json_f in json_files
      if (data := get_json_data(json_f))
      ]

    # --- Show Table ---
    table = Table(title="Links saved", show_lines=True)
    table.add_column("Url", style="cyan")
    table.add_column("Created", style="yellow")

    for link, creation_date in saved_links:
      table.add_row(link, str(creation_date))

    console = Console()

    console.print(table)

    # --- Actions ---
    action = questionary.select("Choose an option:", choices=["Back", "Exit"]).ask()

    if action == "Back":
      main_tui()

    elif action == "Exit":
      sys.exit()
# ====================================


# ::::: GET URLS  :::::
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

  if input_file:
    save_multiples_url(input_file, params)

  # --- Save single url ---
  elif params.get("url"):
    url = params.get("url")
    save_single_url(url, params)

  # --- Start sync ---
  elif params.get("sync"):
    asyncio.run(start_sync())

  # --- TUI ---
  else:
    main_tui()
# ====================================


# ::::: SAVE MULTIPLE URLS FROM CLI :::::
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


# ::::: SAVE ONE URL :::::
def save_single_url(url: str, params: dict) -> None:
  if not validators.url(url):
    show_message("Invalid url")
    return

  creation_date = {"creation_date": dt.now().strftime("%Y-%m-%d %H:%M")}
  params.update(creation_date)
  params["url"] = remove_tracking_param(url)
  save_changes_on_file(params)
  show_message("Url saved!")
  main_tui()
# ====================================


# :::::REMOVE TRACKING PARAMETERS :::::
def remove_tracking_param(url: str) -> str:
  tracking_regex = r"\?utm.+"
  url = re.sub(tracking_regex, "", url)
  return url
# ====================================


# ::::: SAVE PARAMETERS IN JSON :::::
def save_changes_on_file(params: dict) -> None:
  url = params.get("url").encode("utf-8")
  json_name = get_hash(url)
  full_path = OFFLINE_DIR.joinpath(f"{json_name}.json")

  with open(full_path, "w", encoding="utf-8") as f:
    json.dump(params, f, ensure_ascii=False, indent=4)
# ====================================


# ::::: GET WEB PAGE :::::
def load_web_site(url: str) -> str:
  try:
    response = requests.get(
      url, headers={"User-Agent": USERAGENT}
    )
    
    return str(BeautifulSoup(response.content, 'html.parser'))

  except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
    show_message(str(e))
# ====================================


# ::::: EXTRACT ARTICLE FROM HTML :::::
def readability_mode(html: str) -> Document:
  article_obj = Document(html)
  return article_obj
# ====================================


# ::::: GET HASH MD5 :::::
def get_hash(text: str) -> str:
  hash_md5 = hashlib.md5(text).hexdigest()
  return hash_md5
# ====================================


# ::::: DELETE DUPLICATE LINKS (IMG) :::::
def del_dupli_links(article: str, wiki_urls: list) -> str:
  for img in wiki_urls:
    count = article.count(img)
    if count > 1:
      article = re.sub(re.escape(img), "", article, count=count - 1)
  
  return article
# ====================================


# ::::: DOWNLOAD AND SAVE IMAGE :::::
async def check_and_download_img(aiohttp_request, url_img: str) -> str:
  try:
    async with aiohttp_request.get(url_img) as current_img:
      
      if current_img.status == 200 and 'image' in current_img.headers.get('Content-Type', ''):

        # --- Get image file ---
        img_obj = await current_img.read()
  
        # --- Get info image ---
        img_extension = Path(urlparse(url_img).path).suffix.lower()
        md5_img_name = get_hash(img_obj) + img_extension
        full_path = ATTACHMENTS_DIR.joinpath(md5_img_name)
  
        # --- Save image ---
        with open(full_path, "wb") as img:
          img.write(img_obj)
  
        return md5_img_name

  except Exception:  
    return f"![]({url_img})"
# ====================================


# ::::: GET WIKILINKS :::::
def get_wikilinks(md_text: str) -> list:
  regex_wiki = r"!\[.*?\]\(.*?\)"
  wikilinks = re.findall(regex_wiki, md_text, re.MULTILINE)
  return wikilinks
# ====================================


# ::::: GET URL IMGS :::::
def get_url_imgs(wikilinks: list) -> list:
  img_regex = r"https://[^\s\)\]]+"
  
  if wikilinks:
    urls_img = [
    img_link.group(0)
    for wiki in wikilinks
    if (img_link := re.search(img_regex, wiki))
    ]
    
    return urls_img
# ====================================
 

# ::::: BATCH DOWNLOAD :::::
async def batch_img_download(md_article: str, md_wikilinks: list, url_imgs: list) -> str:
  if md_wikilinks and url_imgs:
    
    async with aiohttp.ClientSession() as aiohttp_request:
      tasks = [check_and_download_img(aiohttp_request, url) for url in url_imgs]
      img_objects: list = await asyncio.gather(*tasks, return_exceptions=True)
  
      for ext_img, local_img in list(zip(md_wikilinks, img_objects)):
        if local_img and isinstance(local_img, str): #first try with isinstance instead ==
          local_img = f"![[{local_img}]]"
          article_w_imgs = re.sub(re.escape(ext_img), local_img, md_article)
      
      new_line_pattern = r"(?<=\))(!\[\])(?=\()"
      return re.sub(new_line_pattern, r"\n\n\1", article_w_imgs)
  
  return md_article
  # ====================================


# ::::: SATANIZE INLINE TITLE :::::
def satanize_text(title: str) -> str:
  pattern = re.compile(r"[^\w\s\-.,()&!;@]")
  clean_title: str = pattern.sub("", title)
  return clean_title
# ====================================


# ::::: CLOUDFARE AI TRANSLATE :::::
async def cloudfare_translate(txt_translate: str, aiohttp_request) -> str:
  prompt = f"""
  You're translator. Your only response must be the exact translation of the 
  user's text into the {DEFAULT_LANGUAGE} language, without any explanation, 
  greeting, preface, or extra text. Just the translation.
  """

  headers: dict = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
  }
  body: dict = {
    "messages": [
      {"role": "system", "content": prompt},
      {"role": "user", "content": txt_translate},
    ]
  }

  try:
    async with aiohttp_request.post(
      CLOUDFARE_URL, headers=headers, json=body
    ) as resp:
      answer_content = await resp.json()
      return answer_content["result"]["response"]

  except Exception:
    return txt_translate
# ===================================


# ::::: LINGVA SERVICE :::::
async def lingva_translate(txt_to_translate: str, aiohttp_request) -> str:
  try:
    to_translate = str(quote(txt_to_translate))
    lingva_url = "https://translate.plausibility.cloud/api/v1/en/es/"

    async with aiohttp_request.get(lingva_url + to_translate) as resp:
      answer_content = await resp.json()

      if answer_content["translation"] != "Not Found":
        return answer_content["translation"]
      return txt_to_translate

  except Exception:
    return txt_to_translate
# ====================================


# ::::: TRANSLATE :::::
async def translate(md_article) -> str:
  md_styles_pattern = r"^[!\|\[$$-]"

  # --- Split in paragraphs ---
  org_chunks = [
    chunk
    for chunk in md_article.split("\n\n")
    if not re.match(md_styles_pattern, chunk)
  ]

  # --- Limit tasks ---
  semaphore = asyncio.Semaphore(3)

  # --- batch translate --
  async def rate_limit(chunk, aiohttp_request):
    async with semaphore:
      return await cloudfare_translate(chunk, aiohttp_request)

  async with aiohttp.ClientSession() as aiohttp_request:
    trans_tasks = [
      rate_limit(org_chunk, aiohttp_request) for org_chunk in org_chunks
    ]
    
    trans_chunks: list = await asyncio.gather(*trans_tasks, return_exceptions=True)

    translated_map = dict(zip(org_chunks, trans_chunks))

    for original_chunk, translated_chunk in translated_map.items():
      md_article = md_article.replace(original_chunk, translated_chunk)

    return md_article
# ====================================


# ::::: REGEX RULES (CONTENT) :::::
def content_rules(content: str) -> str:
  for rule in RULES_REGEX:
    content = re.sub(rule["Pattern"], rule["Replacement"], content)
  return content
# ====================================


# ::::: SAVE TO FILE :::::
def save_to_file(name_file: str, content: str) -> None:
  out_path = ARTICLES_DIR.joinpath(f"{name_file}.md")
  with open(out_path, "w", encoding="utf-8") as f:
    f.write(content)
# ====================================


# ::::: FORMAT TAGS :::::
def format_tags(tags: str) -> str:
  if not tags:
    return None
  else:
    x_tags = tags.split(",")
    return "\n" + "".join(f"  - {i}\n" for i in x_tags)
# ====================================


# ::::: BUILD TEMPLATE :::::
def build_template(*args) -> str:
  creation_date, author, num_words, read_time, full_article, url, tags, audio, cited_pdfs = args
  
  metadata = {
    "%CREATIONDATE": creation_date,
    "%AUTHOR": author,
    "%WORDS": num_words,
    "%READTIME": read_time,
    "%ARTICLE": full_article,
    "%URL": url,
    "%TAGS": tags,
    "%AUDIO": audio,
    "%PDF": cited_pdfs
  }

   
  missing_values = (key for key, value in metadata.items() if not value)
  

  with open(TEMPLATE, "r", encoding="utf-8") as f:
    template = f.read()
  
  if missing_values:
    template = del_properties(template, missing_values)
  
  for var, value in filter(lambda item: item[0] not in missing_values, metadata.items()):
    if var in template:
      template = template.replace(str(var), str(value))

  return template
# ====================================


# ::::: DEL UNUSED PROPERTIES :::::
def del_properties(text: str, properties: list):
  props_to_del = "|".join(properties)

  valid_lines = [line for line in text.split("\n") if not re.search(props_to_del, line)]
  cleaned_txt = '\n'.join(valid_lines)
  
  return cleaned_txt
# ====================================


# ::::: DELETE / MOVE JSON FINISHED :::::
def delete_json(json_file: Path) -> None:
  done_path = ARTICLES_SYNCED_DIR.joinpath(json_file.name)

  if DEL_SYNCED_ARTICLES:
    json_file.unlink(missing_ok=True)
  else:
    json_file.rename(done_path)
# ====================================


# ::::: SHOW MESSAGES :::::
def show_message(msg: str, custom_style="Bold") -> None:
  console = Console()
  console.print(f"{msg}", style=custom_style)
# ====================================


# ::::: MICROSOFT EDGE TTS :::::
def text_to_voice(text: str, name_file: str) -> None:
  output_audio_file = ATTACHMENTS_DIR.joinpath(f"{name_file}.mp3")
  try:
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    communicate.save_sync(output_audio_file)
  except Exception as e:
    show_message(e)
# ====================================


# ::::: BUILD SUBLIST RESOURCES :::::
def build_sublist_resources(pdf: str):
  pdf_filename = pdf.split("/")[-1]
  format_name = (
    re.sub(r"-|_", " ", pdf_filename) if not pdf_filename[0].isdigit else pdf_filename
  )
  return f"\t - [{format_name}]({pdf})\n"
# ====================================


# ::::: GROUP ARTICLE RESOURCES :::::
def get_article_resources(text: str) -> str:
  pdf_regex = r"https?://(?:www\.)?[^\s/$.?#].[^\s]*\.pdf(?:\?[^\s]*)?(?:#[^\s]*)?"
  
  valid_pdfs = re.findall(pdf_regex, text, re.MULTILINE)
  
  if valid_pdfs:
    pdf_sublist = [build_sublist_resources(pdf) for pdf in valid_pdfs]
    header = "- Papers cited in this article:" + "\n"
    stylized_pdfs = header + "".join(pdf_sublist)
    
    return stylized_pdfs
# ====================================


# ::::: GET AUTHOR INFO :::::
def get_author_info(author: str, html: str) -> None:
  if not author.startswith("["):
    return author
  
  else:
    author_attr = BeautifulSoup(html, 'html.parser').find('meta', attrs={'name': 'author'})
    
    if author_attr:
      author = author_attr.get('content', '').strip()
      return author 
# ====================================

# ::::: MAIN :::::
async def main(json_file, progress, task_id) -> None:

  # --- JSON SETTINGS ---
  creation_date, url, voice, tags, custom_regex, translation = get_json_data(
    json_file
  )

  # --- HTML ---
  progress.update(task_id, advance=5)
  progress.update(task_id, description="[cyan]Downloading[/cyan] website")

  raw_html = load_web_site(url)
  
  
  if not raw_html:
    show_message(f"Error downloading {url}")

  else:
    progress.update(task_id, advance=5)
    progress.update(task_id, description="[cyan]Extracting[/cyan] article")

    readability_article = readability_mode(raw_html)
    summary_article = readability_article.summary(keep_all_images=True)


    # --- MARKDOWN ---
    progress.update(task_id, advance=5)
    progress.update(task_id, description="[cyan]Markdowning[/cyan] website")

    md_article = md(summary_article)

    

    # --- ARTICLE METADATA ---
    author = get_author_info(readability_article.author(), raw_html)
    title = satanize_text(readability_article.title())
    num_words = len(md_article.split(" "))
    read_time = num_words // WPM


    # --- APPLY REGEX CONTENT RULES ---
    if custom_regex:
      progress.update(task_id, advance=10)
      progress.update(task_id, description="[cyan]Applying[/cyan] regex rules")

      md_article = content_rules(md_article)


    # --- TRANSLATE ---
    if translation and detect(md_article) != DEFAULT_LANGUAGE:
      progress.update(task_id, advance=20)
      progress.update(task_id, description="[cyan]Translating[/cyan] article")

      md_article = await translate(md_article)
      title = satanize_text(await translate(title))


    # --- EDGE TTS ---
    audio_file = None 

    if voice and read_time < READING_THRESHOLD:
      progress.update(task_id, advance=20)
      progress.update(task_id, description="[cyan]Generating[/cyan] audio")

      audio_name = get_hash(title.encode("utf-8"))
      audio_file = f"![[{audio_name}.mp3]]"
      plain_text = convert_to_plain_text(md_article)

      await asyncio.to_thread(text_to_voice, plain_text, audio_file)


    # --- IMAGES ---
    progress.update(task_id, advance=20)
    progress.update(task_id, description="[cyan]Downloading[/cyan] images")
    
    wiki_urls = get_wikilinks(md_article)
    url_imgs = get_url_imgs(wiki_urls)
    
    article_dedup = del_dupli_links(md_article, wiki_urls)
    
    full_article = await batch_img_download(article_dedup, wiki_urls, url_imgs)
    
    
    # --- GROUP RESOURCES ---
    progress.update(task_id, advance=5)
    progress.update(task_id, description="[cyan]Extracting[/cyan] resources")

    cited_pdfs = get_article_resources(md_article)


    # --- BUILD TEMPLATE ---
    progress.update(task_id, advance=5)
    progress.update(task_id, description="[cyan]Building[/cyan] template")

    article_params = (
      creation_date,
      author,
      num_words,
      f"{read_time} minutes",
      full_article,
      url,
      format_tags(tags),
      audio_file,
      cited_pdfs,
    )

    note_templated = build_template(*article_params)


    # --- SAVE FILE ---
    save_to_file(title, note_templated)

    progress.update(task_id, advance=5)
    progress.update(task_id, description="[cyan]Saving[/cyan] note")


    # --- DEL ARTICLE DOWNLOADED ---
    #delete_json(json_file)
    
    progress.update(task_id, completed=100)
# ====================================


# :::::QUEUE ARTICLES :::::
async def start_sync() -> None:
  json_files = list(OFFLINE_DIR.glob("*.json"))

  if not json_files:
    show_message("Nothing to sync")
    return

  # --- Set limit tasks ---
  semaphore = asyncio.Semaphore(3)

  # --- Progress Bar ---
  custom_values = r"{task.percentage}% - {task.description} ([yellow]{task.fields[filename]}[/yellow])"

  with Progress(
    SpinnerColumn(), TextColumn(custom_values), transient=True
  ) as progress:

    # --- Download task ---
    async def limited_process(file_path):
      task_id = progress.add_task("", total=100, filename=file_path.name)

      async with semaphore:
        await main(file_path, progress, task_id)
        progress.stop_task(task_id)
        progress.update(task_id, description="[green]✓ Done[/green]")

    await asyncio.gather(*(limited_process(f) for f in json_files))

  show_message("All files synced!", custom_style="Bold green")
# ====================================


if __name__ == "__main__":
  main_cli()
  