from concurrent.futures import ThreadPoolExecutor, as_completed
from langdetect import detect, DetectorFactory
from markdownify import markdownify as md
from Settings import load_settings
from datetime import datetime as dt
from urllib.parse import urlparse
from readability import Document
from urllib.parse import quote
from pathlib import Path
from icecream import ic
from loguru import logger
import validators
import threading
import edge_tts
import requests
import hashlib
import click
import yaml
import json
import time
import re


import aiohttp
from aiohttp import ClientError
import asyncio


file_lock = threading.Lock()


# ::::: TO-DO ::::::
# ✔️ Add Translate
# Add @click 
# add Download PDF' articles
# ✔️ Add MS TTS EDGE
# Check settings / paths 
# Handle errors
# Add tags function
# replace build_template to kwargs


# ::::: DECORATOR :::::
from functools import wraps
import time
def tempus(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()  # más preciso que time.time()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"Finalizado en: {end - start:.5f} s")
        return result
    return wrapper
# ====================================

# ::::: LOAD SETTINGS :::::
with open(Path(__file__).parent.joinpath("Settings.yaml"), "r") as file:
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
  WPM = settings["OTHERS"]["WPM"]
  DEL_SYNCED_ARTICLES = settings["OTHERS"]["DEL_SYNCED_ARTICLES"]
  USERAGENT = settings["OTHERS"]["USERAGENT"]
  TTS_VOICE = settings["OTHERS"]["TTS_VOICE"]
  
  # API
  CLOUDFARE_URL = settings["API"]["CLOUDFARE_URL"]
  API_KEY = settings["API"]["API_KEY"]
  
  # REGEX
  RULES_REGEX = settings["REGEX"]
# ====================================


# ::::: CHECK DIR EXISTS :::::
def validate_dir_paths() -> None:
  folders_to_check = [OFFLINE_DIR, ARTICLES_DIR, ATTACHMENTS_DIR, ARTICLES_SYNCED_DIR]
  for folder in folders_to_check:
    if not folder.exists():
      folder.mkdir()
# ====================================


# ::::: GET JSON DATA :::::
def get_json_data(json_file):
  with open(json_file, "r") as f:
    return json.load(f)
# ====================================


# ::::: GET URLS  :::::
@click.command()
@click.argument("url", required= False)
@click.option("-l", "--labels", type=str, help="etiquetas para articulos")
@click.option("-t", "--translate", is_flag=True, help="Traducir articulo")
@click.option("-v", "--voice", is_flag=True, help="nota de voz")
@click.option("-r", "--regex", is_flag=True, help="aplicar reglas regex")
@click.option("-i", "--input-file", type=str, help="Procesar urls desde archivo")
@click.option("-s", "--sync", is_flag=True, help="Procesar urls desde archivo")
def get_urls(**kwargs):
  params = kwargs
  
  # --- add creation date --- 
  creation_date = {"creation_date": dt.now().strftime('%Y-%m-%d %H:%M')}
  params.update(creation_date)
  
  # --- save urls from file
  input_file = params.get("input_file")
  
  if input_file:
    urls = load_from_file(input_file)
    for url in urls:
      url_params = params.copy()
      url_params["url"] = url
      del url_params["input_file"]
      save_change_to_file(url_params)
    print(f"{len(urls)} urls saved!")

  # --- save single url ---
  elif params.get("url"):
    if validators.url(params.get("url")):
      save_change_to_file(params)
      print("url saved!")
    else:
      print("url invalid")
  else:
    print("None url or file selected")
    asyncio.run(start_sync())

    
  if params.get("sync"):
    asyncio.run(start_sync())
# ====================================


# ::::: SAVE URL/S IN JSON :::::
def save_change_to_file(params: dict):
  url = params.get("url").encode("utf-8")
  json_name = get_hash(url)
  full_path = OFFLINE_DIR.joinpath(f"{json_name}.json")
  with open(full_path, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=4)
# ====================================


# ::::: LOAD URLS FROM FILE :::::
def load_from_file(input_file: str):
  with open(input_file, "r") as f:
    content = f.readlines()
    valid_urls = [url.strip() for url in content if validators.url(url.strip())]
  return valid_urls
# ====================================



"""
# ::::: SAVE LINK :::::
def save_link(url: str):
  parsed = urlparse(url)
  
  if parsed.scheme and parsed.netloc:
    creation_date = dt.now().strftime(DATETIME_FORMAT)
    json_dict = {"url": url, "creation_date": creation_date}
    name_file = get_hash(url.encode()) + ".json"
    full_path = OFFLINE_DIR.joinpath(name_file)
    with open(full_path, "w", encoding="utf-8") as f:
      json.dump(json_dict, f, ensure_ascii=False, indent=4)
    show_message("url saved!")
  else:
    show_message("Invalid URL")
# ====================================
"""


# ::::: CLEAR THIS PAGE :::::
def clear_this_page(link: str) -> str:
  url_combined = f"https://clearthis.page/?u={link}"
  return url_combined
  # ====================================


# ::::: GET WEB PAGE :::::
def load_web_site(url: str) -> str:
  try:
    response: str = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USERAGENT}).content.decode('utf-8', errors='ignore') 
    return response
  except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
    show_message(str(e))
