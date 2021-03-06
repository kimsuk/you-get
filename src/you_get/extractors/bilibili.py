#!/usr/bin/env python

__all__ = ['bilibili_download']

import hashlib
import re
import time
import json
import http.cookiejar
import urllib.request
import urllib.parse
from xml.dom.minidom import parseString

from ..common import *
from ..util.log import *
from ..extractor import *

from .qq import qq_download_by_vid
from .sina import sina_download_by_vid
from .tudou import tudou_download_by_id
from .youku import youku_download_by_vid

class Bilibili(VideoExtractor):
    name = 'Bilibili'
    live_api = 'http://live.bilibili.com/api/playurl?cid={}&otype=json'
    api_url = 'http://interface.bilibili.com/playurl?'
    bangumi_api_url = 'http://bangumi.bilibili.com/player/web_api/playurl?'
    
    SEC1 = '1c15888dc316e05a15fdd0a02ed6584f'
    SEC2 = '9b288147e5474dd2aa67085f716c560d'
    stream_types = [
            {'id': 'hdflv'},
            {'id': 'flv'},
            {'id': 'hdmp4'},
            {'id': 'mp4'},
            {'id': 'live'}
    ]
    fmt2qlt = dict(hdflv=4, flv=3, hdmp4=2, mp4=1)

    @staticmethod
    def bilibili_stream_type(urls):
        url = urls[0]
        if 'hd.flv?' in url:
            return 'hdflv', 'flv'
        if '.flv?' in url:
            return 'flv', 'flv'
        if 'hd.mp4?' in url:
            return 'hdmp4', 'mp4'
        if '.mp4?' in url:
            return 'mp4', 'mp4'
        raise Exception('Unknown stream type')

    def api_req(self, cid, quality, bangumi):
        ts = str(int(time.time()))
        if not bangumi:
            params_str = 'cid={}&player=1&quality={}&ts={}'.format(cid, quality, ts)
            chksum = hashlib.md5(bytes(params_str+self.SEC1, 'utf8')).hexdigest()
            api_url = self.api_url + params_str + '&sign=' + chksum
        else:
            params_str = 'cid={}&module=bangumi&player=1&quality={}&ts={}'.format(cid, quality, ts)
            chksum = hashlib.md5(bytes(params_str+self.SEC2, 'utf8')).hexdigest()
            api_url = self.bangumi_api_url + params_str + '&sign=' + chksum

        xml_str = get_content(api_url)
        return xml_str

    def parse_bili_xml(self, xml_str):
        urls_list = []
        total_size = 0
        doc = parseString(xml_str.encode('utf8'))
        durls = doc.getElementsByTagName('durl')
        for durl in durls:
            size = durl.getElementsByTagName('size')[0]
            total_size += int(size.firstChild.nodeValue)
            url = durl.getElementsByTagName('url')[0]
            urls_list.append(url.firstChild.nodeValue)
        stream_type, container = self.bilibili_stream_type(urls_list)
        if stream_type not in self.streams:
            self.streams[stream_type] = {}
            self.streams[stream_type]['src'] = urls_list
            self.streams[stream_type]['size'] = total_size
            self.streams[stream_type]['container'] = container

    def download_by_vid(self, cid, bangumi, **kwargs):
        stream_id = kwargs.get('stream_id')
# guard here. if stream_id invalid, fallback as not stream_id
        if stream_id and stream_id in self.fmt2qlt:
            quality = stream_id
        else:
            quality = 'hdflv' if bangumi else 'flv'

        info_only = kwargs.get('info_only')
        if not info_only or stream_id:
# won't be None
            qlt = self.fmt2qlt.get(quality)
            api_xml = self.api_req(cid, qlt, bangumi)
            self.parse_bili_xml(api_xml)
            self.danmuku = get_danmuku_xml(cid)
        else:
            for qlt in range(4, 0, -1):
                api_xml = self.api_req(cid, qlt, bangumi)
                self.parse_bili_xml(api_xml)

    def prepare(self, **kwargs):
        self.ua = fake_headers['User-Agent']
        self.url = url_locations([self.url])[0]
        frag = urllib.parse.urlparse(self.url).fragment
