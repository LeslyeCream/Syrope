# Syrope

> A CLI alternative for saving web articles in Markdown. Similar to Pocket, but for Obsidian

---

## Features

- Automatically extracts the main content from any webpage
- Converts web articles to clean Markdown files
- Maintains formatting, images, links, and structure
- Automatically generates audio versions of articles (Uses Microsoft Edge's TTS)
- Translates articles (Uses Cloudfare AI for translations)
- Downloads and embeds images from the article. Saves them locally
- Add custom tags to articles
- Add metadata (reading time, word count, creation date, author)
- Automatically finds and download PDF papers cited in articles
- Apply custom regex patterns to clean up content

---

# How is it different from the Obsidian extension?

Basically, it's the automation. It lets you save all articles at once with custom settings.

- For example, you might prefer to *read* Substack articles that aren't in your language, but you might prefer to *listen* to the latest news articles online. 
- It doesn't try to compete with or match the scope of Obsidian (although they share many similarities), but rather to recreate the essence of Pocket: copy a URL -> save and sync -> read it later

## How to use

Syrope has two modes of use:

#### 1. **Interactive Menu (Easiest)**
Just run the script:

```bash
python Syrope.py
```

You'll see options like:

- Sync articles
- View your saved articles
- Add new articles
- Exit

#### 2. **Command Line**

Use command-line options for more control:

**Add a single URL**

```bash
python Syrope.py "https://example.com/article" --labels "tag1,tag2" --voice --regex --translate
```

**Add multiple URLs from a file**

```bash
python Syrope.py -i my_urls.txt --voice --translate --labels "Science, Study, News"
```

# Start syncing

```python
python Syrope.py --sync
```

*or simply by using ```--sync``` along with any other command*

---

## Getting Started

### Installation

1. **Clone or download this project**

```bash
git clone https://github.com/yourusername/Syrope.git && cd Syrope
```

2. **Install required packages**

```bash
pip install -r requirements.txt
```

3. **Set up the configuration file**
Edit `Settings.yaml`with your own custom settings


4. **Template file (Optional)**
Edit the template with the variables that need to be included in the article.
The default template looks like this:


```
---
Created: %CREATIONDATE
Read Time: %READTIME minutes
Author: %AUTHOR 
Words: %WORDS 
Tags: %TAGS
---

%AUDIO

***

%PDF 


%ARTICLE

*** 

**Read original article** 

> [!QUOTE]
> %URL
```

---

## Command Line Options

```bash
python Syrope.py [URL] [OPTIONS]

Options:
  -l, --labels LABELS       Add tags to the article (comma-separated)
  -t, --translate            Translate article to your default language
  -v, --voice                Generate audio version
  -r, --regex                Apply custom regex rules
  -i, --input-file PATH      Load URLs from a file (one per line)
  -s, --sync                 Sync articles
```

---

## Configuration Guide

### Settings.yaml Explained

```yaml
PATHS:
  ARTICLES_DIR: "./Articles"           # Folder in Obsidian where the articles will be stored
  ATTACHMENTS_DIR: "./Attachments"     # Folder in Obsidian where the audio and images for the articles will be stored

OTHERS:
  FOREIGN_LANGUAGES:                   #List of languages to detect (to avoid loading them all) 
    - ita
    - fr

  DATETIME_FORMAT: "%Y-%m-%d %H:%M"    # Date format in your notes
  DEFAULT_LANGUAGE: "en"               # Language into which the articles will be translated
  REQUEST_TIMEOUT: 10                  # Seconds to wait for load websites
  READING_THRESHOLD: 30                # Max minutes to generate audio
  WPM: 200                             # Reading speed. Words per minute
  DEL_SYNCED_ARTICLES: true            # Remove items that have already been downloaded
  USERAGENT: "Mozilla/5.0..."          # Browser identification
  TTS_VOICE: "en-US-AriaNeural"        # Which voice to use for audio

PARAM_DEFAULTS:
  voice: false                         # Default: don't generate audio
  translate: false                     # Default: don't translate
  labels: null                         # Default: no tags
  regex: false                         # Default: don't apply custom regex

API:
  API_KEY : 'API_KEY_HERE'             # Cloudflare API Key
  CLOUDFARE_URL: 'CLOUDFARE_URL_HERE'  # Cloudflare url

REGEX:
  - Pattern: "pattern_to_match"        # Regex pattern
    Replacement: "replacement_text"    # What to replace it with
```


## Project Structure

```
Syrope/
├── Syrope.py             # Main script
├── Settings.yaml         # Configuration file
├── Template              # File used as a reference for structuring web articles
├── Offline               # JSON files (articles) pending synchronization
├── Done                  # JSON files (articles) that have already been synchronized
└── README.md             # This file
```

---

## License

This project is open source and available under the AGPL v3 License.

## Roadmap

- [ ] Add synchronization with Raindrop.io
- [ ] Apply a URL-based regular expression 
- [ ] Support for more TTS providers
- [ ] Add translations from Kagi, DeepL, etc
- [ ] Add custom settings for each URL when importing them from a file

---

This project initially started as an automated Tasker task (and it worked!) but Python offered me a faster and more functional way to achieve it (:

# Contribution
Please open an issue on GitHub, DM me on Twitter / Bluesky. I will try to fix it as soon as possible. 

If you find this script very useful, consider supporting me ᵔᴥᵔ

<a href='https://ko-fi.com/W7W349H97' target='_blank'><img height='36' style='border:0px;height:36px;' src='https://storage.ko-fi.com/cdn/kofi1.png?v=6' border='0' alt='Buy Me a Coffee at ko-fi.com' /></a>

Script created using [Acode](https://github.com/Acode-Foundation/Acode) and Fleksy 🖤