# ====================================


# ::::: EXTRACT ARTICLE FROM HTML :::::
def readability(html: str) -> str:
  article_obj = Document(html)
  return article_obj
# ====================================


# ::::: GET HASH MD5 :::::
def get_hash(text: str) -> str:
  hash_md5 = hashlib.md5(text).hexdigest()
  return hash_md5
# ====================================


"""
# ::::: DOWNLOAD SINGLE IMAGE :::::
def batxhoimg(url_img: str) -> str:
  
  # Load image 
  img_obj = requests.get(url_img, timeout=REQUEST_TIMEOUT)
  
  # Get info image
  img_extension = Path(urlparse(url_img).path).suffix.lower()
  full_img_name  = get_hash(img_obj.content) + img_extension
  full_path = ATTACHMENTS_DIR.joinpath(full_img_name)
  
  # Save image
  with file_lock:
    with open(full_path, "wb") as f:
      f.write(img_obj.content)
      
  return full_img_name
# ====================================
"""


"""
# ::::: DELETE DUPLICATE LINKS (IMG) :::::
def del_dupli_links(article: str , markdown_img) -> str:
  mod_article = article
  processed = []
  for i in markdown_img:
    if i in processed:
      mod_article = re.sub(re.escape(i),"", mod_article, count=1)
    else:
      processed.append(i)
      mod_article = re.sub(re.escape(i), i, mod_article, count=1)
  return mod_article
# ====================================
"""

"""
# ::::: BATCH DOWNLOAD :::::
def batcho(article_content: str) -> str:
  bracket_pattern = r"^(?:!|[)[^\n]*?\)\s*$"
  #only_url_pattern = r"https?://[^\s]+?\.(jpg|jpeg|png|webp|heic|avif|gif)"
  only_url_pattern = r"https?://[^\s\)]+(?:jpg|jpeg|png|webp|heic|avif|gif)[^\s\)]*"
  
  # Find brackets_links 
  brackets_links: list = re.findall(bracket_pattern, article_content, re.MULTILINE)
  new_line_pattern = r'(?<=\))(!\[\])(?=\()'
  
  
  # Mapping brackets_links
  if len(brackets_links) >= 1:
    brackets_map: dict = {match.group(0): bracket for bracket in brackets_links if (match := re.search(only_url_pattern, bracket))}
      
    for img_link, bracket in brackets_map.items():
      local_img = download_img_file(img_link)
      article_content = article_content.replace(img_link, local_img)
    
    return re.sub(new_line_pattern, r'\n\n\1', article_content)

  else:
    return article_content
  # ====================================
"""