# http://www.bilibili.com/video/av3141144/index_2.html#page=3
        if frag:
            hit = re.search(r'page=(\d+)', frag)
            if hit is not None:
                page = hit.group(1)
                aid = re.search(r'av(\d+)', self.url).group(1)
                self.url = 'http://www.bilibili.com/video/av{}/index_{}.html'.format(aid, page)
        self.referer = self.url
        self.page = get_content(self.url)
        try:
            self.title = re.search(r'<h1\s*title="([^"]+)"', self.page).group(1)
            if 'subtitle' in kwargs:
                subtitle = kwargs['subtitle']
                self.title = '{} {}'.format(self.title, subtitle)
        except Exception:
            pass
        if 'bangumi.bilibili.com/movie' in self.url:
            self.movie_entry(**kwargs)
        elif 'bangumi.bilibili.com' in self.url:
            self.bangumi_entry(**kwargs)
        elif 'live.bilibili.com' in self.url:
            self.live_entry(**kwargs)
        else:
            self.entry(**kwargs)

    def movie_entry(self, **kwargs):
        patt = r"var\s*aid\s*=\s*'(\d+)'"
        aid = re.search(patt, self.page).group(1)
        page_list = json.loads(get_content('http://www.bilibili.com/widget/getPageList?aid={}'.format(aid)))
        self.title = page_list[0]['pagename']
# False for is_bangumi, old interface works for all free items
        self.download_by_vid(page_list[0]['cid'], False, **kwargs)

    def entry(self, **kwargs):
# tencent player
        tc_flashvars = re.search(r'"bili-cid=\d+&bili-aid=\d+&vid=([^"]+)"', self.page)
        if tc_flashvars:
            tc_flashvars = tc_flashvars.group(1)
        if tc_flashvars is not None:
            self.out = True
            qq_download_by_vid(tc_flashvars, self.title, output_dir=kwargs['output_dir'], merge=kwargs['merge'], info_only=kwargs['info_only'])
            return

        cid = re.search(r'cid=(\d+)', self.page).group(1)
        if cid is not None:
            self.download_by_vid(cid, False, **kwargs)
        else:
# flashvars?
            flashvars = re.search(r'flashvars="([^"]+)"', self.page).group(1)
            if flashvars is None:
                raise Exception('Unsupported page {}'.format(self.url))
            param = flashvars.split('&')[0]
            t, cid = param.split('=')
            t = t.strip()
            cid = cid.strip()
            if t == 'vid':
                sina_download_by_vid(cid, self.title, output_dir=kwargs['output_dir'], merge=kwargs['merge'], info_only=kwargs['info_only'])
            elif t == 'ykid':
                youku_download_by_vid(cid, self.title, output_dir=kwargs['output_dir'], merge=kwargs['merge'], info_only=kwargs['info_only'])
            elif t == 'uid':
                tudou_download_by_id(cid, self.title, output_dir=kwargs['output_dir'], merge=kwargs['merge'], info_only=kwargs['info_only'])
            else:
                raise NotImplementedError('Unknown flashvars {}'.format(flashvars))
            return

    def live_entry(self, **kwargs):
        self.title = re.search(r'<title>([^<]+)', self.page).group(1)
        self.room_id = re.search('ROOMID\s*=\s*(\d+)', self.page).group(1)
        api_url = self.live_api.format(self.room_id)
        json_data = json.loads(get_content(api_url))
        urls = [json_data['durl'][0]['url']]

        self.streams['live'] = {}
        self.streams['live']['src'] = urls
        self.streams['live']['container'] = 'flv'
        self.streams['live']['size'] = 0

    def bangumi_entry(self, **kwargs):
        bangumi_id = re.search(r'(\d+)', self.url).group(1)
        bangumi_data = get_bangumi_info(bangumi_id)
        bangumi_payment = bangumi_data.get('payment')
        if bangumi_payment and bangumi_payment['price'] != '0':
            log.w("It's a paid item")
        ep_ids = collect_bangumi_epids(bangumi_data)

        frag = urllib.parse.urlparse(self.url).fragment
        if frag:
            episode_id = frag
        else:
            episode_id = re.search(r'first_ep_id\s*=\s*"(\d+)"', self.page)
        cont = post_content('http://bangumi.bilibili.com/web_api/get_source', post_data=dict(episode_id=episode_id))
        cid = json.loads(cont)['result']['cid']
        cont = get_content('http://bangumi.bilibili.com/web_api/episode/{}.json'.format(episode_id))
        ep_info = json.loads(cont)['result']['currentEpisode']

        long_title = ep_info['longTitle']
        aid = ep_info['avId']

        idx = 0
        while ep_ids[idx] != episode_id:
            idx += 1

        self.title = '{} [{} {}]'.format(self.title, idx+1, long_title)
        self.download_by_vid(cid, bangumi=True, **kwargs)


