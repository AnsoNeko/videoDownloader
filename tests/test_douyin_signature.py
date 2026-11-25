import hashlib
import io
import unittest
from http.cookies import SimpleCookie
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import app
from chinese_extractors import (
    DOUYIN_WEB_SIGN_SALT, DouyinSignatureError, FetcherDouyinIE,
    signed_douyin_request,
)
from yt_dlp.extractor.tiktok import DouyinIE
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import ExtractorError


URL = 'https://www.douyin.com/video/123456'


def rejected(status=403, body=b'Blocked by ArgusSecurityPlugin Uifid Not Found'):
    return ExtractorError('Unable to download JSON metadata', cause=HTTPError(
        Response(io.BytesIO(body), url=URL, headers={}, status=status)))


class DouyinSignatureTests(unittest.TestCase):
    def setUp(self):
        self.ydl = app.yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True})
        self.addCleanup(self.ydl.close)
        self.extractor = FetcherDouyinIE(self.ydl)

    def test_signature_covers_exact_url_and_same_jar_identity(self):
        with patch('chinese_extractors.signed_douyin_params', return_value={'aweme_id': '123456', 'a_bogus': 'x+y/z=='}):
            url, headers = signed_douyin_request('123456', {'UIFID': 'own-visitor', 'UIFID_TEMP': 'other-visitor',
                                                          's_v_web_id': 'verify_own'}, timestamp=1234567890)
        query = urlsplit(url).query
        covered, signature = query.rsplit('&x-secsdk-web-signature=', 1)
        self.assertEqual(covered, 'aweme_id=123456&a_bogus=x%2By%2Fz%3D%3D&verifyFp=verify_own&fp=verify_own&uifid=own-visitor&timestamp=1234567890')
        expected = hashlib.md5(f'own-visitor_1234567890_{DOUYIN_WEB_SIGN_SALT}_{covered}'.encode()).hexdigest()
        self.assertEqual(signature, expected)
        self.assertEqual(headers['uifid'], 'own-visitor')
        self.assertEqual(headers['x-secsdk-web-signature'], expected)
        self.assertEqual(headers['x-secsdk-web-expire'], '1234567890')
        self.assertNotIn('other-visitor', url)

    def test_absent_identity_is_not_fabricated(self):
        url, headers = signed_douyin_request('123456', {}, timestamp=1234567890)
        self.assertNotIn('uifid', parse_qs(urlsplit(url).query))
        self.assertNotIn('x-secsdk-web-signature', headers)
        url, headers = signed_douyin_request('123456', {'UIFID_TEMP': 'temporary-visitor'}, timestamp=1234567890)
        self.assertEqual(headers['uifid'], 'temporary-visitor')

    def test_detail_uses_cookie_jar_and_does_not_reencode_signed_url(self):
        detail = {'aweme_id': '123456', 'video': {'play_addr': {'url_list': ['https://example.test/video.mp4']}}}
        with patch.object(self.extractor, '_get_cookies', return_value=SimpleCookie('UIFID=own-visitor; s_v_web_id=verify_own')), \
                patch.object(self.extractor, '_download_json', return_value={'aweme_detail': detail}) as download:
            self.assertEqual(self.extractor._signed_detail('123456'), detail)
        self.assertNotIn('query', download.call_args.kwargs)
        query = parse_qs(urlsplit(download.call_args.args[0]).query)
        self.assertEqual(query['uifid'], ['own-visitor'])
        self.assertEqual(query['verifyFp'], ['verify_own'])
        self.assertEqual(query['fp'], ['verify_own'])
        self.assertNotIn('Cookie', download.call_args.kwargs['headers'])

    def test_confirmed_signature_rejection_is_specific(self):
        with patch.object(self.extractor, '_download_json', side_effect=rejected()):
            with self.assertRaisesRegex(DouyinSignatureError, '设备签名'):
                self.extractor._signed_detail('123456')

    def test_signature_rejection_reaches_page_fallback(self):
        detail = {'aweme_id': '123456', 'video': {}}
        with patch.object(self.extractor, '_signed_detail', side_effect=DouyinSignatureError('设备签名', expected=True)), \
                patch.object(self.extractor, '_page_detail', return_value=detail) as page, \
                patch.object(self.extractor, '_parse_detail', return_value={'id': '123456'}), \
                patch.object(DouyinIE, '_real_extract') as native:
            self.assertEqual(self.extractor._real_extract(URL)['id'], '123456')
            page.assert_called_once_with('123456')
            native.assert_not_called()

    def test_login_rate_limit_and_generic_denials_do_not_retry_other_routes(self):
        for status in (401, 403, 418, 429):
            with self.subTest(status=status), \
                    patch.object(self.extractor, '_download_json', side_effect=rejected(status, b'access denied')), \
                    patch.object(self.extractor, '_page_detail') as page:
                with self.assertRaises(ExtractorError):
                    self.extractor._real_extract(URL)
                page.assert_not_called()

    def test_errors_strip_ansi_and_redact_visitor_signature(self):
        message = '\x1b[0;31mERROR:\x1b[0m HTTP Error 403 https://www.douyin.com/api?uifid=private-visitor&verifyFp=private-fp&x-secsdk-web-signature=private-signature'
        result = app.readable_download_error(RuntimeError(message), URL)
        self.assertNotIn('\x1b', result)
        self.assertNotIn('private-', result)
        result = app.readable_download_error(DouyinSignatureError('抖音设备签名校验未通过（HTTP 403）', expected=True), URL)
        self.assertIn('设备签名', result)
        self.assertNotIn('请在浏览器完成验证', result)


if __name__ == '__main__':
    unittest.main()