# ::::: EXPERIMENTAL - DOWNLOAD AND SAVE IMAGE :::::
async def download_img_file(aiohttp_request, url_img):
  try:
    async with aiohttp_request.get(url_img, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as result:
      
      # --- Get image file ---
      img_obj = await result.read()
      
      # --- Get info image ---
      img_extension = Path(urlparse(url_img).path).suffix.lower()
      md5_img_name  = get_hash(img_obj) + img_extension
      full_path = ATTACHMENTS_DIR.joinpath(md5_img_name)
      
      # --- Save image ---
      with open(full_path, "wb") as img:
        img.write(img_obj)
          
      return {md5_img_name: url_img}
  
  except Exception: # if download fail 
    return {url_img: url_img}
  

# ====================================


# ::::: EXPERIMENTAL -BATCH DOWNLOAD :::::
async def batch_img_download(article_content: str) -> str:
  bracket_pattern = r"^(?:!|\[)[^\n]*?\)\s*$"
  only_url_pattern = r"https?://[^\s\)]+(?:jpg|jpeg|png|webp|heic|avif|gif)[^\s\)]*"
  new_line_pattern = r'(?<=\))(!\[\])(?=\()'

  # Find brackets_links 
  brackets_links: list = re.findall(bracket_pattern, article_content, re.MULTILINE)
  
  # Mapping brackets_links
  if len(brackets_links) >= 1:
    brackets_map: dict = {only_url_img.group(0): bracket for bracket in brackets_links if (only_url_img := re.search(only_url_pattern, bracket))}

    async with aiohttp.ClientSession() as aiohttp_request:
      tasks = [download_img_file(aiohttp_request, url) for url in brackets_map]
      img_objects: list = await asyncio.gather(*tasks, return_exceptions=True)
  
    for dictt in img_objects:
      local_img, ext_img = dictt.popitem()
      article_content = article_content.replace(ext_img, local_img)
    
    return re.sub(new_line_pattern, r'\n\n\1', article_content)
  
  else:
    return article_content
# ====================================


# ::::: FORMAT INLINE TITLE :::::
def fix_title(title: str) -> str:
  pattern = re.compile(r'[\[\]#^|\:*?"<>\/|]') # To-do - enchance this
  clean_title: str = pattern.sub("", title)
  return clean_title
# ====================================


# ::::: DETECT LANGUAGE :::::
def detect_language(text: str) -> str:
  DetectorFactory.seed = 0
  try:
    chunk_txt =   str(text.splitlines()[:5])
    return detect(chunk_txt)
  except Exception:
    return DEFAULT_LANGUAGE
# ====================================


# ::::: GOOGLE TRANSLATE :::::
def google_translate(input_text: str) -> str:
  google_url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=es&dt=t&q={str(quote(input_text))}"
  response = requests.get(google_url)
  return response.json()[0][0][0]
# ====================================   


# ::::: CLOUDFARE AI TRANSLATE :::::
async def cloudfare_translate(txt_translate: str, aiohttp_request) -> str:
  prompt = f"Translate the following text into {DEFAULT_LANGUAGE} while preserving meaning, tone, cultural nuance, and style. If idioms or context don’t translate directly, adapt them naturally for the target audience. Provide only the translated text, no explanations.Text:"
  headers: dict = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}
  body: dict = {"messages": [{"role": "system", "content": prompt},{"role": "user", "content": txt_translate}]}
  # try:
  #   headers: dict = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}
  #   body: dict = {"messages": [{"role": "system", "content": prompt},{"role": "user", "content": txt_translate}]}
  #   http_request = requests.post(url=CLOUDFARE_URL, headers=headers, json=body)
  #   answer_content = http_request.json()
  #   return answer_content['result']['response']
  # except Exception:
  #   return txt_translate
  
  
  try:
    async with aiohttp_request.post(CLOUDFARE_URL, headers=headers, json=body) as resp:      
      answer_content = await resp.json()
      return answer_content['result']['response']
  except Exception:
      return txt_translate
# ===================================


# ::::: LINGVA SERVICE :::::
def lingva_translate(txt_to_translate: str) -> str:
  try:
    lingva_url = f"https://translate.plausibility.cloud/api/v1/en/es/{str(quote(txt_to_translate))}"
    response = requests.get(lingva_url).content.decode('utf-8')
    return json.loads(response)["translation"]
  except Exception:
    return txt_to_translate
# ====================================

"""
# ::::: TRANSLATE CONTENT:::::
async def old_translate(text: str, api_service=lingva_translate) -> str:
  try:
    text_translated = api_service(text)
  except requests.exceptions.RequestException:
    text_translated = translate(text, api_service=lingva_translate)
    
  return text_translated  
# ====================================
"""

