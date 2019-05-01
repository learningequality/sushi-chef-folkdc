#!/usr/bin/env python

from bs4 import BeautifulSoup
import codecs
from collections import defaultdict, OrderedDict
import copy
from git import Repo
import glob
from le_utils.constants import licenses, content_kinds, file_formats
import hashlib
import json
import logging
import markdown2
import ntpath
import os
from pathlib import Path
import re
import requests
from ricecooker.classes.licenses import get_license
from ricecooker.chefs import JsonTreeChef
from ricecooker.utils import downloader, html_writer
from ricecooker.utils.caching import CacheForeverHeuristic, FileCache, CacheControlAdapter
from ricecooker.utils.html import download_file
from ricecooker.utils.jsontrees import write_tree_to_json_tree, SUBTITLES_FILE
from ricecooker.utils.zip import create_predictable_zip
from pressurecooker.youtube import YouTubeResource
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.parse import urlparse, parse_qs 
from utils import dir_exists, get_name_from_url, clone_repo, build_path
from utils import file_exists, get_video_resolution_format, remove_links
from utils import get_name_from_url_no_ext, get_node_from_channel, get_level_map
from utils import remove_iframes, get_confirm_token, save_response_content
from utils import link_to_text, remove_scripts
import youtube_dl
from urllib.parse import urlparse


DATA_DIR = "chefdata"
DATA_DIR_SUBJECT = ""
COPYRIGHT_HOLDER = " European Commission"
LICENSE = get_license(licenses.CC_BY_NC, 
        copyright_holder=COPYRIGHT_HOLDER).as_dict()
AUTHOR = "FolkDC"

LOGGER = logging.getLogger()
__logging_handler = logging.StreamHandler()
LOGGER.addHandler(__logging_handler)
LOGGER.setLevel(logging.INFO)

DOWNLOAD_VIDEOS = True
DOWNLOAD_FILES = True
OVERWRITE = True

sess = requests.Session()
cache = FileCache('.webcache')
basic_adapter = CacheControlAdapter(cache=cache)
forever_adapter = CacheControlAdapter(heuristic=CacheForeverHeuristic(), cache=cache)

# Run constants
################################################################################
CHANNEL_NAME = "FolkDC Learning through Folksongs"              # Name of channel
CHANNEL_SOURCE_ID = "sushi-chef-folkdc"    # Channel's unique id
CHANNEL_DOMAIN = ""          # Who is providing the content
CHANNEL_LANGUAGE = ""      # Language of channel
CHANNEL_DESCRIPTION = None                                  # Description of the channel (optional)
CHANNEL_THUMBNAIL = "http://folkdc.eu/img/Folk8-200.png"    # Local path or url to image file (optional)


SUBJECTS = {
    "en": {"introduction": "http://folkdc.eu/resources/overview/",
           "songs": ""},
    "es": {"introduction": 
            {"title": "Introducción", "url": "http://folkdc.eu/es/recursos/introduccion/"},
          "songs": 
            {"title": "Canciones", "url": "http://folkdc.eu/es/recursos/attt-canciones-y-plantillas/"},
          "activities": 
            {"title": "Actividades", "url": "http://folkdc.eu/es/attt-actividades/"}
          },
    "it": {"introduction": "http://folkdc.eu/it/resources/introduzione/"}
}



def cache(fn):
    def view(*args, **kwargs):
        self = args[0]
        key = "{}_cache".format(fn.__name__)
        if not hasattr(self, key):
            value = fn(*args, **kwargs)
            setattr(self, key, value)
        return getattr(self, key)
    return view


class Node:
    def __init__(self, title=None, source_id=None, lang="en"):
        self.title = title
        self.source_id = source_id
        self.tree_nodes = OrderedDict()
        self.lang = lang
        self.description = None

    @classmethod
    def cls_name(cls):
        return cls.__name__

    def add_node(self, obj):
        node = obj.to_node()
        if node is not None:
            self.tree_nodes[node["source_id"]] = node

    def add_nodes(self, nodes):
        for node in nodes:
            self.add_node(node)

    def to_node(self):
        children = list(self.tree_nodes.values())
        if len(children) == 1:
            return children[0]
        else:
            return dict(
                kind=content_kinds.TOPIC,
                source_id=self.source_id,
                title=self.title,
                description=self.description,
                language=self.lang,
                author=AUTHOR,
                #role=roles.COACH,
                license=LICENSE,
                children=list(self.tree_nodes.values())
            )