def check_oversea():
    url = 'https://interface.bilibili.com/player?id=cid:17778881'
    xml_lines = get_content(url).split('\n')
    for line in xml_lines:
        key = line.split('>')[0][1:]
        if key == 'country':
            value = line.split('>')[1].split('<')[0]
            if value != '中国':
                return True
            else:
                return False
    return False

def check_sid():
    if not cookies:
        return False
    for cookie in cookies:
        if cookie.domain == '.bilibili.com' and cookie.name == 'sid':
            return True
    return False

def fetch_sid(cid, aid):
    url = 'http://interface.bilibili.com/player?id=cid:{}&aid={}'.format(cid, aid)
    cookies = http.cookiejar.CookieJar()
    req = urllib.request.Request(url)
    res = urllib.request.urlopen(url)
    cookies.extract_cookies(res, req)
    for c in cookies:
        if c.domain == '.bilibili.com' and c.name == 'sid':
            return c.value
    raise

def collect_bangumi_epids(json_data):
    eps = json_data['result']['episodes']
    eps = sorted(eps, key=lambda item: float(item['index'].split('-')[0].split('+')[0]))
    result = []
    for ep in eps:
        result.append(ep['episode_id'])
    return result

def get_bangumi_info(bangumi_id):
    BASE_URL = 'http://bangumi.bilibili.com/jsonp/seasoninfo/'
    long_epoch = int(time.time() * 1000)
    req_url = BASE_URL + bangumi_id + '.ver?callback=seasonListCallback&jsonp=jsonp&_=' + str(long_epoch)
    season_data = get_content(req_url)
    season_data = season_data[len('seasonListCallback('):]
    season_data = season_data[: -1 * len(');')]
    json_data = json.loads(season_data)
    return json_data

def get_danmuku_xml(cid):
    return get_content('http://comment.bilibili.com/{}.xml'.format(cid))

def parse_cid_playurl(xml):
    from xml.dom.minidom import parseString
    try:
        urls_list = []
        total_size = 0
        doc = parseString(xml.encode('utf-8'))
        durls = doc.getElementsByTagName('durl')
        cdn_cnt = len(durls[0].getElementsByTagName('url'))
        for i in range(cdn_cnt):
            urls_list.append([])
        for durl in durls:
            size = durl.getElementsByTagName('size')[0]
            total_size += int(size.firstChild.nodeValue)
            cnt = len(durl.getElementsByTagName('url'))
            for i in range(cnt):
                u = durl.getElementsByTagName('url')[i].firstChild.nodeValue
                urls_list[i].append(u)
        return urls_list, total_size
    except Exception as e:
        log.w(e)
        return [], 0

def bilibili_download_playlist_by_url(url, **kwargs):
    url = url_locations([url])[0]
# a bangumi here? possible?
    if 'live.bilibili' in url:
        site.download_by_url(url)
    elif 'bangumi.bilibili' in url:
        bangumi_id = re.search(r'(\d+)', url).group(1)
        bangumi_data = get_bangumi_info(bangumi_id)
        ep_ids = collect_bangumi_epids(bangumi_data)

        base_url = url.split('#')[0]
        for ep_id in ep_ids:
            ep_url = '#'.join([base_url, ep_id])
            Bilibili().download_by_url(ep_url, **kwargs)
    else:
        aid = re.search(r'av(\d+)', url).group(1)
        page_list = json.loads(get_content('http://www.bilibili.com/widget/getPageList?aid={}'.format(aid)))
        page_cnt = len(page_list)
        for no in range(1, page_cnt+1):
            page_url = 'http://www.bilibili.com/video/av{}/index_{}.html'.format(aid, no)
            subtitle = page_list[no-1]['pagename']
            Bilibili().download_by_url(page_url, subtitle=subtitle, **kwargs)

site = Bilibili()
download = site.download_by_url
download_playlist = bilibili_download_playlist_by_url

bilibili_download = download