# ::::: PRE-TRANSLATE :::::
@tempus
async def translate(md_article):
  print("translating...")
  md_styles_pattern = r"^[!|*|\[|\-]"
   
  # --- get originals article's paragraph ---
  org_chunks = [chunk.strip() for chunk in md_article.split("\n\n") if not re.match(md_styles_pattern, chunk)]
  
  # --- batch translated --
  async with aiohttp.ClientSession() as aiohttp_request:
    trans_tasks = [cloudfare_translate(org_chunk, aiohttp_request) for org_chunk in org_chunks]
    trans_chunks : list = await asyncio.gather(*trans_tasks, return_exceptions=True)
    
    translated_map = dict(zip(org_chunks, trans_chunks))
    for original_chunk, translated_chunk in translated_map.items():
      md_article = md_article.replace(original_chunk, translated_chunk)

    return md_article
  # for original_chunk in org_chunks: 
  #   chunk_translated = translate(original_chunk)
  #   md_article = md_article.replace(original_chunk, chunk_translated)
  #   time.sleep(1.2)
  
  #return md_article
# ====================================
  

# ::::: REGEX RULES (CONTENT) :::::
def content_rules(content: str) -> str:
  regex_rules: list[tuple[str, str]] = [(rule["Pattern"], rule["Replacement"]) for rule in RULES_REGEX]

  for pattern, replacement in regex_rules:
    content: str = re.sub(pattern, replacement, content)
  return content
# ====================================


# ::::: SAVE TO FILE :::::
def save_to_file(name_file: str, content: str) -> None:
  out_path = ARTICLES_DIR.joinpath(f"{name_file}.md")
  with open(out_path, "w") as file:
    file.write(content)
# ====================================


# ::::: FORMAT TAGS :::::
def format_tags(tags: str) -> str:
  x_tags = tags.split(",")
  return "\n" + "".join(f"  - {i}\n" for i in x_tags)
# ====================================


# ::::: BUILD TEMPLATE :::::
def build_template(creation_date, author, title, num_words, read_time, full_note, url, tags, audio) -> str:
  metadata = {
  "%CREATIONDATE": creation_date,
  "%AUTHOR": author if  author != "[no-author]" else "Unknown",
  "%WORDS": num_words,
  "%READTIME": f"{read_time} minutes",
  "%ARTICLE": full_note,
  "%URL": url,
  "%TAGS": format_tags(tags) if tags else "",
  "%AUDIO": f"![[{audio}.mp3]]" if audio is not None else ""
  }
  
  with open(TEMPLATE, "r") as f:
    template = f.read()
    for var, value in metadata.items():
      if var in template:
        template = template.replace(str(var), str(value)) 
  
  return template
# ====================================


# ::::: DELETE / MOVE JSON FINISHED :::::
def delete_json(json_file: Path) -> None:
  with file_lock:
    done_path = ARTICLES_SYNCED_DIR.joinpath(json_file.name)
    
    if DEL_SYNCED_ARTICLES:
      json_file.unlink(missing_ok=True)
    else:
      json_file.rename(done_path)
# ====================================


# ::::: CLEAN ATTACHMENTS DIR :::::
def clean_attachments():
  articles_dir = ARTICLES_DIR
  attachments_dir = ATTACHMENTS_DIR
  total_img_innotes = set()

  article_files = {article for article in articles_dir.glob("*.md") if article.is_file()}
  attachments_imgs = {img.name for img in attachments_dir.glob("*")}

  pattern = re.compile(r"([a-f0-9]{32}\.(jpg|jpeg|png|webp|heic|avif|gif))")

  for article in article_files:
    with open(article, "r") as f:
      article_content = f.read()
      total_img_innotes.update([match.group(1) for match in pattern.finditer(article_content)])
  
  img_to_del = attachments_imgs - total_img_innotes
  for img_name in img_to_del:
    (attachments_dir / img_name).unlink()
# ====================================


# ::::: SHOW MESSAGES :::::
def show_message(msg: str, sep="-") -> None:
  line = sep * len(msg)
  print(f"{line}\n{msg}\n{line}")
# ====================================