class Resource(object):
    def __init__(self, lang="en"):
        self.lang = lang
        self.resources = []

    def load(self, filename, auto_parse=False):
        for subject, info in SUBJECTS[self.lang].items():
            if subject == "introduction":
                subject_obj = Introduction(title=info["title"], source_id=info["url"], 
                    lang=self.lang)
                self.resources.append(subject_obj)
            #print(, info)
        #with open(filename, "r") as f:
        #    grades = json.load(f)
        #    for grade in grades:
        #        grade_obj = Grade() 
        #        subject_obj = Subject(title=grade["title"], source_id=grade["source_id"], 
        #                              lang=grade["lang"])
        #        subject_obj.auto_generate_lessons(grade["lessons"], playlist=False)
        #        self.grades.append(subject_obj)

    def __iter__(self):
        return iter(self.resources)


class Html5Node(Node):

    def clean(self, content):
        link_to_text(content)
        remove_links(content)
        remove_iframes(content)
        remove_scripts(content)
        return content

    def to_local_images(self, content):
        images_urls = {}
        for img in content.find_all("img"):
            try:
                img_src = img["src"]
            except KeyError:
                continue
            else:
                if img_src.startswith("/"):
                    img_src = urljoin(BASE_URL, img_src)
                filename = get_name_from_url(img_src)
                if img_src not in images_urls and img_src:
                    img["src"] = filename
                    images_urls[img_src] = filename
        return images_urls

    def write_css_js(self, filepath):
        with html_writer.HTMLWriter(filepath, "a") as zipper, open("chefdata/styles.css") as f:
            content = f.read()
            zipper.write_contents("styles.css", content, directory="css/")

        with html_writer.HTMLWriter(filepath, "a") as zipper, open("chefdata/scripts.js") as f:
            content = f.read()
            zipper.write_contents("scripts.js", content, directory="js/")

    def write_index(self, filepath, content):
        with html_writer.HTMLWriter(filepath, "w") as zipper:
            zipper.write_index_contents(content)

    def write_images(self, filepath, images):
        with html_writer.HTMLWriter(filepath, "a") as zipper:
            for img_src, img_filename in images.items():
                try:
                    if img_src.startswith("data:image/") or img_src.startswith("file://"):
                        pass
                    else:
                        # zipper.write_url(img_src, img_filename, directory="")
                        zipper.write_contents(img_filename, downloader.read(img_src, timeout=5, session=sess), directory="")
                except (requests.exceptions.HTTPError, requests.exceptions.ConnectTimeout,
                        requests.exceptions.ConnectionError, FileNotFoundError, requests.exceptions.ReadTimeout):
                    pass

    def to_file(self, base_path):
        filepath = "{path}/{name}.zip".format(path=base_path, name=self.title)
        if file_exists(filepath) and OVERWRITE is False:
            self.filepath = filepath
            LOGGER.info("Not overwrited file {}".format(self.filepath))
        else:
            self.filepath = filepath
            body = self.clean(self.body)
            images = self.to_local_images(body)
            try:
                self.write_index(self.filepath, '<html><head><meta charset="utf-8"><link rel="stylesheet" href="css/styles.css"></head><body><div class="main-content-with-sidebar">{}</div><script src="js/scripts.js"></script></body></html>'.format(body))
            except RuntimeError as e:
                self.filepath = None
                LOGGER.error(e)
            else:
                self.write_images(self.filepath, images)
                self.write_css_js(self.filepath)

    def to_node(self):
        if self.filepath is not None:
            return dict(
                kind=content_kinds.HTML5,
                source_id=self.source_id,
                title=self.title,
                description="",
                thumbnail=None,
                author=AUTHOR,
                files=[dict(
                    file_type=content_kinds.HTML5,
                    path=self.filepath
                )],
                language=self.lang,
                license=LICENSE)


class ContentNode(Node):
    def to_soup(self):
        LOGGER.info("DOWNLOADING: {}".format(self.source_id))
        document = download(self.source_id)
        if document is not None:
            return BeautifulSoup(document, 'html5lib') #html5lib

    def get_videos_urls(self, content):
        urls = set([])
        if content is not None:
            video_urls = content.find_all(lambda tag: tag.name == "a" and tag.attrs.get("href", "").find("youtube") != -1 or tag.attrs.get("href", "").find("youtu.be") != -1 or tag.text.lower() == "youtube")

            for video_url in video_urls:
                urls.add(video_url.get("href", ""))

            for iframe in content.find_all("iframe"):
                url = iframe["src"]
                if YouTubeResource.is_youtube(url) and not YouTubeResource.is_channel(url):
                    urls.add(YouTubeResource.transform_embed(url))
        return urls

    def get_pdfs_urls(self, content):
        urls = set([])
        if content is not None:
            pdf_urls = content.findAll(lambda tag: tag.name == "a" and tag.attrs.get("href", "").endswith(".pdf"))
            for pdf_url in pdf_urls:
                urls.add(pdf_url.get("href", ""))
        return urls

    def build_pdfs_nodes(self, base_path, content):
        pdfs_url = self.get_pdfs_urls(content)
        base_path = build_path([base_path, 'pdfs'])
        for pdf_url in pdfs_url:
            pdf_file = File(source_id=pdf_url, lang=self.lang, title=self.title)
            pdf_file.download(download=DOWNLOAD_FILES, base_path=base_path)
            yield pdf_file

    def build_video_nodes(self, base_path, content):
        videos_url = self.get_videos_urls(content)
        base_path = build_path([DATA_DIR])
        video_nodes = []
        for video_url in videos_url:
            if YouTubeResource.is_youtube(video_url) and not YouTubeResource.is_channel(video_url):
                video = YouTubeResourceNode(video_url, lang=self.lang)
                video.download(download=DOWNLOAD_VIDEOS, base_path=base_path)
                yield video

    def to_file(self, base_path):
        html_node = Html5Node(title=self.title, source_id=self.source_id, 
                              lang=self.lang)
        html_node.body = self.body()
        html_node.to_file(base_path)
        if html_node.body is not None:
            self.add_node(html_node)
            self.add_nodes(self.build_video_nodes(base_path, html_node.body))
            self.add_nodes(self.build_pdfs_nodes(base_path, html_node.body))
        else:
            LOGGER.error("Empty body in {}".format(self.source_id))
            return


class Introduction(ContentNode):
    @cache
    def body(self):
        soup = self.to_soup()
        return soup.find("div", id="column-main")


def thumbnails_links(soup, tag, class_):
    if soup is not None:
        courses_list = soup.find_all(tag, class_=class_)
        thumnails = {}
        for course_li in courses_list:
            link = course_li.find("a").get("href")
            img = course_li.find("img")
            if img is not None:
                thumnails[link] = img["src"]
        return thumnails


def save_thumbnail(url, title):
    import imghdr
    from io import BytesIO
    try:
        r = requests.get(url)
    except:
        return None
    else:
        img_buffer = BytesIO(r.content)
        img_ext = imghdr.what(img_buffer)
        if img_ext != "gif":
            filename = "{}.{}".format(title, img_ext)
            base_dir = build_path([DATA_DIR, DATA_DIR_SUBJECT, "thumbnails"])
            filepath = os.path.join(base_dir, filename)
            with open(filepath, "wb") as f:
                f.write(img_buffer.read())
            return filepath