# ::::: CONVERT TO PLAINTEXT :::::
def convert_to_plaintext(text: str) -> str:
 
  # HEADERS
  text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
  
  # CODE BLOCKS
  text = re.sub(r'```[\s\S]*?```', '', text)
  
  # INLINE
  text = re.sub(r'`([^`]+)`', r'\1', text)
  
  # BOLD
  text = re.sub(r'\*\*([^\*]+)\*\*', r'\1', text)
  text = re.sub(r'__([^_]+)__', r'\1', text)
  
  # ITALIC
  text = re.sub(r'\*([^\*]+)\*', r'\1', text)
  text = re.sub(r'_([^_]+)_', r'\1', text)
  
  # 
  text = re.sub(r'~~([^~]+)~~', r'\1', text)
  
  # ALT TEXT LINKS
  text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
  
  # IMAGES
  text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
  
  # SEPARATORS
  text = re.sub(r'^[\*\-_]{3,}\s*$', '', text, flags=re.MULTILINE)
  
  # LISTS
  text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE)
  text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
  
  # BLOCKQUOTES
  text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
  
  
  # CALLOUTS
  text = re.sub(r'\[![\w]+\]', '', text)
  
  # EMBEDS
  text = re.sub(r'!\[\[.*?\]\]', '', text)
  
  # IMAGES
  text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)
  text = re.sub(r'!\[([^\]]*)\]', '', text)
  
  # URLS
  text = re.sub(r'https?://[^\s]+', '', text)
  text = re.sub(r'www\.[^\s]+', '', text)
  
  return text
# ====================================


# ::::: MICROSOFT EDGE TTS :::::
def text_to_voice(text: str, name_file: str) -> None:
  output_audio_file = ATTACHMENTS_DIR.joinpath(f"{name_file}.mp3")
  communicate = edge_tts.Communicate(text, TTS_VOICE)
  communicate.save_sync(output_audio_file)
# ====================================


# ::::: MAIN :::::
LOG_FILE = "logs/app.log"
logger.add(LOG_FILE, rotation="500 MB", level="DEBUG")
@logger.catch
async def main(json_file: Path) -> None:
  
  # --- JSON SETTINGS ---
  article_params = get_json_data(json_file)
  creation_date = article_params["creation_date"]
  url = article_params["url"]
  voice_on = article_params["voice"]
  tags = article_params["labels"]
  custom_rules = article_params["regex"]
  translate_on = article_params["translate"]
  
  
  # --- CLEAR THIS PAGE --+ 
  #url = clear_this_page(url)

  # --- HTML ---
  html_page = load_web_site(url)
  if html_page:
    html_article = readability(html_page)
    summary_article = html_article.summary(keep_all_images=True)

  # --- MARKDOWN ---
    md_article = md(summary_article)

  # --- ARTICLE METADATA ---
    author = html_article.author()
    title = fix_title(html_article.title())
    num_words = len(md_article.split(" "))
    read_time = num_words // WPM
  
  # --- APPLY REGEX CONTENT RULES ---
    if custom_rules:
      md_article = content_rules(md_article) 
  
  # --- TRANSLATE --- 
    if translate_on and detect_language(md_article) != DEFAULT_LANGUAGE:
      md_article = await translate(md_article)

  # --- EDGE TTS ---
    if voice_on:
      audio_filename = get_hash(title.encode('utf-8'))
      plain_text = convert_to_plaintext(md_article)
      text_to_voice(plain_text, audio_filename)

  # --- IMAGES ---
    full_note = await batch_img_download(md_article)

  # --- BUILD TEMPLATE ---
    note_templated = build_template(creation_date, author, title, num_words, read_time, full_note, url, tags, audio_filename)
  
  # --- SAVE FILE ---
    save_to_file(title, note_templated)
  
  # --- DEL ARTICLE DOWNLOADED ---
    delete_json(json_file)
  # ====================================


# :::::QUEUE ARTICLES :::::
async def start_sync() -> None:
  show_message("Sync started...")
  
  json_files = list(OFFLINE_DIR.glob("*.json"))
  
  
  for i in json_files:
    await main(i)
# ====================================


if __name__ == "__main__":
  #validate_dir_paths()
  #get_urls()
  
  
  filee = "/storage/emulated/0/Documents/Obsidian/Read Later/The Nonwriter's Guide to Writing A Lot.md"
  with open(filee, "r") as f:
    text = f.read()
    x = asyncio.run(translate(text))
    print(x)
  