class YouTubeResourceNode(YouTubeResource):
    def __init__(self, source_id, name=None, type_name="Youtube", lang="ar", 
            embeded=False, section_title=None):
        if embeded is True:
            self.source_id = YouTubeResourceNode.transform_embed(source_id)
        else:
            self.source_id = self.clean_url(source_id)
        super(YouTubeResourceNode, self).__init__(source_id)
        LOGGER.info("    + Resource Type: {}".format(type_name))
        LOGGER.info("    - URL: {}".format(source_id))
        self.filename = None
        self.type_name = type_name
        self.filepath = None
        self.name = name
        self.section_title = section_title
        self.file_format = file_formats.MP4
        self.lang = lang
        self.is_valid = False

    def clean_url(self, url):
        if url[-1] == "/":
            url = url[:-1]
        return url.strip()

    @property
    def title(self):
        return self.name

    @title.setter
    def title(self, v):
        self.name = v

    @classmethod
    def is_youtube(self, url, get_channel=False):
        youtube = url.find("youtube") != -1 or url.find("youtu.be") != -1
        if get_channel is False:
            youtube = youtube and url.find("user") == -1 and url.find("/c/") == -1
        return youtube

    @classmethod
    def transform_embed(self, url):
        url = "".join(url.split("?")[:1])
        return url.replace("embed/", "watch?v=").strip()

    def playlist_links(self):
        ydl_options = {
                'no_warnings': True,
                'restrictfilenames':True,
                'continuedl': True,
                'quiet': False,
                'format': "bestvideo[height<={maxheight}][ext=mp4]+bestaudio[ext=m4a]/best[height<={maxheight}][ext=mp4]".format(maxheight='480'),
                'noplaylist': False
            }

        playlist_videos_url = []
        with youtube_dl.YoutubeDL(ydl_options) as ydl:
            try:
                ydl.add_default_info_extractors()
                info = ydl.extract_info(self.source_id, download=False)
                for entry in info["entries"]:
                    playlist_videos_url.append(entry["webpage_url"])
            except(youtube_dl.utils.DownloadError, youtube_dl.utils.ContentTooShortError,
                    youtube_dl.utils.ExtractorError) as e:
                LOGGER.info('An error occured ' + str(e))
                LOGGER.info(self.source_id)
            except KeyError as e:
                LOGGER.info(str(e))
        return playlist_videos_url

    def playlist_name_links(self):
        name_url = []
        source_id_hash = hashlib.sha1(self.source_id.encode("utf-8")).hexdigest()
        base_path = build_path([DATA_DIR])
        videos_url_path = os.path.join(base_path, "{}.json".format(source_id_hash))

        if file_exists(videos_url_path) and LOAD_VIDEO_LIST is True:
            with open(videos_url_path, "r") as f:
                name_url = json.load(f)
        else:
            for url in self.playlist_links():
                youtube = YouTubeResourceNode(url)
                info = youtube.get_resource_info()
                name_url.append((info["title"], url))
            with open(videos_url_path, "w") as f:
                json.dump(name_url, f)
        return name_url

    def subtitles_dict(self):
        subs = []
        video_info = self.get_resource_subtitles()
        if video_info is not None:
            video_id = video_info["id"]
            if 'subtitles' in video_info:
                subtitles_info = video_info["subtitles"]
                for language in subtitles_info.keys():
                    subs.append(dict(file_type=SUBTITLES_FILE, youtube_id=video_id, language=language))
        return subs

    def download(self, download=True, base_path=None):
        info = super(YouTubeResourceNode, self).download(base_path=base_path)
        self.filepath = info["filename"]
        self.title = info["title"]
        return self.get_file_url(info)

    def get_file_url(self, info):
        description = info["description"]
        pattern = 'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        url_re = re.compile(pattern)
        return url_re.findall(description)

    def to_node(self):
        if self.filepath is not None:
            files = [dict(file_type=content_kinds.VIDEO, path=self.filepath)]
            files += self.subtitles_dict()
            node = dict(
                kind=content_kinds.VIDEO,
                source_id=self.source_id,
                title=self.title,
                description='',
                author=AUTHOR,
                files=files,
                language=self.lang,
                license=LICENSE
            )
            return node


class File(Node):
    def __init__(self, title=None, source_id=None, lang="en"):
        super(File, self).__init__(title=title, source_id=source_id, lang=lang)
        self.filename = get_name_from_url(source_id)
        self.source_id = urljoin(BASE_URL, self.source_id) if source_id.startswith("/") else self.source_id
        self.filepath = None
        self.name = "{}_{}".format(self.title, self.filename)

    def download(self, download=True, base_path=None):
        try:
            if download is False:
                return
            response = sess.get(self.source_id)
            content_type = response.headers.get('content-type')
            if content_type is not None and 'application/pdf' in content_type:
                self.filepath = os.path.join(base_path, self.filename)
                with open(self.filepath, 'wb') as f:
                    for chunk in response.iter_content(10000):
                        f.write(chunk)
                LOGGER.info("    - Get file: {}, node name: {}".format(self.filename, self.name))
        except requests.exceptions.HTTPError as e:
            LOGGER.info("Error: {}".format(e))
        except requests.exceptions.ConnectionError:
            ### this is a weird error, may be it's raised when the webpage
            ### is slow to respond requested resources
            LOGGER.info("Connection error, the resource will be scraped in 5s...")
            time.sleep(3)
        except requests.exceptions.ReadTimeout as e:
            LOGGER.error("Error: {}".format(e))
        except requests.exceptions.TooManyRedirects as e:
            LOGGER.error("Error: {}".format(e))
        except requests.exceptions.InvalidSchema as e:
            LOGGER.error("Error: {}".format(e))

    def to_node(self):
        if self.filepath is not None:
            node = dict(
                kind=content_kinds.DOCUMENT,
                source_id=self.source_id,
                title=self.name,
                description='',
                files=[dict(
                    file_type=content_kinds.DOCUMENT,
                    path=self.filepath
                )],
                language=self.lang,
                license=LICENSE)
            return node


def download(source_id, loadjs=False, timeout=5):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:20.0) Gecko/20100101 Firefox/20.0",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive"
    }

    tries = 0
    while tries < 4:
        try:
            #document = downloader.read(source_id, loadjs=loadjs, session=sess)
            response = sess.get(source_id, headers=headers, timeout=timeout)
            if response.status_code != 200:
                LOGGER.error(response.status_code)
            document = response.text
        except requests.exceptions.HTTPError as e:
            LOGGER.info("Error: {}".format(e))
        except requests.exceptions.ConnectionError:
            ### this is a weird error, may be it's raised when the webpage
            ### is slow to respond requested resources
            LOGGER.info("Connection error, the resource will be scraped in 5s...")
            time.sleep(3)
        except requests.exceptions.TooManyRedirects as e:
            LOGGER.info("Error: {}".format(e))
        except (requests.exceptions.InvalidURL, FileNotFoundError) as e:
            LOGGER.error(e)
        else:
            return document
        tries += 1


# The chef subclass
################################################################################
class FolkDCChef(JsonTreeChef):
    TREES_DATA_DIR = os.path.join(DATA_DIR, 'trees')
    SCRAPING_STAGE_OUTPUT_TPL = 'ricecooker_{lang}_json_tree.json'
    BASE_URL = "http://folkdc.eu/"

    def pre_run(self, args, options):
        build_path([FolkDCChef.TREES_DATA_DIR])
        self.download_css_js()
        self.lang = options.get('--lang', "en")
        self.RICECOOKER_JSON_TREE = FolkDCChef.SCRAPING_STAGE_OUTPUT_TPL.format(lang=self.lang)
        self.scrape_stage = os.path.join(FolkDCChef.TREES_DATA_DIR, 
            self.RICECOOKER_JSON_TREE)
        channel_tree = self.scrape(args, options)
        self.write_tree_to_json(channel_tree)

    def download_css_js(self):
        r = requests.get("https://raw.githubusercontent.com/learningequality/html-app-starter/master/css/styles.css")
        with open("chefdata/styles.css", "wb") as f:
            f.write(r.content)

        r = requests.get("https://raw.githubusercontent.com/learningequality/html-app-starter/master/js/scripts.js")
        with open("chefdata/scripts.js", "wb") as f:
            f.write(r.content)

    def scrape(self, args, options):
        run_test = bool(int(options.get('--test', "0")))

        global channel_tree
        channel_tree = dict(
                source_domain=FolkDCChef.BASE_URL,
                source_id=CHANNEL_SOURCE_ID + "-" + self.lang,
                title=CHANNEL_NAME,
                description="""Digital Children's Folksongs for Language and Cultural Learning: a collection of multi-language folk songs and activities for primary students to learn languages, engage in collaboration and critical thinking, and develop intercultural skills. Contains folk songs, activity suggestions, and teacher training materials."""
[:400], #400 UPPER LIMIT characters allowed 
                thumbnail=CHANNEL_THUMBNAIL,
                author=AUTHOR,
                language=self.lang,
                children=[],
                license=LICENSE,
            )

        if run_test is True:
            return test(channel_tree)
        else:
            resources = Resource(lang=self.lang)
            resources.load(None)
            for resource in resources:
                base_path = build_path([DATA_DIR, self.lang, resource.cls_name()])
                resource.to_file(base_path)
                node = resource.to_node()
                if node is not None:
                    channel_tree["children"].append(node)
            return channel_tree

    def write_tree_to_json(self, channel_tree):
        write_tree_to_json_tree(self.scrape_stage, channel_tree)


def test(channel_tree):
    base_path = build_path([DATA_DIR, DATA_DIR_SUBJECT, "test"])
    #c = CourseIndex("test", "https://chem.libretexts.org/Courses/University_of_California%2C_Irvine/UCI%3A_General_Chemistry_1C_(OpenChem)/015Review_on_Cell_Potential_(OpenChem)/xSolution")
    #c.index(base_path)
    c = Chapter("test", "https://phys.libretexts.org/Courses/University_of_California_Davis/UCD%3A_Physics_9A%2F%2F9HA_%E2%80%93_Classical_Mechanics/4%3A_Linear_Momentum/4.6%3A_Problem_Solving")
    c.to_file(base_path)
    channel_tree["children"].append(c.to_node())
    return channel_tree

# CLI
################################################################################
if __name__ == '__main__':
    chef = FolkDCChef()
    chef.main()
